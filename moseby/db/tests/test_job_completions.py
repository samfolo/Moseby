"""Keep a job outcome, thread result and summary consistent across retries."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import select, update

from moseby.db import tables
from moseby.db.errors import IdempotencyConflict, WriteConflict
from moseby.db.models.jobs import NewJob
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.models.tasks import NewTask
from moseby.db.models.threads import ProjectionUpdate
from moseby.db.operations import job_completions
from moseby.db.repositories import (
    completion_outbox,
    jobs,
    request_deduplication,
    task_claims,
    tasks,
    thread_records,
    threads,
)
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.domain.enums import StaffRole
from moseby.runtime.enums import JobStatus, RunStatus
from moseby.runtime.models.common import ErrorDetails
from moseby.runtime.models.job_outcomes import JobOutcome
from moseby.runtime.models.messages import ToolResultStatus
from moseby.runtime.models.thread_records import ThreadRecordKind, thread_record_adapter


class JobCompletionTests(StayDatabaseTestCase):
    def setUp(self):
        """Give each actor a thread and give the first thread a message with several calls."""
        super().setUp()
        self.actor = {"actor_staff_member_id": identifier("staff_member")}
        self.creator = {"creator_staff_member_id": identifier("staff_member")}
        self.success = JobOutcome(status=JobStatus.SUCCEEDED, result={"rooms": []})
        with transaction(self.engine, write=True) as connection:
            for number in (1, 2):
                self.insert(
                    connection,
                    "staff_members",
                    id=identifier("staff_member", number),
                    hotel_id=identifier("hotel", number),
                    staff_code=f"STAFF-{number}",
                    first_name="Sam",
                    last_name="Staff",
                    role=StaffRole.CONCIERGE.value,
                )
                self.insert(
                    connection,
                    "threads",
                    id=identifier("thread", number),
                    creator_staff_member_id=identifier("staff_member", number),
                    title="Stay",
                    permissions_json='["moseby:read"]',
                    projection_sequence=0,
                    projection_format_version=1,
                    projection_json="{}",
                )
                self.insert(
                    connection,
                    "runs",
                    id=identifier("run", number),
                    thread_id=identifier("thread", number),
                    status=RunStatus.RUNNING.value,
                    recovery_attempts=0,
                )
                thread_records.append(
                    connection,
                    thread_record_adapter.validate_python(
                        dict(
                            id=identifier("thread_record", number * 100),
                            thread_id=identifier("thread", number),
                            sequence=1,
                            kind=ThreadRecordKind.THREAD_CREATED,
                            created_at=to_datetime(NOW),
                            format_version=1,
                            payload={
                                "creator_staff_member_id": identifier(
                                    "staff_member", number
                                ),
                                "permissions": ["moseby:read"],
                            },
                        )
                    ),
                    creator_staff_member_id=identifier("staff_member", number),
                )
            thread_records.append(
                connection,
                thread_record_adapter.validate_python(
                    dict(
                        id=identifier("thread_record", 101),
                        thread_id=identifier("thread"),
                        run_id=identifier("run"),
                        sequence=2,
                        kind=ThreadRecordKind.ASSISTANT_MESSAGE,
                        created_at=to_datetime(NOW),
                        format_version=1,
                        payload={
                            "tool_calls": [
                                {"id": f"call-{n}", "name": "lookup", "arguments": {}}
                                for n in range(1, 7)
                            ]
                        },
                    )
                ),
                **self.creator,
            )

    def prepare(self, connection, number=1, *, tool=True, standalone=False, fail=False):
        """Create a job and finish its single task through the worker repositories."""
        key = RequestKey(
            **self.actor, operation="lookup", request_id=f"request-{number}"
        )
        request_deduplication.accept(connection, key, {}, now=NOW)
        job = jobs.create(
            connection,
            NewJob(
                id=identifier("job", number),
                request_key=key,
                handler="lookup",
                phase="FINAL",
                input={},
                thread_id=None if standalone else identifier("thread"),
                run_id=identifier("run") if tool and not standalone else None,
                source_record_id=identifier("thread_record", 101)
                if tool and not standalone
                else None,
                tool_call_id=f"call-{number}" if tool and not standalone else None,
            ),
            now=NOW,
        )
        task = tasks.create(
            connection,
            NewTask(
                id=identifier("task", number),
                job_id=job.id,
                step_key="lookup",
                handler="lookup",
                input={},
                available_at=NOW,
            ),
            **self.actor,
            now=NOW,
        )
        claim = task_claims.claim(
            connection,
            task.id,
            **self.actor,
            worker_id="worker",
            now=NOW + 1,
            expires_at=NOW + 100,
        )
        if fail:
            tasks.fail(
                connection,
                task.id,
                claim.token,
                {"code": "UNAVAILABLE", "message": "Service unavailable"},
                **self.actor,
                now=NOW + 2,
            )
        else:
            tasks.succeed(
                connection,
                task.id,
                claim.token,
                self.success.result,
                **self.actor,
                now=NOW + 2,
            )
        return job

    def finish(self, connection, number=1, *, outcome=None, completion_number=None):
        return job_completions.finish(
            connection,
            identifier("job", number),
            outcome or self.success,
            expected_phase="FINAL",
            completion_id=identifier("completion", completion_number or number),
            **self.actor,
            now=NOW + 3,
        )

    def deliver(
        self, connection, number=1, *, record_number=102, expected_sequence=0, head=2
    ):
        return job_completions.deliver(
            connection,
            identifier("completion", number),
            record_id=identifier("thread_record", record_number),
            projection=ProjectionUpdate(
                expected_sequence=expected_sequence,
                expected_history_sequence=head,
                value={"latest_job": identifier("job", number)},
            ),
            **self.actor,
            now=NOW + 4,
        )

    def test_finish_saves_one_outcome_and_outbox_entry_across_retries(self):
        """When completion is retried with another candidate ID, it returns the original delivery."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            first = self.finish(connection)
            second = self.finish(connection, completion_number=99)
            self.assertEqual(first, second)
            self.assertEqual(first.job.status, JobStatus.SUCCEEDED)
            self.assertEqual(
                first.completion.payload, self.success.model_dump(mode="json")
            )
            self.assertIsNone(
                completion_outbox.find_by_id(
                    connection, identifier("completion", 99), **self.actor
                )
            )
            with self.assertRaises(IdempotencyConflict):
                self.finish(
                    connection,
                    outcome=JobOutcome(
                        status=JobStatus.SUCCEEDED, result={"different": True}
                    ),
                )

    def test_parent_waits_for_all_tasks_and_the_expected_workflow_phase(self):
        """When a branch remains ready or the phase differs, the parent cannot finish."""
        with transaction(self.engine, write=True) as connection:
            job = self.prepare(connection)
            with self.assertRaises(WriteConflict):
                job_completions.finish(
                    connection,
                    job.id,
                    self.success,
                    expected_phase="OLD",
                    completion_id=identifier("completion"),
                    **self.actor,
                    now=NOW + 3,
                )
            with self.assertRaises(WriteConflict):
                job_completions.finish(
                    connection,
                    job.id,
                    self.success,
                    expected_phase="FINAL",
                    completion_id=identifier("completion"),
                    **self.actor,
                    now=NOW + 1,
                )
            tasks.create(
                connection,
                NewTask(
                    id=identifier("task", 99),
                    job_id=job.id,
                    step_key="other",
                    handler="lookup",
                    input={},
                    available_at=NOW + 2,
                ),
                **self.actor,
                now=NOW + 2,
            )
            for outcome in (
                self.success,
                JobOutcome(
                    status=JobStatus.FAILED,
                    error=ErrorDetails(code="FAILED", message="Failure"),
                ),
            ):
                with self.assertRaises(WriteConflict):
                    self.finish(connection, outcome=outcome)
            self.assertIsNone(
                jobs.find_by_id(connection, job.id, **self.actor).finished_at
            )
            self.assertIsNone(
                completion_outbox.find_by_job_id(connection, job.id, **self.actor)
            )

    def test_failed_tasks_prevent_success_but_allow_a_final_failure(self):
        """When a task fails, the settled job can record that failure but cannot claim success."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection, fail=True)
            with self.assertRaises(WriteConflict):
                self.finish(connection)
            failed = JobOutcome(
                status=JobStatus.FAILED,
                error=ErrorDetails(code="UNAVAILABLE", message="Service unavailable"),
            )
            self.finish(connection, outcome=failed)
            record = self.deliver(connection)
            self.assertEqual(record.payload["error"]["code"], "UNAVAILABLE")
            self.assertEqual(record.payload["job_id"], identifier("job"))
            self.assertNotIn("result", record.payload)

    def test_outbox_failure_rolls_back_the_parent_even_when_caught(self):
        """When delivery cannot be saved, a caught exception leaves the job unfinished."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            with self.assertRaises(ValueError):
                job_completions.finish(
                    connection,
                    identifier("job"),
                    self.success,
                    expected_phase="FINAL",
                    **self.actor,
                    now=NOW + 3,
                )
            self.assertIsNone(
                jobs.find_by_id(connection, identifier("job"), **self.actor).finished_at
            )
            with patch(
                "moseby.db.operations.job_completions.completion_outbox.create",
                side_effect=RuntimeError("failed delivery insert"),
            ):
                with self.assertRaises(RuntimeError):
                    self.finish(connection)
            self.assertIsNone(
                jobs.find_by_id(connection, identifier("job"), **self.actor).finished_at
            )
            self.assertIsNone(
                completion_outbox.find_by_job_id(
                    connection, identifier("job"), **self.actor
                )
            )

    def test_delivery_advances_history_projection_and_receipt_once(self):
        """When a delivery is retried, the history and summary retain the first saved result."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            self.finish(connection)
            record = self.deliver(connection)
            replay = self.deliver(connection, record_number=999)
            self.assertEqual(record, replay)
            self.assertEqual(record.sequence, 3)
            self.assertEqual(record.kind, ThreadRecordKind.TOOL_RESULT)
            self.assertEqual(record.tool_call_id, "call-1")
            self.assertEqual(record.created_at, NOW + 4)
            self.assertEqual(record.payload["result"], {"rooms": []})
            summary = threads.find_by_id(
                connection, identifier("thread"), **self.creator
            )
            self.assertEqual(
                (summary.projection_sequence, summary.projection),
                (3, {"latest_job": identifier("job")}),
            )
            receipt = completion_outbox.find_by_job_id(
                connection, identifier("job"), **self.actor
            )
            self.assertEqual(
                (receipt.record_id, receipt.appended_at), (record.id, NOW + 4)
            )
            self.assertEqual(
                len(
                    thread_records.find_all_by_thread_id(
                        connection, identifier("thread"), **self.creator
                    ).items
                ),
                3,
            )

    def test_stale_projection_or_history_leaves_the_completion_pending(self):
        """When the summary input is stale, delivery rolls back its record and retains the pending entry."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            self.finish(connection)
            for expected, head in ((1, 2), (0, 1)):
                with self.assertRaises(WriteConflict):
                    self.deliver(connection, expected_sequence=expected, head=head)
                self.assertIsNone(
                    thread_records.find_by_id(
                        connection, identifier("thread_record", 102), **self.creator
                    )
                )
                self.assertIsNone(
                    completion_outbox.find_by_id(
                        connection, identifier("completion"), **self.actor
                    ).record_id
                )
            self.deliver(connection)

    def test_delivery_retries_after_a_steer_advances_history_and_projection(self):
        """When steering arrives first, delivery keeps it and retries with an updated summary."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            self.finish(connection)

        # Accept the new message and its summary together, as steering would do.
        with transaction(self.engine, write=True) as connection:
            steer = thread_records.append(
                connection,
                thread_record_adapter.validate_python(
                    dict(
                        id=identifier("thread_record", 102),
                        thread_id=identifier("thread"),
                        run_id=identifier("run"),
                        sequence=3,
                        kind=ThreadRecordKind.USER_MESSAGE,
                        created_at=to_datetime(NOW + 4),
                        format_version=1,
                        payload={"text": "Please look for a room with twin beds."},
                    )
                ),
                **self.creator,
            )
            threads.save_projection(
                connection,
                identifier("thread"),
                ProjectionUpdate(
                    expected_sequence=0,
                    expected_history_sequence=2,
                    value={"latest_user_message": steer.id},
                ),
                **self.creator,
                now=NOW + 4,
            )

        with transaction(self.engine, write=True) as connection:
            with self.assertRaises(WriteConflict):
                self.deliver(connection, record_number=103)
            receipt = completion_outbox.find_by_id(
                connection, identifier("completion"), **self.actor
            )
            self.assertIsNone(receipt.record_id)
            self.assertIsNone(
                thread_records.find_by_id(
                    connection, identifier("thread_record", 103), **self.creator
                )
            )

        # Retry from the current history, retaining the new message in the summary.
        with transaction(self.engine, write=True) as connection:
            summary = threads.find_by_id(
                connection, identifier("thread"), **self.creator
            )
            last = thread_records.find_last_by_thread_id(
                connection, identifier("thread"), **self.creator
            )
            value = {**summary.projection, "latest_job": identifier("job")}
            result = job_completions.deliver(
                connection,
                identifier("completion"),
                record_id=identifier("thread_record", 103),
                projection=ProjectionUpdate(
                    expected_sequence=summary.projection_sequence,
                    expected_history_sequence=last.sequence,
                    value=value,
                ),
                **self.actor,
                now=NOW + 5,
            )
            self.assertEqual(result.sequence, 4)
            self.assertEqual(
                thread_records.find_by_id(connection, steer.id, **self.creator), steer
            )
            saved = threads.find_by_id(connection, identifier("thread"), **self.creator)
            self.assertEqual(saved.projection_sequence, 4)
            self.assertEqual(saved.projection, value)
            self.assertEqual(
                completion_outbox.find_by_id(
                    connection, identifier("completion"), **self.actor
                ).record_id,
                result.id,
            )

    def test_receipt_failure_rolls_back_both_record_and_projection(self):
        """When the final receipt fails, catching the error leaves neither earlier delivery write behind."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            self.finish(connection)
            with patch(
                "moseby.db.operations.job_completions.completion_outbox.mark_delivered",
                side_effect=RuntimeError("receipt failed"),
            ):
                with self.assertRaises(RuntimeError):
                    self.deliver(connection)
            self.assertEqual(
                threads.find_by_id(
                    connection, identifier("thread"), **self.creator
                ).projection_sequence,
                0,
            )
            self.assertIsNone(
                thread_records.find_by_id(
                    connection, identifier("thread_record", 102), **self.creator
                )
            )
            self.assertIsNone(
                completion_outbox.find_by_id(
                    connection, identifier("completion"), **self.actor
                ).record_id
            )

    def test_late_result_does_not_restart_a_cancelled_run(self):
        """When the run has stopped, its completed job still delivers evidence without changing the run."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == identifier("run"))
                .values(status=RunStatus.CANCELLED.value, finished_at=NOW + 2)
            )
            self.finish(connection)
            self.deliver(connection)
            self.assertEqual(
                connection.scalar(
                    select(tables.runs.c.status).where(
                        tables.runs.c.id == identifier("run")
                    )
                ),
                RunStatus.CANCELLED,
            )

    def test_standalone_and_thread_linked_non_tool_jobs_have_distinct_delivery(self):
        """When a job has no tool call, it keeps a standalone outcome or emits a control record."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection, standalone=True)
            result = job_completions.finish(
                connection,
                identifier("job"),
                self.success,
                expected_phase="FINAL",
                **self.actor,
                now=NOW + 3,
            )
            self.assertIsNone(result.completion)
            self.prepare(connection, 2, tool=False)
            self.finish(connection, 2)
            record = self.deliver(connection, 2)
            self.assertEqual(record.kind, ThreadRecordKind.CONTROL_EVENT)
            self.assertEqual(record.payload["name"], "job.finished")
            self.assertEqual(record.payload["data"]["job_id"], identifier("job", 2))
            self.assertIsNone(record.run_id)

    def test_cancelled_job_delivers_a_reason_and_preserves_its_outcome(self):
        """When a settled job is cancelled, its tool result carries the saved reason."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection, fail=True)
            cancelled = JobOutcome(
                status=JobStatus.CANCELLED,
                error=ErrorDetails(code="CANCELLED", message="The guest changed plans"),
            )
            self.finish(connection, outcome=cancelled)
            record = self.deliver(connection)
            self.assertEqual(record.payload["reason"], "The guest changed plans")
            self.assertEqual(
                jobs.find_by_id(connection, identifier("job"), **self.actor).status,
                JobStatus.CANCELLED,
            )

    def test_ownership_checks_apply_to_completion_writes_and_receipts(self):
        """When another actor knows the job or delivery ID, they still cannot finish or deliver it."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            with self.assertRaises(WriteConflict):
                job_completions.finish(
                    connection,
                    identifier("job"),
                    self.success,
                    expected_phase="FINAL",
                    completion_id=identifier("completion"),
                    actor_staff_member_id=identifier("staff_member", 2),
                    now=NOW + 3,
                )
            self.finish(connection)
            with self.assertRaises(WriteConflict):
                job_completions.deliver(
                    connection,
                    identifier("completion"),
                    record_id=identifier("thread_record", 999),
                    projection=ProjectionUpdate(
                        expected_sequence=0, expected_history_sequence=2, value={}
                    ),
                    actor_staff_member_id=identifier("staff_member", 2),
                    now=NOW + 4,
                )
            self.assertIsNone(
                completion_outbox.find_by_id(
                    connection, identifier("completion"), **self.actor
                ).record_id
            )

    def test_tool_results_must_answer_a_call_in_the_source_message(self):
        """When a tool ID was never in its source message, the result cannot enter history."""
        with transaction(self.engine, write=True) as connection:
            record = thread_record_adapter.validate_python(
                dict(
                    id=identifier("thread_record", 102),
                    thread_id=identifier("thread"),
                    run_id=identifier("run"),
                    sequence=3,
                    kind=ThreadRecordKind.TOOL_RESULT,
                    source_record_id=identifier("thread_record", 101),
                    tool_call_id="invented",
                    created_at=to_datetime(NOW + 4),
                    format_version=1,
                    payload={"status": ToolResultStatus.SUCCEEDED, "result": {}},
                )
            )
            with self.assertRaises(ValueError):
                thread_records.append(connection, record, **self.creator)
            self.assertIsNone(
                thread_records.find_by_id(connection, record.id, **self.creator)
            )

    def test_outcome_models_reject_contradictory_results(self):
        """When an outcome claims success with an error or failure without one, validation rejects it."""
        for payload in (
            {
                "status": JobStatus.SUCCEEDED,
                "error": {"code": "FAILED", "message": "Failure"},
            },
            {"status": JobStatus.FAILED},
            {"status": JobStatus.CANCELLED},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                JobOutcome.model_validate(payload)

    def test_two_deliverers_return_the_same_record(self):
        """When two connections deliver the same completion, both receive one persisted result."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            self.finish(connection)
        barrier = Barrier(2)

        def deliver(number):
            barrier.wait(timeout=5)
            with transaction(self.engine, write=True) as connection:
                return self.deliver(connection, record_number=number).id

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(deliver, number) for number in (102, 103)]
            records = [future.result(timeout=10) for future in futures]
        self.assertEqual(records[0], records[1])
        with self.engine.connect() as connection:
            self.assertEqual(
                len(
                    thread_records.find_all_by_thread_id(
                        connection, identifier("thread"), **self.creator
                    ).items
                ),
                3,
            )

    def test_record_replays_and_receipts_reject_different_saved_content(self):
        """When a record ID or receipt is reused, it cannot silently refer to a different result."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            self.finish(connection)
            record = self.deliver(connection)
            decoded = thread_record_adapter.validate_python(
                record.model_dump() | {"created_at": to_datetime(record.created_at)}
            )
            self.assertEqual(
                thread_records.append(connection, decoded, **self.creator), record
            )
            changed = thread_record_adapter.validate_python(
                decoded.model_dump()
                | {
                    "payload": {
                        "status": ToolResultStatus.SUCCEEDED,
                        "result": {"different": True},
                        "job_id": identifier("job"),
                    }
                }
            )
            with self.assertRaises(IdempotencyConflict):
                thread_records.append(connection, changed, **self.creator)
            receipt = completion_outbox.find_by_id(
                connection, identifier("completion"), **self.actor
            )
            self.assertEqual(
                completion_outbox.mark_delivered(
                    connection, receipt.id, record.id, **self.actor, now=NOW + 10
                ),
                receipt,
            )
            with self.assertRaises(IdempotencyConflict):
                completion_outbox.mark_delivered(
                    connection,
                    receipt.id,
                    identifier("thread_record", 999),
                    **self.actor,
                    now=NOW + 10,
                )

    def test_receipt_rejects_a_record_with_the_right_call_but_wrong_result(self):
        """When a record answers the right call with different content, it cannot acknowledge this completion."""
        with transaction(self.engine, write=True) as connection:
            self.prepare(connection)
            self.finish(connection)
            wrong = thread_record_adapter.validate_python(
                dict(
                    id=identifier("thread_record", 102),
                    thread_id=identifier("thread"),
                    run_id=identifier("run"),
                    sequence=3,
                    kind=ThreadRecordKind.TOOL_RESULT,
                    source_record_id=identifier("thread_record", 101),
                    tool_call_id="call-1",
                    created_at=to_datetime(NOW + 4),
                    format_version=1,
                    payload={
                        "status": ToolResultStatus.SUCCEEDED,
                        "job_id": identifier("job"),
                        "result": {"wrong": True},
                    },
                )
            )
            with self.assertRaises(WriteConflict):
                with connection.begin_nested():
                    thread_records.append(connection, wrong, **self.creator)
                    completion_outbox.mark_delivered(
                        connection,
                        identifier("completion"),
                        wrong.id,
                        **self.actor,
                        now=NOW + 4,
                    )
            self.assertIsNone(
                thread_records.find_by_id(connection, wrong.id, **self.creator)
            )
            self.assertIsNone(
                completion_outbox.find_by_id(
                    connection, identifier("completion"), **self.actor
                ).record_id
            )
            self.deliver(connection)

    def test_initial_record_must_match_the_saved_thread_identity(self):
        """When the first record names different permissions or a different creator, it is rejected."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "threads",
                id=identifier("thread", 3),
                creator_staff_member_id=identifier("staff_member"),
                title="Stay",
                permissions_json='["moseby:read"]',
                projection_sequence=0,
                projection_format_version=1,
                projection_json="{}",
            )
            for creator, permissions in (
                (identifier("staff_member", 2), ["moseby:read"]),
                (identifier("staff_member"), ["moseby:write"]),
            ):
                record = thread_record_adapter.validate_python(
                    dict(
                        id=identifier("thread_record", 300),
                        thread_id=identifier("thread", 3),
                        sequence=1,
                        kind=ThreadRecordKind.THREAD_CREATED,
                        format_version=1,
                        created_at=to_datetime(NOW),
                        payload={
                            "creator_staff_member_id": creator,
                            "permissions": permissions,
                        },
                    )
                )
                with self.assertRaises(WriteConflict):
                    thread_records.append(connection, record, **self.creator)
            self.assertIsNone(
                thread_records.find_last_by_thread_id(
                    connection, identifier("thread", 3), **self.creator
                )
            )
