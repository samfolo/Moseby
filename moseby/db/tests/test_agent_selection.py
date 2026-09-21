from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from moseby.agents.identity import AgentReference
from moseby.agents.models import AgentThreadContext
from moseby.db.errors import IdempotencyConflict, WriteConflict
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import runs, thread_records, threads
from moseby.db.tests.fixtures import NOW, ROOT, StayDatabaseTestCase, identifier
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.domain.enums import StaffRole
from moseby.permissions import Permission
from moseby.runtime.enums import RunStatus
from moseby.runtime.models.thread_records import (
    ThreadCreatedPayload,
    ThreadCreatedRecord,
    ThreadRecordKind,
    thread_record_adapter,
)


class AgentSelectionTests(StayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.creator = {"creator_staff_member_id": identifier("staff_member")}
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "staff_members",
                id=identifier("staff_member"),
                hotel_id=identifier("hotel"),
                staff_code="CONCIERGE",
                first_name="Alex",
                last_name="Morgan",
                role=StaffRole.CONCIERGE.value,
            )
            self.insert(
                connection,
                "threads",
                id=identifier("thread"),
                **self.creator,
                permissions_json='["moseby.guests:read"]',
                projection_sequence=0,
                projection_format_version=1,
                projection_json="{}",
            )

    def attributed_thread(self, connection, number=2, agent_id="concierge", version=2):
        self.insert(
            connection,
            "threads",
            id=identifier("thread", number),
            **self.creator,
            permissions_json='["moseby.guests:read"]',
            projection_sequence=0,
            projection_format_version=1,
            projection_json="{}",
            agent_id=agent_id,
            agent_version=version,
        )

    def creation_record(self, agent, number=1):
        return ThreadCreatedRecord(
            id=identifier("thread_record", number),
            thread_id=identifier("thread", number),
            sequence=1,
            kind=ThreadRecordKind.THREAD_CREATED,
            format_version=1,
            created_at=to_datetime(NOW),
            payload=ThreadCreatedPayload(
                **self.creator,
                permissions=[Permission("moseby.guests:read")],
                agent=agent,
            ),
        )

    def test_saved_selection_restores_the_same_agent_version_and_permissions(self):
        """A fresh database read restores the selection that created the thread."""
        selection = AgentReference(id="concierge", version=2)
        record = self.creation_record(selection, number=2)
        with transaction(self.engine, write=True) as connection:
            self.attributed_thread(connection)
            saved = thread_records.append(connection, record, **self.creator)
            self.assertEqual(
                thread_records.append(connection, record, **self.creator), saved
            )
        with transaction(self.engine) as connection:
            saved = thread_records.find_by_id(connection, record.id, **self.creator)
            self.assertIsNotNone(saved)
            decoded = thread_record_adapter.validate_python(
                saved.model_dump() | {"created_at": to_datetime(saved.created_at)}
            )
        context = AgentThreadContext.from_creation_record(decoded)
        self.assertEqual(context.agent, selection)
        self.assertEqual(context.thread_id, record.thread_id)
        self.assertEqual(context.permissions, (Permission("moseby.guests:read"),))
        with transaction(self.engine, write=True) as connection:
            with self.assertRaises(IdempotencyConflict):
                thread_records.append(
                    connection,
                    self.creation_record(
                        AgentReference(id="concierge", version=3), number=2
                    ),
                    **self.creator,
                )

    def test_history_without_a_selection_stays_readable_but_cannot_choose_an_agent(
        self,
    ):
        """Reading an older thread preserves its payload and never guesses an agent."""
        record = self.creation_record(None)
        self.assertNotIn("agent", record.payload.model_dump())
        with transaction(self.engine, write=True) as connection:
            saved = thread_records.append(connection, record, **self.creator)
            self.assertNotIn("agent", saved.payload)
            self.assertEqual(
                thread_records.append(connection, record, **self.creator), saved
            )
        with self.assertRaisesRegex(ValueError, "no saved agent selection"):
            AgentThreadContext.from_creation_record(record)

    def test_runs_and_creation_history_must_match_the_thread(self):
        """A different agent or version cannot claim work belonging to this thread."""
        with transaction(self.engine, write=True) as connection:
            self.attributed_thread(connection)
            for agent_id, version in (("other", 2), ("concierge", 3), (None, None)):
                with self.subTest(agent_id=agent_id, version=version):
                    with self.assertRaises(IntegrityError):
                        self.insert(
                            connection,
                            "runs",
                            id=identifier("run"),
                            thread_id=identifier("thread", 2),
                            status=RunStatus.RUNNING.value,
                            recovery_attempts=0,
                            agent_id=agent_id,
                            agent_version=version,
                        )
            with self.assertRaises(WriteConflict):
                thread_records.append(
                    connection,
                    self.creation_record(AgentReference(id="other", version=2), 2),
                    **self.creator,
                )
            with self.assertRaises(IntegrityError):
                self.insert(
                    connection,
                    "thread_records",
                    id=identifier("thread_record", 2),
                    thread_id=identifier("thread", 2),
                    sequence=1,
                    kind=ThreadRecordKind.THREAD_CREATED.value,
                    format_version=1,
                    payload_json='{"agent":{"id":"other","version":2}}',
                )
            self.insert(
                connection,
                "runs",
                id=identifier("run"),
                thread_id=identifier("thread", 2),
                status=RunStatus.RUNNING.value,
                recovery_attempts=0,
                agent_id="concierge",
                agent_version=2,
            )
            for table in ("threads", "runs"):
                with self.assertRaises(IntegrityError):
                    connection.execute(
                        self.metadata.tables[table].update().values(agent_version=3)
                    )

    def test_agent_search_filters_before_paging_and_keeps_creator_scope(self):
        """Agent evaluation pages include only matching versions owned by this creator."""
        with transaction(self.engine, write=True) as connection:
            for number, agent_id, version in (
                (2, "concierge", 1),
                (3, "other", 1),
                (4, "concierge", 2),
            ):
                self.attributed_thread(connection, number, agent_id, version)
                self.insert(
                    connection,
                    "runs",
                    id=identifier("run", number),
                    thread_id=identifier("thread", number),
                    status=RunStatus.RUNNING.value,
                    recovery_attempts=0,
                    agent_id=agent_id,
                    agent_version=version,
                )
        with transaction(self.engine) as connection:
            for repository in (threads, runs):
                first = repository.find_all_by_agent_id(
                    connection, "concierge", **self.creator, page=PageRequest(limit=1)
                )
                second = repository.find_all_by_agent_id(
                    connection,
                    "concierge",
                    **self.creator,
                    page=PageRequest(limit=1, cursor=first.next_cursor),
                )
                self.assertEqual(
                    [first.items[0].agent_version, second.items[0].agent_version],
                    [1, 2],
                )
                self.assertIsNone(second.next_cursor)
                version = repository.find_all_by_agent_id(
                    connection, "concierge", **self.creator, agent_version=2
                )
                self.assertEqual([row.agent_version for row in version.items], [2])
                with self.assertRaises(InvalidCursor):
                    repository.find_all_by_agent_id(
                        connection,
                        "other",
                        **self.creator,
                        page=PageRequest(cursor=first.next_cursor),
                    )
                hidden = repository.find_all_by_agent_id(
                    connection,
                    "concierge",
                    creator_staff_member_id=identifier("staff_member", 99),
                )
                self.assertEqual(hidden.items, [])

    def test_invalid_attribution_is_rejected_at_the_database_boundary(self):
        """A selection needs both fields, a readable bounded ID and a positive version."""
        with transaction(self.engine, write=True) as connection:
            for agent_id, version in (
                (None, 1),
                ("concierge", None),
                ("concierge", 0),
                ("UPPER", 1),
                ("bad--id", 1),
                ("bad-", 1),
                ("a" * 65, 1),
            ):
                with (
                    self.subTest(agent_id=agent_id, version=version),
                    self.assertRaises(IntegrityError),
                ):
                    self.attributed_thread(connection, 2, agent_id, version)

    def test_upgrade_recovers_attribution_from_creation_history(self):
        """Migration preserves unknown history and copies an existing selection into its run."""
        config = Config(str(ROOT / "alembic.ini"))
        with transaction(self.engine, write=True) as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "0004_party_detail_search")
            self.insert(
                connection,
                "thread_records",
                id=identifier("thread_record"),
                thread_id=identifier("thread"),
                sequence=1,
                kind=ThreadRecordKind.THREAD_CREATED.value,
                format_version=1,
                payload_json='{"agent":{"id":"concierge","version":2}}',
            )
            self.insert(
                connection,
                "runs",
                id=identifier("run"),
                thread_id=identifier("thread"),
                status=RunStatus.RUNNING.value,
                recovery_attempts=0,
            )
            command.upgrade(config, "head")
            thread = threads.find_by_id(
                connection, identifier("thread"), **self.creator
            )
            run = runs.find_by_id(connection, identifier("run"), **self.creator)
            self.assertEqual((thread.agent_id, thread.agent_version), ("concierge", 2))
            self.assertEqual((run.agent_id, run.agent_version), ("concierge", 2))
            with self.assertRaisesRegex(RuntimeError, "carry agent attribution"):
                command.downgrade(config, "0004_party_detail_search")
