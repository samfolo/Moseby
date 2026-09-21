"""Exercise command replay and task ownership through real write transactions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from moseby.db import tables
from moseby.db._transaction_state import WRITE_TRANSACTION_OPTION
from moseby.db.connection import create_database_engine
from moseby.db.errors import (
    ClaimLost,
    IdempotencyConflict,
    RepositoryInvariantError,
    WriteConflict,
)
from moseby.db.models.jobs import NewJob
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.models.tasks import NewTask
from moseby.db.repositories import jobs, request_deduplication, task_claims, tasks
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction
from moseby.domain.enums import StaffRole
from moseby.runtime.enums import JobStatus, RunStatus, TaskStatus
from moseby.runtime.models.thread_records import ThreadRecordKind


class WorkMutationTests(StayDatabaseTestCase):
    def setUp(self):
        """Give each staff member a running thread and leave the work queue empty."""
        super().setUp()
        self.actor = {"actor_staff_member_id": identifier("staff_member")}
        self.key = RequestKey(
            **self.actor, operation="demo.lookup", request_id="request-1"
        )
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

    def accept_work(
        self, connection, number=1, *, key=None, request=None, thread=None, tool=False
    ):
        """Compose acceptance, job creation and its first task on the supplied connection."""
        key = key or self.key
        accepted = request_deduplication.accept(
            connection,
            key,
            request if request is not None else {"query": "rooms"},
            now=NOW,
        )
        if not accepted.created:
            return jobs.find_by_operation_and_request_id(
                connection,
                key.operation,
                key.request_id,
                actor_staff_member_id=key.actor_staff_member_id,
            )
        job = jobs.create(
            connection,
            NewJob(
                id=identifier("job", number),
                request_key=key,
                handler="demo.lookup",
                phase="START",
                input={"query": "rooms"},
                thread_id=identifier("thread", thread) if thread else None,
                run_id=identifier("run", thread) if thread else None,
                source_record_id=identifier("thread_record", 2) if tool else None,
                tool_call_id="call-1" if tool else None,
            ),
            now=NOW,
        )
        tasks.create(
            connection,
            NewTask(
                id=identifier("task", number),
                job_id=job.id,
                step_key="lookup",
                handler="demo.lookup",
                input={"query": "rooms"},
                available_at=NOW,
            ),
            actor_staff_member_id=key.actor_staff_member_id,
            now=NOW,
        )
        request_deduplication.save_response(
            connection, key, {"job_id": job.id}, now=NOW
        )
        return job

    def start(self, connection, *, thread=None):
        """Accept the work and claim its first attempt for a known time interval."""
        self.accept_work(connection, thread=thread)
        return task_claims.claim(
            connection,
            identifier("task"),
            **self.actor,
            worker_id="worker-1",
            now=NOW + 1,
            expires_at=NOW + 100,
        )

    def test_replayed_command_returns_the_original_job_without_more_tasks(self):
        """When a client repeats a command, its new candidate IDs do not create more work."""
        with transaction(self.engine, write=True) as connection:
            payload = {"query": "rooms", "options": {"b": 2, "a": 1}}
            original = self.accept_work(connection, request=payload)
            self.assertEqual(payload, {"query": "rooms", "options": {"b": 2, "a": 1}})
            self.assertEqual(list(payload), ["query", "options"])
            self.assertEqual(list(payload["options"]), ["b", "a"])
            repeated = self.accept_work(
                connection, 2, request={"options": {"b": 2, "a": 1}, "query": "rooms"}
            )
            self.assertEqual(original.id, repeated.id)
            self.assertIsNone(
                jobs.find_by_id(connection, identifier("job", 2), **self.actor)
            )
            self.assertEqual(
                len(
                    tasks.find_all_by_job_id(
                        connection, original.id, **self.actor
                    ).items
                ),
                1,
            )
            with self.assertRaises(IdempotencyConflict):
                self.accept_work(connection, 3, request={"query": "venues"})

    def test_response_receipt_distinguishes_empty_from_unsaved_and_rejects_replacement(
        self,
    ):
        """When an empty response is saved, retries return it without replacing its timestamp."""
        with transaction(self.engine, write=True) as connection:
            accepted = request_deduplication.accept(connection, self.key, {}, now=NOW)
            self.assertTrue(accepted.created)
            self.assertIsNone(accepted.request.response)
            saved = request_deduplication.save_response(
                connection, self.key, {}, now=NOW + 1
            )
            repeated = request_deduplication.save_response(
                connection, self.key, {}, now=NOW + 2
            )
            self.assertEqual(saved, repeated)
            with self.assertRaises(IdempotencyConflict):
                request_deduplication.save_response(
                    connection, self.key, {"changed": True}, now=NOW + 2
                )
            with self.assertRaises(WriteConflict):
                request_deduplication.save_response(
                    connection,
                    self.key.model_copy(update={"request_id": "missing"}),
                    {},
                    now=NOW,
                )

    def test_request_comparison_preserves_types_and_rejects_nonfinite_numbers(self):
        """When a retry changes a boolean to a number, it is different input despite Python equality."""
        with transaction(self.engine, write=True) as connection:
            request_deduplication.accept(connection, self.key, {"value": True}, now=NOW)
            with self.assertRaises(IdempotencyConflict):
                request_deduplication.accept(
                    connection, self.key, {"value": 1}, now=NOW
                )
            with self.assertRaises(ValueError):
                request_deduplication.accept(
                    connection,
                    self.key.model_copy(update={"request_id": "nan"}),
                    {"value": float("nan")},
                    now=NOW,
                )
            self.assertIsNone(
                request_deduplication.find_by_operation_and_request_id(
                    connection, self.key.operation, "nan", **self.actor
                )
            )

    def test_command_keys_allow_distinct_actors_and_operations(self):
        """When actor or operation changes, the same request-ID string names a separate command."""
        with transaction(self.engine, write=True) as connection:
            for number, key in enumerate(
                (
                    self.key,
                    self.key.model_copy(update={"operation": "demo.other"}),
                    self.key.model_copy(
                        update={"actor_staff_member_id": identifier("staff_member", 2)}
                    ),
                ),
                1,
            ):
                self.assertEqual(
                    self.accept_work(connection, number, key=key).id,
                    identifier("job", number),
                )

    def test_job_and_task_creation_failures_roll_back_the_accepted_command(self):
        """When initial work cannot be created, the ledger must not retain a half-accepted command."""
        with self.assertRaises(WriteConflict):
            with transaction(self.engine, write=True) as connection:
                self.accept_work(connection, thread=2)
        with self.engine.connect() as connection:
            self.assertIsNone(
                request_deduplication.find_by_operation_and_request_id(
                    connection, self.key.operation, self.key.request_id, **self.actor
                )
            )
        with self.assertRaises(IntegrityError):
            with transaction(self.engine, write=True) as connection:
                job = self.accept_work(connection)
                tasks.create(
                    connection,
                    NewTask(
                        id=identifier("task", 2),
                        job_id=job.id,
                        step_key="lookup",
                        handler="demo.lookup",
                        input={},
                        available_at=NOW,
                    ),
                    **self.actor,
                    now=NOW,
                )
        with self.engine.connect() as connection:
            self.assertIsNone(
                jobs.find_by_id(connection, identifier("job"), **self.actor)
            )
            self.assertIsNone(
                request_deduplication.find_by_operation_and_request_id(
                    connection, self.key.operation, self.key.request_id, **self.actor
                )
            )

    def test_writes_require_a_transaction_that_actually_started_as_a_writer(self):
        """When a connection began as a reader, changing its option later does not authorize writes."""
        with self.engine.connect() as connection:
            with self.assertRaises(RuntimeError):
                request_deduplication.accept(connection, self.key, {}, now=NOW)
            with connection.begin():
                connection.execution_options(**{WRITE_TRANSACTION_OPTION: True})
                with self.assertRaises(RuntimeError):
                    request_deduplication.accept(connection, self.key, {}, now=NOW)
        with transaction(self.engine, write=True) as connection:
            request_deduplication.accept(connection, self.key, {}, now=NOW)

    def test_claim_starts_one_attempt_and_a_second_worker_cannot_take_it(self):
        """When a task has a live owner, another worker gets no claim or extra attempt."""
        with transaction(self.engine, write=True) as connection:
            claim = self.start(connection)
            self.assertIsNotNone(claim)
            self.assertEqual(claim.claimed_at, NOW + 1)
            self.assertEqual(
                jobs.find_by_id(connection, identifier("job"), **self.actor).status,
                JobStatus.RUNNING,
            )
            task = tasks.find_by_id(connection, identifier("task"), **self.actor)
            self.assertEqual(
                (task.status, task.attempt_count, task.started_at),
                (TaskStatus.RUNNING, 1, NOW + 1),
            )
            self.assertIsNone(
                task_claims.claim(
                    connection,
                    task.id,
                    **self.actor,
                    worker_id="worker-2",
                    now=NOW + 2,
                    expires_at=NOW + 200,
                )
            )
            self.assertEqual(
                tasks.find_by_id(connection, task.id, **self.actor).attempt_count, 1
            )

    def test_expiry_reclaim_replaces_the_token_and_rejects_old_worker_writes(self):
        """At the expiry boundary, a new worker can claim the task and the old token loses every write."""
        with transaction(self.engine, write=True) as connection:
            old = self.start(connection)
            self.assertIsNone(
                task_claims.renew(
                    connection,
                    old.task_id,
                    old.token,
                    **self.actor,
                    now=NOW + 100,
                    expires_at=NOW + 200,
                )
            )
            replacement = task_claims.claim(
                connection,
                old.task_id,
                **self.actor,
                worker_id="worker-2",
                now=NOW + 100,
                expires_at=NOW + 200,
            )
            self.assertNotEqual(replacement.token, old.token)
            self.assertEqual(replacement.created_at, old.created_at)
            self.assertIsNone(
                task_claims.renew(
                    connection,
                    old.task_id,
                    old.token,
                    **self.actor,
                    now=NOW + 101,
                    expires_at=NOW + 300,
                )
            )
            for method in (tasks.succeed, tasks.fail):
                with self.assertRaises(ClaimLost):
                    method(
                        connection,
                        old.task_id,
                        old.token,
                        {},
                        **self.actor,
                        now=NOW + 101,
                    )
            with self.assertRaises(ClaimLost):
                tasks.retry(
                    connection,
                    old.task_id,
                    old.token,
                    {},
                    **self.actor,
                    now=NOW + 101,
                    available_at=NOW + 102,
                )
            task = tasks.succeed(
                connection,
                replacement.task_id,
                replacement.token,
                {"found": 2},
                **self.actor,
                now=NOW + 102,
            )
            self.assertEqual(task.attempt_count, 2)
            self.assertEqual(task.result, {"found": 2})
            self.assertEqual(task.started_at, NOW + 1)

    def test_renewal_only_extends_a_live_lease_with_forward_time(self):
        """When a heartbeat renews a lease, it cannot shorten the deadline or move time backwards."""
        with transaction(self.engine, write=True) as connection:
            claim = self.start(connection)
            renewed = task_claims.renew(
                connection,
                claim.task_id,
                claim.token,
                **self.actor,
                now=NOW + 10,
                expires_at=NOW + 200,
            )
            self.assertEqual(
                (renewed.heartbeat_at, renewed.expires_at), (NOW + 10, NOW + 200)
            )
            for now, expires_at in ((NOW + 9, NOW + 300), (NOW + 11, NOW + 150)):
                self.assertIsNone(
                    task_claims.renew(
                        connection,
                        claim.task_id,
                        claim.token,
                        **self.actor,
                        now=now,
                        expires_at=expires_at,
                    )
                )
            with self.assertRaises(ValueError):
                task_claims.renew(
                    connection,
                    claim.task_id,
                    claim.token,
                    **self.actor,
                    now=NOW + 10,
                    expires_at=NOW + 10,
                )

    def test_retry_releases_the_claim_and_waits_before_counting_the_next_attempt(self):
        """When an attempt is deferred, its task keeps the error and input until a later claim."""
        with transaction(self.engine, write=True) as connection:
            claim = self.start(connection)
            retry = tasks.retry(
                connection,
                claim.task_id,
                claim.token,
                {"message": "Temporary failure"},
                **self.actor,
                now=NOW + 2,
                available_at=NOW + 20,
            )
            self.assertEqual((retry.status, retry.attempt_count), (TaskStatus.READY, 1))
            self.assertIsNone(
                task_claims.find_by_task_id(connection, retry.id, **self.actor)
            )
            self.assertIsNone(
                task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id="worker-2",
                    now=NOW + 19,
                    expires_at=NOW + 100,
                )
            )
            next_claim = task_claims.claim_next(
                connection,
                **self.actor,
                worker_id="worker-2",
                now=NOW + 20,
                expires_at=NOW + 100,
            )
            self.assertNotEqual(next_claim.token, claim.token)
            result = tasks.succeed(
                connection, retry.id, next_claim.token, {}, **self.actor, now=NOW + 21
            )
            self.assertEqual(
                (result.attempt_count, result.input, result.result, result.error),
                (2, {"query": "rooms"}, {}, None),
            )

    def test_terminal_tasks_keep_their_outcome_and_cannot_renew_or_reclaim(self):
        """When a task fails permanently, later attempts cannot overwrite its saved error."""
        with transaction(self.engine, write=True) as connection:
            claim = self.start(connection)
            failed = tasks.fail(
                connection,
                claim.task_id,
                claim.token,
                {"message": "No access"},
                **self.actor,
                now=NOW + 2,
            )
            self.assertEqual(failed.status, TaskStatus.FAILED)
            self.assertEqual(failed.finished_at, NOW + 2)
            self.assertIsNone(failed.result)
            self.assertIsNone(
                task_claims.renew(
                    connection,
                    claim.task_id,
                    claim.token,
                    **self.actor,
                    now=NOW + 3,
                    expires_at=NOW + 200,
                )
            )
            self.assertIsNone(
                task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id="worker-2",
                    now=NOW + 101,
                    expires_at=NOW + 200,
                )
            )
            with self.assertRaises(ClaimLost):
                tasks.succeed(
                    connection,
                    claim.task_id,
                    claim.token,
                    {},
                    **self.actor,
                    now=NOW + 3,
                )

    def test_sleeping_and_stopped_runs_block_new_claims_but_keep_late_evidence(self):
        """When a run stops during external work, its live task can save a result without waking it."""
        with transaction(self.engine, write=True) as connection:
            self.accept_work(connection, thread=1)
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == identifier("run"))
                .values(status=RunStatus.WAITING.value, wake_at=NOW + 100)
            )
            self.assertIsNone(
                task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id="worker",
                    now=NOW + 1,
                    expires_at=NOW + 50,
                )
            )
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == identifier("run"))
                .values(
                    status=RunStatus.RUNNING.value,
                    wake_at=None,
                    cancel_requested_at=NOW,
                    cancel_requested_by_staff_member_id=identifier("staff_member"),
                )
            )
            self.assertIsNone(
                task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id="worker",
                    now=NOW + 1,
                    expires_at=NOW + 50,
                )
            )
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == identifier("run"))
                .values(
                    cancel_requested_at=None, cancel_requested_by_staff_member_id=None
                )
            )
            claim = task_claims.claim_next(
                connection,
                **self.actor,
                worker_id="worker",
                now=NOW + 1,
                expires_at=NOW + 50,
            )
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == identifier("run"))
                .values(status=RunStatus.CANCELLED.value, finished_at=NOW + 2)
            )
            tasks.succeed(
                connection,
                claim.task_id,
                claim.token,
                {"late": True},
                **self.actor,
                now=NOW + 3,
            )
            self.assertEqual(
                connection.scalar(
                    select(tables.runs.c.status).where(
                        tables.runs.c.id == identifier("run")
                    )
                ),
                RunStatus.CANCELLED,
            )
            self.assertEqual(
                jobs.find_by_id(connection, identifier("job"), **self.actor).status,
                JobStatus.RUNNING,
            )

    def test_queue_selection_skips_future_and_other_actor_work(self):
        """When tasks are not yet due or belong to another actor, they cannot block eligible work."""
        with transaction(self.engine, write=True) as connection:
            self.accept_work(connection)
            self.accept_work(
                connection,
                2,
                key=self.key.model_copy(
                    update={"actor_staff_member_id": identifier("staff_member", 2)}
                ),
            )
            tasks.create(
                connection,
                NewTask(
                    id=identifier("task", 3),
                    job_id=identifier("job"),
                    step_key="second",
                    handler="demo.lookup",
                    input={},
                    available_at=NOW + 10,
                ),
                **self.actor,
                now=NOW,
            )
            first = task_claims.claim_next(
                connection,
                **self.actor,
                worker_id="worker",
                now=NOW + 1,
                expires_at=NOW + 100,
            )
            self.assertEqual(first.task_id, identifier("task"))
            self.assertIsNone(
                task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id="worker",
                    now=NOW + 2,
                    expires_at=NOW + 100,
                )
            )
            second = task_claims.claim_next(
                connection,
                **self.actor,
                worker_id="worker",
                now=NOW + 10,
                expires_at=NOW + 100,
            )
            self.assertEqual(second.task_id, identifier("task", 3))
            self.assertIsNone(
                task_claims.claim(
                    connection,
                    identifier("task", 2),
                    **self.actor,
                    worker_id="worker",
                    now=NOW + 10,
                    expires_at=NOW + 100,
                )
            )

    def test_guard_rolls_back_related_writes_when_an_outcome_cannot_be_saved(self):
        """When a guarded operation fails, catching its error does not leave its earlier writes behind."""
        with transaction(self.engine, write=True) as connection:
            claim = self.start(connection)
            with self.assertRaises(ValueError):
                with task_claims.guard(
                    connection, claim.task_id, claim.token, **self.actor, now=NOW + 2
                ):
                    connection.execute(
                        update(tables.jobs)
                        .where(tables.jobs.c.id == identifier("job"))
                        .values(phase="ADVANCED")
                    )
                    tasks.succeed(
                        connection,
                        claim.task_id,
                        claim.token,
                        {"bad": float("nan")},
                        **self.actor,
                        now=NOW + 2,
                    )
            self.assertEqual(
                jobs.find_by_id(connection, identifier("job"), **self.actor).phase,
                "START",
            )
            self.assertEqual(
                tasks.find_by_id(connection, claim.task_id, **self.actor).status,
                TaskStatus.RUNNING,
            )
            with self.assertRaises(ClaimLost):
                with task_claims.guard(
                    connection, claim.task_id, "wrong-token", **self.actor, now=NOW + 2
                ):
                    self.fail("A stale worker must not enter the protected block")

    def test_failed_claim_insert_rolls_back_the_attempt_and_parent_change(self):
        """When a token cannot be inserted, catching the error does not strand a running task."""
        with transaction(self.engine, write=True) as connection:
            first = self.start(connection)
            self.accept_work(
                connection,
                2,
                key=self.key.model_copy(update={"request_id": "request-2"}),
            )
            with patch(
                "moseby.db.repositories.task_claims.secrets.token_urlsafe",
                return_value=first.token,
            ):
                with self.assertRaises(IntegrityError):
                    task_claims.claim(
                        connection,
                        identifier("task", 2),
                        **self.actor,
                        worker_id="worker-2",
                        now=NOW + 2,
                        expires_at=NOW + 100,
                    )
            task = tasks.find_by_id(connection, identifier("task", 2), **self.actor)
            self.assertEqual((task.status, task.attempt_count), (TaskStatus.READY, 0))
            self.assertEqual(
                jobs.find_by_id(connection, identifier("job", 2), **self.actor).status,
                JobStatus.QUEUED,
            )

    def test_two_connections_accept_one_command_and_claim_one_attempt(self):
        """When two workers race, both see one accepted job and only one gets its claim."""
        barrier = Barrier(2)

        def submit(number):
            barrier.wait(timeout=5)
            with transaction(self.engine, write=True) as connection:
                return self.accept_work(connection, number).id

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(submit, n) for n in (1, 2)]
            job_ids = [future.result(timeout=10) for future in futures]
        self.assertEqual(job_ids[0], job_ids[1])
        barrier = Barrier(2)

        def acquire(number):
            barrier.wait(timeout=5)
            with transaction(self.engine, write=True) as connection:
                return task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id=f"worker-{number}",
                    now=NOW + 1,
                    expires_at=NOW + 100,
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(acquire, n) for n in (1, 2)]
            claims = [future.result(timeout=10) for future in futures]
        winner = [claim for claim in claims if claim is not None]
        self.assertEqual(len(winner), 1)
        with self.engine.connect() as connection:
            self.assertEqual(
                tasks.find_by_id(
                    connection, winner[0].task_id, **self.actor
                ).attempt_count,
                1,
            )

    def test_waiting_run_allows_its_tool_job_without_starting_agent_work(self):
        """When the agent waits for a tool, that tool can start and save its result without waking it."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "thread_records",
                id=identifier("thread_record"),
                thread_id=identifier("thread"),
                sequence=1,
                kind=ThreadRecordKind.THREAD_CREATED.value,
                format_version=1,
                payload_json="{}",
            )
            self.insert(
                connection,
                "thread_records",
                id=identifier("thread_record", 2),
                thread_id=identifier("thread"),
                run_id=identifier("run"),
                sequence=2,
                kind=ThreadRecordKind.ASSISTANT_MESSAGE.value,
                format_version=1,
                payload_json='{"tool_calls":[{"id":"call-1","name":"demo.lookup","arguments":{}}]}',
            )
            self.accept_work(connection, thread=1)
            self.accept_work(
                connection,
                2,
                key=self.key.model_copy(update={"request_id": "tool-request"}),
                thread=1,
                tool=True,
            )
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == identifier("run"))
                .values(status=RunStatus.WAITING.value, wake_at=NOW + 100)
            )
            claim = task_claims.claim_next(
                connection,
                **self.actor,
                worker_id="worker",
                now=NOW + 1,
                expires_at=NOW + 50,
            )
            self.assertEqual(claim.task_id, identifier("task", 2))
            self.assertIsNone(
                task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id="worker",
                    now=NOW + 1,
                    expires_at=NOW + 50,
                )
            )
            tasks.succeed(
                connection, claim.task_id, claim.token, {}, **self.actor, now=NOW + 2
            )
            self.assertEqual(
                connection.scalar(
                    select(tables.runs.c.status).where(
                        tables.runs.c.id == identifier("run")
                    )
                ),
                RunStatus.WAITING,
            )

    def test_claim_token_does_not_bypass_actor_or_finished_job_checks(self):
        """When another actor has the token, or the parent job has ended, it still cannot save an outcome."""
        with transaction(self.engine, write=True) as connection:
            claim = self.start(connection)
            with self.assertRaises(ClaimLost):
                tasks.succeed(
                    connection,
                    claim.task_id,
                    claim.token,
                    {},
                    actor_staff_member_id=identifier("staff_member", 2),
                    now=NOW + 2,
                )
            self.assertIsNone(
                task_claims.renew(
                    connection,
                    claim.task_id,
                    claim.token,
                    actor_staff_member_id=identifier("staff_member", 2),
                    now=NOW + 2,
                    expires_at=NOW + 200,
                )
            )
            connection.execute(
                update(tables.jobs)
                .where(tables.jobs.c.id == identifier("job"))
                .values(
                    status=JobStatus.CANCELLED.value,
                    finished_at=NOW + 2,
                    updated_at=NOW + 2,
                )
            )
            with self.assertRaises(ClaimLost):
                tasks.succeed(
                    connection,
                    claim.task_id,
                    claim.token,
                    {},
                    **self.actor,
                    now=NOW + 3,
                )
            self.assertIsNone(
                task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id="worker-2",
                    now=NOW + 101,
                    expires_at=NOW + 200,
                )
            )
            with self.assertRaises(WriteConflict):
                tasks.create(
                    connection,
                    NewTask(
                        id=identifier("task", 2),
                        job_id=identifier("job"),
                        step_key="second",
                        handler="demo.lookup",
                        input={},
                        available_at=NOW + 3,
                    ),
                    **self.actor,
                    now=NOW + 3,
                )

    def test_missing_saved_command_raises_an_explicit_error_and_rolls_back(self):
        """When an accepted command cannot be read back, the operation fails and its insert rolls back."""
        with self.assertRaises(RepositoryInvariantError):
            with transaction(self.engine, write=True) as connection:
                with patch(
                    "moseby.db.repositories.request_deduplication.find_by_operation_and_request_id",
                    return_value=None,
                ):
                    request_deduplication.accept(connection, self.key, {}, now=NOW)
        with self.engine.connect() as connection:
            self.assertIsNone(
                request_deduplication.find_by_operation_and_request_id(
                    connection, self.key.operation, self.key.request_id, **self.actor
                )
            )

    def test_worker_that_stops_heartbeating_leaves_a_recoverable_task_on_disk(self):
        """When a worker disappears after claiming, a new connection recovers its task after expiry."""
        with transaction(self.engine, write=True) as connection:
            abandoned = self.start(connection)
        restarted = create_database_engine(self.engine.url)
        self.addCleanup(restarted.dispose)
        with transaction(restarted, write=True) as connection:
            self.assertIsNone(
                task_claims.claim_next(
                    connection,
                    **self.actor,
                    worker_id="replacement",
                    now=NOW + 99,
                    expires_at=NOW + 200,
                )
            )
        with transaction(restarted, write=True) as connection:
            recovered = task_claims.claim_next(
                connection,
                **self.actor,
                worker_id="replacement",
                now=NOW + 100,
                expires_at=NOW + 200,
            )
            self.assertEqual(recovered.task_id, abandoned.task_id)
            self.assertNotEqual(recovered.token, abandoned.token)
            saved = tasks.succeed(
                connection,
                recovered.task_id,
                recovered.token,
                {"recovered": True},
                **self.actor,
                now=NOW + 101,
            )
            self.assertEqual(saved.attempt_count, 2)
            with self.assertRaises(ClaimLost):
                tasks.succeed(
                    connection,
                    abandoned.task_id,
                    abandoned.token,
                    {"late": True},
                    **self.actor,
                    now=NOW + 102,
                )
