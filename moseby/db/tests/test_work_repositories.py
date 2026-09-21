"""Read accepted work and its outcomes without crossing actor or thread boundaries."""

import json

from sqlalchemy import update

from moseby.db import tables
from moseby.db.models.completion_outbox import CompletionFilters
from moseby.db.models.jobs import JobFilters
from moseby.db.models.tasks import TaskFilters
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import (
    completion_outbox,
    jobs,
    request_deduplication,
    task_claims,
    tasks,
)
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction
from moseby.domain.enums import StaffRole
from moseby.runtime.enums import JobStatus, RunStatus, TaskStatus
from moseby.runtime.models.thread_records import ThreadRecordKind


class WorkRepositoryTests(StayDatabaseTestCase):
    def setUp(self):
        """Give three staff members work, including deliberately mismatched thread links."""
        super().setUp()
        self.scope = {"actor_staff_member_id": identifier("staff_member")}
        self.record_sequences = {1: 2, 2: 2, 3: 2}
        with transaction(self.engine, write=True) as connection:
            for number in (1, 2, 3):
                actor = identifier("staff_member", number)
                self.insert(
                    connection,
                    "staff_members",
                    id=actor,
                    hotel_id=identifier("hotel", 2 if number == 3 else 1),
                    staff_code=f"STAFF-{number}",
                    first_name="Sam",
                    last_name="Staff",
                    role=StaffRole.CONCIERGE.value,
                )
                self.insert(
                    connection,
                    "threads",
                    id=identifier("thread", number),
                    creator_staff_member_id=actor,
                    title="Work",
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
                self.insert(
                    connection,
                    "thread_records",
                    id=identifier("thread_record", number * 100 + 1),
                    thread_id=identifier("thread", number),
                    sequence=1,
                    kind=ThreadRecordKind.THREAD_CREATED.value,
                    format_version=1,
                    payload_json=json.dumps(
                        {
                            "creator_staff_member_id": actor,
                            "permissions": ["moseby:read"],
                        }
                    ),
                )
                self.insert(
                    connection,
                    "thread_records",
                    id=identifier("thread_record", number * 100 + 2),
                    thread_id=identifier("thread", number),
                    sequence=2,
                    kind=ThreadRecordKind.ASSISTANT_MESSAGE.value,
                    format_version=1,
                    run_id=identifier("run", number),
                    payload_json='{"tool_calls":[{"id":"call-shared","name":"demo.lookup","arguments":{}}]}',
                )
            for number, actor, thread, status in (
                (1, 1, None, JobStatus.QUEUED),
                (2, 1, 1, JobStatus.RUNNING),
                (3, 1, 1, JobStatus.SUCCEEDED),
                (4, 1, 1, JobStatus.FAILED),
                (5, 1, 1, JobStatus.CANCELLED),
                (6, 2, 2, JobStatus.SUCCEEDED),
                (7, 3, 3, JobStatus.SUCCEEDED),
                (8, 1, 2, JobStatus.SUCCEEDED),
                (9, 2, 1, JobStatus.SUCCEEDED),
                (10, 1, None, JobStatus.SUCCEEDED),
                (11, 1, 1, JobStatus.WAITING),
            ):
                self.add_job(connection, number, actor, thread, status)
            self.add_task(
                connection,
                22,
                2,
                TaskStatus.READY,
                attempt_count=2,
                available_at=NOW + 200,
            )
            self.add_task(connection, 23, 2, TaskStatus.RUNNING, attempt_count=4)
            for task, expiry in (
                (21, NOW + 50),
                (23, NOW + 20),
                (61, NOW + 50),
                (81, NOW + 50),
                (91, NOW + 50),
            ):
                self.insert(
                    connection,
                    "task_claims",
                    task_id=identifier("task", task),
                    token=f"token-{task}",
                    worker_id="worker-1",
                    claimed_at=NOW + 10,
                    heartbeat_at=NOW + 15,
                    expires_at=expiry,
                    updated_at=NOW + 15,
                )

    def add_task(self, connection, number, job, status, **changes):
        """Save a task with timing and outcome fields that agree with its status."""
        finished = status in (
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )
        values = dict(
            id=identifier("task", number),
            job_id=identifier("job", job),
            step_key=f"step-{number}",
            handler="demo.task",
            format_version=1,
            input_json='{"query":"rooms"}',
            status=status.value,
            attempt_count=3,
            available_at=NOW,
            started_at=NOW + 5 if status != TaskStatus.READY else None,
            finished_at=NOW + 40 if finished else None,
            updated_at=NOW + 40,
            result_json='{"count":2}' if status == TaskStatus.SUCCEEDED else None,
            error_json='{"code":"RETRY","message":"Try again"}'
            if status in (TaskStatus.RUNNING, TaskStatus.FAILED)
            else None,
        )
        self.insert(connection, "tasks", **(values | changes))

    def add_job(self, connection, number, actor, thread, status):
        """Save a command, its job and a task; finished threaded jobs also get a result delivery."""
        operation = "demo.lookup" if number in (1, 6) else f"demo.operation-{number}"
        request_id = "shared" if number in (1, 6, 10) else f"request-{number}"
        self.insert(
            connection,
            "request_deduplication",
            actor_staff_member_id=identifier("staff_member", actor),
            operation=operation,
            request_id=request_id,
            request_json=json.dumps({"number": number, "path": {"id": number}}),
            response_json=json.dumps({"job_id": identifier("job", number)})
            if number == 3
            else None,
        )
        finished = status in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )
        self.insert(
            connection,
            "jobs",
            id=identifier("job", number),
            actor_staff_member_id=identifier("staff_member", actor),
            operation=operation,
            request_id=request_id,
            thread_id=identifier("thread", thread) if thread else None,
            run_id=identifier("run", thread) if thread else None,
            source_record_id=identifier("thread_record", 102) if number == 2 else None,
            tool_call_id="call-shared" if number == 2 else None,
            handler="demo.workflow",
            phase="DONE" if finished else "START",
            format_version=1,
            input_json=json.dumps({"number": number, "options": {"rooms": []}}),
            status=status.value,
            result_json='{"count":2}' if status == JobStatus.SUCCEEDED else None,
            error_json='{"code":"FAILED","message":"No result"}'
            if status == JobStatus.FAILED
            else None,
            finished_at=NOW + 40 if finished else None,
            updated_at=NOW + 40,
        )
        task_status = (
            TaskStatus.READY
            if status == JobStatus.QUEUED
            else TaskStatus[f"{status.name}"]
        )
        self.add_task(connection, number * 10 + 1, number, task_status)
        if finished and thread:
            self.insert(
                connection,
                "completion_outbox",
                id=identifier("completion", number),
                job_id=identifier("job", number),
                thread_id=identifier("thread", thread),
                format_version=1,
                payload_json=json.dumps({"job": number, "status": status.value}),
            )
        if number == 4:
            self.deliver(connection, number, thread)

    def deliver(self, connection, job, thread):
        """Append a control result and its delivery receipt in the caller's transaction."""
        self.record_sequences[thread] += 1
        sequence = self.record_sequences[thread]
        record = identifier("thread_record", thread * 100 + sequence)
        self.insert(
            connection,
            "thread_records",
            id=record,
            thread_id=identifier("thread", thread),
            sequence=sequence,
            kind=ThreadRecordKind.CONTROL_EVENT.value,
            format_version=1,
            run_id=identifier("run", thread),
            payload_json='{"name":"job.finished","data":{}}',
        )
        connection.execute(
            update(tables.completion_outbox)
            .where(tables.completion_outbox.c.job_id == identifier("job", job))
            .values(record_id=record, appended_at=NOW + 100, updated_at=NOW + 100)
        )

    def test_job_and_child_lookups_require_both_actor_and_thread_ownership(self):
        """When either the actor or thread owner differs, the job and its children are hidden."""
        cases = (
            (jobs, "job", [3, 6, 7, 8, 9, 999]),
            (tasks, "task", [31, 61, 71, 81, 91, 999]),
            (completion_outbox, "completion", [3, 6, 7, 8, 9, 999]),
        )
        with transaction(self.engine) as connection:
            for repository, prefix, numbers in cases:
                with self.subTest(repository=repository.__name__):
                    ids = [identifier(prefix, number) for number in numbers]
                    self.assertIsNotNone(
                        repository.find_by_id(connection, ids[0], **self.scope)
                    )
                    for id in ids[1:]:
                        self.assertIsNone(
                            repository.find_by_id(connection, id, **self.scope)
                        )
                    self.assertEqual(
                        list(
                            repository.find_by_ids(
                                connection, ids + [ids[0]], **self.scope
                            )
                        ),
                        [ids[0]],
                    )
                    self.assertEqual(
                        repository.find_by_ids(connection, [], **self.scope), {}
                    )
                    with self.assertRaises(ValueError):
                        repository.find_by_ids(connection, [ids[0]] * 101, **self.scope)
                    other = {"actor_staff_member_id": identifier("staff_member", 2)}
                    self.assertIsNotNone(
                        repository.find_by_id(connection, ids[1], **other)
                    )
                    self.assertIsNone(
                        repository.find_by_id(connection, ids[3], **other)
                    )
                    self.assertIsNone(
                        repository.find_by_id(connection, ids[4], **other)
                    )

    def test_job_pages_preserve_standalone_jobs_outcomes_and_workflow_fields(self):
        """When a job has no thread or has already finished, its actor can still read it."""
        with transaction(self.engine) as connection:
            first = jobs.find_all(connection, **self.scope, page=PageRequest(limit=3))
            rest = jobs.find_all(
                connection, **self.scope, page=PageRequest(cursor=first.next_cursor)
            )
            rows = first.items + rest.items
            self.assertEqual(
                [row.id for row in rows],
                [identifier("job", n) for n in (1, 2, 3, 4, 5, 10, 11)],
            )
            self.assertIsNone(rows[0].thread_id)
            self.assertEqual(
                (rows[1].handler, rows[1].phase), ("demo.workflow", "START")
            )
            self.assertEqual(rows[1].input["options"], {"rooms": []})
            self.assertEqual(rows[2].result, {"count": 2})
            self.assertEqual(rows[3].error["code"], "FAILED")
            self.assertIs(rows[4].status, JobStatus.CANCELLED)
            self.assertIsNone(rest.next_cursor)

    def test_request_lookup_uses_actor_operation_and_request_id_together(self):
        """When a request ID is reused for another actor or operation, it finds a different command."""
        with transaction(self.engine) as connection:
            for actor, operation, number in (
                (1, "demo.lookup", 1),
                (2, "demo.lookup", 6),
                (1, "demo.operation-10", 10),
            ):
                scope = {"actor_staff_member_id": identifier("staff_member", actor)}
                job = jobs.find_by_operation_and_request_id(
                    connection, operation, "shared", **scope
                )
                receipt = request_deduplication.find_by_operation_and_request_id(
                    connection, operation, "shared", **scope
                )
                self.assertEqual(job.id, identifier("job", number))
                self.assertEqual(
                    receipt.request, {"number": number, "path": {"id": number}}
                )
            for repository in (jobs, request_deduplication):
                for operation, request in (
                    ("missing", "shared"),
                    ("demo.lookup", "unknown"),
                    ("demo.operation-6", "shared"),
                ):
                    self.assertIsNone(
                        repository.find_by_operation_and_request_id(
                            connection, operation, request, **self.scope
                        )
                    )
            self.assertIsNone(
                jobs.find_by_operation_and_request_id(
                    connection, "demo.operation-8", "request-8", **self.scope
                )
            )

    def test_ledger_distinguishes_missing_pending_and_empty_saved_responses(self):
        """When the ledger has an empty saved response, it is still different from no response."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "request_deduplication",
                actor_staff_member_id=identifier("staff_member"),
                operation="guests.update",
                request_id="sync",
                request_json='{"payload":{"name":"Sam"}}',
                response_json="{}",
            )
            read = request_deduplication.find_by_operation_and_request_id
            self.assertIsNone(
                read(connection, "guests.update", "missing", **self.scope)
            )
            self.assertIsNone(
                read(connection, "demo.lookup", "shared", **self.scope).response
            )
            self.assertEqual(
                read(connection, "guests.update", "sync", **self.scope).response, {}
            )
            self.assertEqual(
                read(
                    connection, "demo.operation-3", "request-3", **self.scope
                ).response,
                {"job_id": identifier("job", 3)},
            )

    def test_tool_job_lookup_uses_the_source_record_as_well_as_the_call_id(self):
        """When call IDs repeat in different messages, the source record selects the job."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "request_deduplication",
                actor_staff_member_id=identifier("staff_member", 2),
                operation="demo.other",
                request_id="tool",
                request_json="{}",
            )
            self.insert(
                connection,
                "jobs",
                id=identifier("job", 20),
                actor_staff_member_id=identifier("staff_member", 2),
                operation="demo.other",
                request_id="tool",
                thread_id=identifier("thread", 2),
                run_id=identifier("run", 2),
                source_record_id=identifier("thread_record", 202),
                tool_call_id="call-shared",
                handler="demo.workflow",
                phase="START",
                format_version=1,
                input_json="{}",
                status=JobStatus.QUEUED.value,
            )
            read = jobs.find_by_source_record_id_and_tool_call_id
            self.assertEqual(
                read(
                    connection,
                    identifier("thread_record", 102),
                    "call-shared",
                    **self.scope,
                ).id,
                identifier("job", 2),
            )
            self.assertIsNone(
                read(
                    connection, identifier("thread_record", 102), "other", **self.scope
                )
            )
            self.assertIsNone(
                read(
                    connection,
                    identifier("thread_record", 202),
                    "call-shared",
                    **self.scope,
                )
            )
            self.assertEqual(
                read(
                    connection,
                    identifier("thread_record", 202),
                    "call-shared",
                    actor_staff_member_id=identifier("staff_member", 2),
                ).id,
                identifier("job", 20),
            )

    def test_job_filters_intersect_before_paging(self):
        """When a run and statuses are supplied, every returned job must match both."""
        with transaction(self.engine) as connection:
            filters = JobFilters(
                thread_ids=[identifier("thread")],
                run_ids=[identifier("run")],
                statuses=[JobStatus.RUNNING, JobStatus.WAITING],
            )
            first = jobs.search(
                connection, filters, **self.scope, page=PageRequest(limit=1)
            )
            rest = jobs.search(
                connection,
                JobFilters(
                    thread_ids=[identifier("thread")],
                    run_ids=[identifier("run")],
                    statuses=[JobStatus.WAITING, JobStatus.RUNNING, JobStatus.WAITING],
                ),
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.id for row in first.items + rest.items],
                [identifier("job", 2), identifier("job", 11)],
            )
            for read, prefix in (
                (jobs.find_all_by_thread_id, "thread"),
                (jobs.find_all_by_run_id, "run"),
            ):
                self.assertEqual(
                    [
                        row.id
                        for row in read(
                            connection, identifier(prefix), **self.scope
                        ).items
                    ],
                    [identifier("job", n) for n in (2, 3, 4, 5, 11)],
                )
                self.assertEqual(
                    read(connection, identifier(prefix, 2), **self.scope).items, []
                )
            self.assertEqual(
                jobs.search(
                    connection, JobFilters(ids=[identifier("job", 8)]), **self.scope
                ).items,
                [],
            )

    def test_task_reads_keep_retries_and_future_work_on_the_same_task(self):
        """When a task is retried or deferred, its identity and saved progress remain readable."""
        with transaction(self.engine) as connection:
            read = tasks.find_by_job_id_and_step_key
            retried = read(connection, identifier("job", 2), "step-21", **self.scope)
            self.assertEqual(
                (retried.id, retried.attempt_count), (identifier("task", 21), 3)
            )
            self.assertEqual(retried.error["code"], "RETRY")
            self.assertEqual(retried.input, {"query": "rooms"})
            self.assertEqual(
                tasks.find_by_id(
                    connection, identifier("task", 22), **self.scope
                ).available_at,
                NOW + 200,
            )
            self.assertIsNone(
                read(connection, identifier("job", 1), "step-21", **self.scope)
            )
            self.assertIsNone(
                read(connection, identifier("job", 8), "step-81", **self.scope)
            )
            first = tasks.find_all_by_job_id(
                connection,
                identifier("job", 2),
                **self.scope,
                page=PageRequest(limit=1),
            )
            rest = tasks.find_all_by_job_id(
                connection,
                identifier("job", 2),
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.id for row in first.items + rest.items],
                [identifier("task", n) for n in (21, 22, 23)],
            )
            self.assertEqual(
                tasks.find_all_by_job_id(
                    connection, identifier("job", 8), **self.scope
                ).items,
                [],
            )
            for job, status in (
                (3, TaskStatus.SUCCEEDED),
                (4, TaskStatus.FAILED),
                (5, TaskStatus.CANCELLED),
                (11, TaskStatus.WAITING),
            ):
                self.assertIs(
                    tasks.find_all_by_job_id(
                        connection, identifier("job", job), **self.scope
                    )
                    .items[0]
                    .status,
                    status,
                )

    def test_task_filters_apply_before_paging_and_do_not_expand_the_job(self):
        """When a task ID belongs to another job, including it does not widen the search."""
        with transaction(self.engine) as connection:
            filters = TaskFilters(
                job_id=identifier("job", 2),
                ids=[identifier("task", n) for n in (21, 23, 61)],
                statuses=[TaskStatus.RUNNING],
            )
            first = tasks.search(
                connection, filters, **self.scope, page=PageRequest(limit=1)
            )
            rest = tasks.search(
                connection,
                filters,
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.id for row in first.items + rest.items],
                [identifier("task", 21), identifier("task", 23)],
            )
            self.assertIsNone(rest.next_cursor)

    def test_claim_reads_keep_expired_claims_but_apply_exact_lease_boundaries(self):
        """When the clock reaches a claim's expiry, it stops matching the unexpired lookup."""
        with transaction(self.engine) as connection:
            for now, found in (
                (NOW + 9, False),
                (NOW + 10, True),
                (NOW + 49, True),
                (NOW + 50, False),
            ):
                claim = task_claims.find_unexpired_by_task_id(
                    connection, identifier("task", 21), now=now, **self.scope
                )
                self.assertEqual(claim is not None, found)
            saved = task_claims.find_by_task_id(
                connection, identifier("task", 23), **self.scope
            )
            self.assertEqual(saved.token, "token-23")
            self.assertIsNone(
                task_claims.find_unexpired_by_task_id(
                    connection, saved.task_id, now=NOW + 30, **self.scope
                )
            )
            self.assertIsNone(
                task_claims.find_by_task_id(
                    connection, identifier("task", 22), **self.scope
                )
            )
            self.assertIsNone(
                task_claims.find_by_task_id(
                    connection, identifier("task", 999), **self.scope
                )
            )

    def test_claim_batches_follow_job_scope_and_enforce_the_input_limit(self):
        """When task IDs include another actor's work, its claim tokens are not returned."""
        with transaction(self.engine) as connection:
            values = [identifier("task", n) for n in (21, 21, 22, 23, 61, 81, 91, 999)]
            found = task_claims.find_by_task_ids(connection, values, **self.scope)
            self.assertEqual(
                set(found), {identifier("task", 21), identifier("task", 23)}
            )
            self.assertEqual(
                task_claims.find_by_task_ids(connection, [], **self.scope), {}
            )
            with self.assertRaises(ValueError):
                task_claims.find_by_task_ids(
                    connection, [values[0]] * 101, **self.scope
                )
            for number in (61, 81, 91):
                self.assertIsNone(
                    task_claims.find_by_task_id(
                        connection, identifier("task", number), **self.scope
                    )
                )
                self.assertIsNone(
                    task_claims.find_unexpired_by_task_id(
                        connection,
                        identifier("task", number),
                        now=NOW + 20,
                        **self.scope,
                    )
                )

    def test_replacement_claim_reads_return_the_new_token(self):
        """When a claim is replaced, later reads return its new worker and token."""
        with transaction(self.engine, write=True) as connection:
            previous = task_claims.find_by_task_id(
                connection, identifier("task", 23), **self.scope
            )
            connection.execute(
                update(tables.task_claims)
                .where(tables.task_claims.c.task_id == previous.task_id)
                .values(
                    token="replacement",
                    worker_id="worker-2",
                    claimed_at=NOW + 30,
                    heartbeat_at=NOW + 30,
                    expires_at=NOW + 60,
                    updated_at=NOW + 30,
                )
            )
            current = task_claims.find_unexpired_by_task_id(
                connection, previous.task_id, now=NOW + 30, **self.scope
            )
            self.assertEqual(
                (previous.token, current.token, current.worker_id),
                ("token-23", "replacement", "worker-2"),
            )

    def test_completion_reads_distinguish_pending_and_delivered_results(self):
        """When a result enters thread history, it stays readable but leaves the pending list."""
        with transaction(self.engine) as connection:
            pending = completion_outbox.search(
                connection, CompletionFilters(), **self.scope
            )
            self.assertEqual(
                [row.id for row in pending.items],
                [identifier("completion", 3), identifier("completion", 5)],
            )
            all_rows = completion_outbox.find_all_by_thread_id(
                connection, identifier("thread"), **self.scope
            ).items
            self.assertEqual(
                [row.id for row in all_rows],
                [identifier("completion", n) for n in (3, 4, 5)],
            )
            delivered = completion_outbox.find_by_job_id(
                connection, identifier("job", 4), **self.scope
            )
            self.assertIsNotNone(delivered.record_id)
            self.assertEqual(delivered.appended_at, NOW + 100)
            self.assertEqual(delivered.payload["status"], JobStatus.FAILED.value)
            for number in (2, 8, 10, 999):
                self.assertIsNone(
                    completion_outbox.find_by_job_id(
                        connection, identifier("job", number), **self.scope
                    )
                )
            self.assertEqual(
                completion_outbox.find_all_by_thread_id(
                    connection, identifier("thread", 2), **self.scope
                ).items,
                [],
            )

    def test_pending_completion_pages_survive_delivery_and_run_cancellation(self):
        """When a run stops, its undelivered results remain visible without restarting it."""
        filters = CompletionFilters(thread_ids=[identifier("thread")])
        with transaction(self.engine) as connection:
            first = completion_outbox.search(
                connection, filters, **self.scope, page=PageRequest(limit=1)
            )
        with transaction(self.engine, write=True) as connection:
            self.deliver(connection, 3, 1)
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == identifier("run"))
                .values(
                    status=RunStatus.CANCELLED.value,
                    finished_at=NOW + 200,
                    updated_at=NOW + 200,
                )
            )
        with transaction(self.engine) as connection:
            rest = completion_outbox.search(
                connection,
                filters,
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual([row.job_id for row in rest.items], [identifier("job", 5)])
            selected = completion_outbox.search(
                connection,
                CompletionFilters(
                    thread_ids=[identifier("thread")],
                    job_ids=[identifier("job", 3)],
                    pending_only=False,
                ),
                **self.scope,
            )
            self.assertIsNotNone(selected.items[0].record_id)
            self.assertEqual(
                connection.execute(
                    tables.runs.select().where(tables.runs.c.id == identifier("run"))
                )
                .mappings()
                .one()["status"],
                RunStatus.CANCELLED.value,
            )

    def test_cursors_reject_changed_filters_actor_and_collection(self):
        """When the caller changes a page's scope or filters, its cursor cannot be reused."""
        with transaction(self.engine) as connection:
            cases = (
                (jobs.search, JobFilters(), JobFilters(statuses=[JobStatus.SUCCEEDED])),
                (
                    tasks.search,
                    TaskFilters(job_id=identifier("job", 2)),
                    TaskFilters(job_id=identifier("job", 1)),
                ),
                (
                    completion_outbox.search,
                    CompletionFilters(),
                    CompletionFilters(pending_only=False),
                ),
            )
            for read, filters, changed in cases:
                first = read(
                    connection, filters, **self.scope, page=PageRequest(limit=1)
                )
                self.assertIsNotNone(first.next_cursor)
                with self.assertRaises(InvalidCursor):
                    read(
                        connection,
                        changed,
                        **self.scope,
                        page=PageRequest(cursor=first.next_cursor),
                    )
                with self.assertRaises(InvalidCursor):
                    read(
                        connection,
                        filters,
                        actor_staff_member_id=identifier("staff_member", 2),
                        page=PageRequest(cursor=first.next_cursor),
                    )
            first = jobs.find_all(connection, **self.scope, page=PageRequest(limit=1))
            with self.assertRaises(InvalidCursor):
                tasks.find_all_by_job_id(
                    connection,
                    identifier("job", 2),
                    **self.scope,
                    page=PageRequest(cursor=first.next_cursor),
                )

    def test_reads_leave_claims_and_delivery_unchanged_and_do_not_commit(self):
        """When a caller rolls back after reading pending changes, no outcome is saved."""
        with self.assertRaisesRegex(RuntimeError, "roll back"):
            with transaction(self.engine, write=True) as connection:
                connection.execute(
                    update(tables.jobs)
                    .where(tables.jobs.c.id == identifier("job", 2))
                    .values(phase="TEMPORARY")
                )
                self.assertEqual(
                    jobs.find_by_id(
                        connection, identifier("job", 2), **self.scope
                    ).phase,
                    "TEMPORARY",
                )
                before = task_claims.find_by_task_id(
                    connection, identifier("task", 21), **self.scope
                )
                tasks.find_all_by_job_id(connection, identifier("job", 2), **self.scope)
                completion_outbox.search(connection, CompletionFilters(), **self.scope)
                self.assertEqual(
                    task_claims.find_by_task_id(
                        connection, before.task_id, **self.scope
                    ),
                    before,
                )
                self.assertIsNone(
                    completion_outbox.find_by_job_id(
                        connection, identifier("job", 3), **self.scope
                    ).record_id
                )
                raise RuntimeError("roll back")
        with transaction(self.engine) as connection:
            self.assertEqual(
                jobs.find_by_id(connection, identifier("job", 2), **self.scope).phase,
                "START",
            )
