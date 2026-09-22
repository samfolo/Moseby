"""Check runtime history and delivery rules with real SQLite transactions."""

import tempfile
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from moseby.db.connection import create_database_engine
from moseby.db.transaction import transaction


def identifier(prefix, number=1):
    return f"{prefix}_{number:026d}"


class RuntimeMigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_database_engine(f"sqlite:///{directory.name}/test.db")
        self.addCleanup(self.engine.dispose)
        self.config = Config(str(Path(__file__).resolve().parents[3] / "alembic.ini"))
        self.migrate("head")
        self.metadata = sa.MetaData()
        with self.engine.connect() as connection:
            self.metadata.reflect(connection)
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection, "hotels", id=identifier("hotel"), created_at=0, name="Hotel"
            )
            self.insert(
                connection,
                "staff_members",
                id=identifier("staff_member"),
                created_at=0,
                hotel_id=identifier("hotel"),
                staff_code="ONE",
                first_name="Sam",
                last_name="Staff",
                role="STAFF_ROLE_CONCIERGE",
            )
            for number in (1, 2):
                self.insert(
                    connection,
                    "threads",
                    id=identifier("thread", number),
                    created_at=0,
                    creator_staff_member_id=identifier("staff_member"),
                    permissions_json='["moseby:read"]',
                    projection_sequence=0,
                    projection_format_version=1,
                    projection_json="{}",
                )
                self.insert(
                    connection,
                    "runs",
                    id=identifier("run", number),
                    created_at=0,
                    thread_id=identifier("thread", number),
                    status="RUN_STATUS_RUNNING",
                    recovery_attempts=0,
                )
                self.record(
                    connection,
                    number,
                    thread=number,
                    sequence=1,
                    kind="THREAD_RECORD_KIND_THREAD_CREATED",
                    run_id=None,
                )

    def migrate(self, revision, *, downgrade=False):
        with transaction(self.engine, write=True) as connection:
            self.config.attributes["connection"] = connection
            try:
                (command.downgrade if downgrade else command.upgrade)(
                    self.config, revision
                )
            finally:
                self.config.attributes.pop("connection")

    def insert(self, connection, table, **values):
        target = self.metadata.tables[table]
        if "created_at" in target.c:
            values.setdefault("created_at", 0)
        if "updated_at" in target.c:
            values.setdefault("updated_at", values["created_at"])
        connection.execute(target.insert().values(**values))

    def update(self, connection, table, identity, **values):
        target = self.metadata.tables[table]
        connection.execute(
            target.update().where(target.c.id == identity).values(**values)
        )

    def invalid(self, connection, action):
        with self.assertRaises(IntegrityError), connection.begin_nested():
            action()

    def record(
        self,
        connection,
        number,
        *,
        thread=1,
        sequence=2,
        kind="THREAD_RECORD_KIND_USER_MESSAGE",
        **changes,
    ):
        values = dict(
            id=identifier("thread_record", number),
            created_at=1,
            thread_id=identifier("thread", thread),
            sequence=sequence,
            kind=kind,
            format_version=1,
            run_id=identifier("run", thread),
            payload_json="{}",
        )
        self.insert(connection, "thread_records", **(values | changes))

    def incoming(self, connection, number=1, **changes):
        values = dict(
            id=identifier("incoming_thread_record", number),
            created_at=1,
            thread_id=identifier("thread"),
            sequence=number,
            kind="INCOMING_THREAD_RECORD_KIND_USER_MESSAGE",
            delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE",
            actor_staff_member_id=identifier("staff_member"),
            format_version=1,
            payload_json='{"text":"Avoid morning activities"}',
        )
        self.insert(connection, "incoming_thread_records", **(values | changes))

    def job(self, connection, number=1, **changes):
        self.insert(
            connection,
            "request_deduplication",
            actor_staff_member_id=identifier("staff_member"),
            operation="demo",
            request_id=str(number),
            created_at=1,
            request_json="{}",
        )
        values = dict(
            id=identifier("job", number),
            created_at=1,
            actor_staff_member_id=identifier("staff_member"),
            operation="demo",
            request_id=str(number),
            thread_id=identifier("thread"),
            run_id=identifier("run"),
            handler="demo",
            phase="START",
            format_version=1,
            input_json="{}",
            status="JOB_STATUS_QUEUED",
        )
        self.insert(connection, "jobs", **(values | changes))

    def inference(self, connection, number=1):
        self.insert(
            connection,
            "inference_requests",
            id=identifier("inference_request", number),
            created_at=2,
            thread_id=identifier("thread"),
            run_id=identifier("run"),
            purpose="INFERENCE_REQUEST_PURPOSE_MAIN",
            provider="demo",
            model="demo",
            format_version=1,
            request_json="{}",
            status="INFERENCE_STATUS_PREPARED",
        )

    def test_upgrade_and_populated_downgrade_preserve_domain(self):
        """Runtime migrations can be removed and reapplied, preserving domain rows."""
        with transaction(self.engine, write=True) as connection:
            self.record(connection, 3, kind="THREAD_RECORD_KIND_ASSISTANT_MESSAGE")
            self.record(
                connection,
                4,
                sequence=3,
                kind="THREAD_RECORD_KIND_TOOL_RESULT",
                source_record_id=identifier("thread_record", 3),
                tool_call_id="call-1",
            )
            self.job(connection)
            inspector = sa.inspect(connection)
            # SQLite identifies FTS virtual and storage tables separately.
            ordinary_tables = {
                row["name"]
                for row in connection.exec_driver_sql("PRAGMA table_list").mappings()
                if row["type"] == "table" and row["schema"] == "main"
            }
            tables = [
                name for name in inspector.get_table_names() if name in ordinary_tables
            ]
            self.assertEqual(len(tables), 31)
            for name in tables:
                if name != "alembic_version":
                    self.assertTrue(inspector.get_table_options(name)["sqlite_strict"])
                    self.assertTrue(inspector.get_pk_constraint(name)["name"])
            self.assertEqual(
                connection.exec_driver_sql("PRAGMA foreign_key_check").all(), []
            )
        self.migrate("0001_domain", downgrade=True)
        with self.engine.connect() as connection:
            self.assertEqual(len(sa.inspect(connection).get_table_names()), 20)
            self.assertEqual(
                connection.exec_driver_sql(
                    "SELECT count(*) FROM staff_members"
                ).scalar_one(),
                1,
            )
        self.migrate("head")
        self.migrate("base", downgrade=True)
        self.migrate("head")

    def test_history_is_ordered_immutable_and_stays_in_its_thread(self):
        """Thread history rejects gaps, cross-thread links and changes to saved rows."""
        with transaction(self.engine, write=True) as connection:
            self.invalid(connection, lambda: self.record(connection, 3, sequence=4))
            self.invalid(
                connection,
                lambda: self.record(connection, 3, run_id=identifier("run", 2)),
            )
            self.invalid(
                connection,
                lambda: self.record(
                    connection, 3, source_record_id=identifier("thread_record", 2)
                ),
            )
            self.invalid(
                connection, lambda: self.record(connection, 3, payload_json="[]")
            )
            self.record(connection, 3)
            self.invalid(
                connection,
                lambda: self.update(
                    connection,
                    "thread_records",
                    identifier("thread_record", 3),
                    payload_json='{"text":"changed"}',
                ),
            )
            self.invalid(
                connection,
                lambda: connection.execute(
                    self.metadata.tables["thread_records"].delete()
                ),
            )

    def test_received_appended_and_included_are_distinct(self):
        """Multiple inference requests can reuse one message without copying it."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "incoming_thread_records",
                id=identifier("incoming_thread_record"),
                created_at=0,
                thread_id=identifier("thread"),
                sequence=1,
                kind="INCOMING_THREAD_RECORD_KIND_USER_MESSAGE",
                delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE",
                actor_staff_member_id=identifier("staff_member"),
                request_id="request-1",
                format_version=1,
                payload_json='{"text":"Hello"}',
            )
            self.record(connection, 3, payload_json='{"text":"Hello"}')
            self.update(
                connection,
                "incoming_thread_records",
                identifier("incoming_thread_record"),
                record_id=identifier("thread_record", 3),
                appended_at=1,
            )
            self.invalid(
                connection,
                lambda: self.update(
                    connection,
                    "incoming_thread_records",
                    identifier("incoming_thread_record"),
                    record_id=None,
                    appended_at=None,
                ),
            )
            for number in (1, 2):
                self.inference(connection, number)
                self.insert(
                    connection,
                    "inference_request_records",
                    inference_request_id=identifier("inference_request", number),
                    record_id=identifier("thread_record", 3),
                    thread_id=identifier("thread"),
                    sequence=1,
                )
            self.update(
                connection,
                "inference_requests",
                identifier("inference_request"),
                status="INFERENCE_STATUS_IN_FLIGHT",
                started_at=3,
            )
            self.invalid(
                connection,
                lambda: self.update(
                    connection,
                    "inference_requests",
                    identifier("inference_request"),
                    status="INFERENCE_STATUS_PREPARED",
                    started_at=None,
                ),
            )
            self.invalid(
                connection,
                lambda: self.insert(
                    connection,
                    "inference_request_records",
                    inference_request_id=identifier("inference_request"),
                    record_id=identifier("thread_record"),
                    thread_id=identifier("thread"),
                    sequence=2,
                ),
            )
            self.assertEqual(
                connection.exec_driver_sql(
                    "SELECT count(*) FROM thread_records WHERE kind = 'THREAD_RECORD_KIND_USER_MESSAGE'"
                ).scalar_one(),
                1,
            )
            self.assertEqual(
                connection.exec_driver_sql(
                    "SELECT count(*) FROM inference_request_records"
                ).scalar_one(),
                2,
            )

    def test_wait_keeps_run_slot_and_late_result_does_not_revive_cancelled_run(self):
        """Waiting keeps the run slot; late results cannot restart a cancelled run."""
        with transaction(self.engine, write=True) as connection:
            self.update(
                connection,
                "runs",
                identifier("run"),
                status="RUN_STATUS_WAITING",
                wake_at=20,
            )

            def next_run():
                self.insert(
                    connection,
                    "runs",
                    id=identifier("run", 3),
                    created_at=2,
                    thread_id=identifier("thread"),
                    status="RUN_STATUS_QUEUED",
                    recovery_attempts=0,
                )

            self.invalid(connection, next_run)
            self.record(connection, 3, kind="THREAD_RECORD_KIND_ASSISTANT_MESSAGE")
            self.update(
                connection,
                "runs",
                identifier("run"),
                status="RUN_STATUS_CANCELLED",
                wake_at=None,
                finished_at=3,
            )
            next_run()
            self.record(
                connection,
                4,
                sequence=3,
                kind="THREAD_RECORD_KIND_TOOL_RESULT",
                source_record_id=identifier("thread_record", 3),
                tool_call_id="call-1",
            )
            self.invalid(
                connection,
                lambda: self.record(
                    connection,
                    5,
                    sequence=4,
                    kind="THREAD_RECORD_KIND_TOOL_RESULT",
                    source_record_id=identifier("thread_record", 3),
                    tool_call_id="call-1",
                ),
            )
            self.invalid(
                connection,
                lambda: self.update(
                    connection,
                    "runs",
                    identifier("run"),
                    status="RUN_STATUS_RUNNING",
                    finished_at=None,
                ),
            )

    def test_incoming_delivery_mode_can_change_until_appended(self):
        """Pending input can become a steer; delivery settings freeze on append."""
        with transaction(self.engine, write=True) as connection:
            identity = identifier("incoming_thread_record")
            self.insert(
                connection,
                "incoming_thread_records",
                id=identity,
                created_at=1,
                thread_id=identifier("thread"),
                sequence=1,
                kind="INCOMING_THREAD_RECORD_KIND_USER_MESSAGE",
                delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE",
                actor_staff_member_id=identifier("staff_member"),
                request_id="message-1",
                format_version=1,
                payload_json='{"text":"Avoid morning activities"}',
            )
            # Assertive input targets a run, and it must be in the same thread.
            for target in (None, identifier("run", 2)):
                self.invalid(
                    connection,
                    lambda target=target: self.update(
                        connection,
                        "incoming_thread_records",
                        identity,
                        delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE",
                        target_run_id=target,
                        updated_at=2,
                    ),
                )
            self.update(
                connection,
                "incoming_thread_records",
                identity,
                delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE",
                target_run_id=identifier("run"),
                updated_at=2,
            )
            self.assertEqual(
                connection.exec_driver_sql("SELECT DISTINCT status FROM runs").all(),
                [("RUN_STATUS_RUNNING",)],
            )
            self.record(connection, 3)
            self.update(
                connection,
                "incoming_thread_records",
                identity,
                record_id=identifier("thread_record", 3),
                appended_at=3,
                updated_at=3,
            )
            self.invalid(
                connection,
                lambda: self.update(
                    connection,
                    "incoming_thread_records",
                    identity,
                    delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE",
                    target_run_id=None,
                    updated_at=4,
                ),
            )

    def test_pending_input_cancellation_is_terminal_and_retained(self):
        """Withdrawn input retains a permanent receipt and cannot be changed."""
        identity = identifier("incoming_thread_record")
        cancellation = dict(
            cancelled_at=2,
            cancelled_by_staff_member_id=identifier("staff_member"),
            updated_at=2,
        )
        with transaction(self.engine, write=True) as connection:
            self.incoming(
                connection,
                delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE",
                target_run_id=identifier("run"),
            )
            for changes in (
                {"cancelled_at": None},
                {"cancelled_by_staff_member_id": None},
                {"cancelled_by_staff_member_id": identifier("staff_member", 2)},
                {"cancelled_at": 0},
                {"updated_at": 1},
            ):
                self.invalid(
                    connection,
                    lambda changes=changes: self.update(
                        connection,
                        "incoming_thread_records",
                        identity,
                        **(cancellation | changes),
                    ),
                )
            self.update(connection, "incoming_thread_records", identity, **cancellation)
            for changes in (
                {"cancelled_at": None, "cancelled_by_staff_member_id": None},
                {
                    "delivery_mode": "INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE",
                    "target_run_id": None,
                },
                {"updated_at": 3},
            ):
                self.invalid(
                    connection,
                    lambda changes=changes: self.update(
                        connection, "incoming_thread_records", identity, **changes
                    ),
                )
            target = self.metadata.tables["incoming_thread_records"]
            self.invalid(connection, lambda: connection.execute(target.delete()))

    def test_cancellation_and_append_cannot_both_win(self):
        """Delivery and cancellation cannot both succeed or leave partial history."""
        with transaction(self.engine, write=True) as connection:
            self.incoming(connection)
            self.incoming(connection, 2)
            self.record(connection, 3)
            self.update(
                connection,
                "incoming_thread_records",
                identifier("incoming_thread_record"),
                record_id=identifier("thread_record", 3),
                appended_at=2,
                updated_at=2,
            )
            self.invalid(
                connection,
                lambda: self.update(
                    connection,
                    "incoming_thread_records",
                    identifier("incoming_thread_record"),
                    cancelled_at=3,
                    cancelled_by_staff_member_id=identifier("staff_member"),
                    updated_at=3,
                ),
            )
            self.update(
                connection,
                "incoming_thread_records",
                identifier("incoming_thread_record", 2),
                cancelled_at=2,
                cancelled_by_staff_member_id=identifier("staff_member"),
                updated_at=2,
            )

        # Losing the race rolls back the history append as well as its receipt.
        with (
            self.assertRaises(IntegrityError),
            transaction(self.engine, write=True) as connection,
        ):
            self.record(connection, 4, sequence=3)
            self.update(
                connection,
                "incoming_thread_records",
                identifier("incoming_thread_record", 2),
                record_id=identifier("thread_record", 4),
                appended_at=3,
                updated_at=3,
            )
        with self.engine.connect() as connection:
            records = self.metadata.tables["thread_records"]
            self.assertIsNone(
                connection.execute(
                    records.select().where(
                        records.c.id == identifier("thread_record", 4)
                    )
                ).first()
            )

    def test_input_cancellation_migration_preserves_pending_messages(self):
        """Adding cancellation fields preserves existing pending messages."""
        self.migrate("0002_runtime", downgrade=True)
        with transaction(self.engine, write=True) as connection:
            self.incoming(connection)
        self.migrate("head")
        with self.engine.connect() as connection:
            target = self.metadata.tables["incoming_thread_records"]
            saved = connection.execute(target.select()).mappings().one()
            self.assertIsNone(saved["cancelled_at"])
            self.assertEqual(
                saved["payload_json"], '{"text":"Avoid morning activities"}'
            )
            self.assertEqual(
                connection.exec_driver_sql("PRAGMA foreign_key_check").all(), []
            )

    def test_downgrade_cannot_turn_cancelled_input_back_into_pending_input(self):
        """Downgrade is blocked when it would make withdrawn messages pending again."""
        with transaction(self.engine, write=True) as connection:
            self.incoming(
                connection,
                cancelled_at=1,
                cancelled_by_staff_member_id=identifier("staff_member"),
            )
        with self.assertRaisesRegex(
            RuntimeError, "would make cancelled messages pending again"
        ):
            self.migrate("0002_runtime", downgrade=True)
        with self.engine.connect() as connection:
            target = self.metadata.tables["incoming_thread_records"]
            self.assertEqual(
                connection.execute(target.select()).mappings().one()["cancelled_at"], 1
            )

    def test_creation_and_update_timestamps_are_required_on_mutable_rows(self):
        """Mutable rows require timestamps, with updates no earlier than creation."""
        mutable = (
            "hotels",
            "staff_members",
            "rooms",
            "beds",
            "bookings",
            "guests",
            "party_details",
            "room_keys",
            "venues",
            "activities",
            "activity_types",
            "threads",
            "runs",
            "incoming_thread_records",
            "inference_requests",
            "request_deduplication",
            "jobs",
            "tasks",
            "task_claims",
            "completion_outbox",
        )
        for table in mutable:
            for name in ("created_at", "updated_at"):
                self.assertFalse(self.metadata.tables[table].c[name].nullable)
        with transaction(self.engine, write=True) as connection:
            self.invalid(
                connection,
                lambda: self.update(
                    connection, "threads", identifier("thread"), updated_at=-1
                ),
            )
            self.update(
                connection,
                "threads",
                identifier("thread"),
                title="New title",
                updated_at=5,
            )
            self.assertEqual(
                connection.execute(
                    sa.select(self.metadata.tables["threads"].c.updated_at).where(
                        self.metadata.tables["threads"].c.id == identifier("thread")
                    )
                ).scalar_one(),
                5,
            )

    def test_jobs_tasks_claims_and_completion_identity(self):
        """Duplicate steps, simultaneous claims and duplicate completions fail."""
        with transaction(self.engine, write=True) as connection:
            self.record(connection, 3, kind="THREAD_RECORD_KIND_ASSISTANT_MESSAGE")
            self.job(
                connection,
                source_record_id=identifier("thread_record", 3),
                tool_call_id="call-1",
            )

            def task(number, step):
                self.insert(
                    connection,
                    "tasks",
                    id=identifier("task", number),
                    created_at=1,
                    job_id=identifier("job"),
                    step_key=step,
                    handler="demo",
                    format_version=1,
                    input_json="{}",
                    status="TASK_STATUS_READY",
                    attempt_count=0,
                    available_at=1,
                )

            task(1, "first")
            self.invalid(connection, lambda: task(2, "first"))
            task(2, "second")

            def claim(token):
                self.insert(
                    connection,
                    "task_claims",
                    task_id=identifier("task"),
                    token=token,
                    worker_id="worker",
                    claimed_at=1,
                    heartbeat_at=2,
                    expires_at=10,
                )

            claim("one")
            self.invalid(connection, lambda: claim("two"))

            def completion(number):
                self.insert(
                    connection,
                    "completion_outbox",
                    id=identifier("completion", number),
                    created_at=4,
                    job_id=identifier("job"),
                    thread_id=identifier("thread"),
                    format_version=1,
                    payload_json="{}",
                )

            self.invalid(connection, lambda: completion(1))
            self.update(
                connection,
                "jobs",
                identifier("job"),
                status="JOB_STATUS_SUCCEEDED",
                result_json="{}",
                finished_at=4,
            )
            completion(1)
            self.invalid(connection, lambda: completion(2))
            self.record(
                connection,
                4,
                sequence=3,
                kind="THREAD_RECORD_KIND_TOOL_RESULT",
                source_record_id=identifier("thread_record", 3),
                tool_call_id="call-1",
            )
            self.update(
                connection,
                "completion_outbox",
                identifier("completion"),
                record_id=identifier("thread_record", 4),
                appended_at=5,
            )
            self.invalid(
                connection,
                lambda: self.update(
                    connection,
                    "completion_outbox",
                    identifier("completion"),
                    record_id=None,
                    appended_at=None,
                ),
            )
