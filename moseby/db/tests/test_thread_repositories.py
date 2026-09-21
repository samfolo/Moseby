"""Read thread state and ordered input without crossing creator boundaries."""

import base64
import json

from sqlalchemy import update

from moseby.db import tables
from moseby.db.models.incoming_thread_records import IncomingThreadRecordFilters
from moseby.db.models.thread_records import ThreadRecordFilters
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import (
    incoming_thread_records,
    runs,
    thread_records,
    threads,
)
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction
from moseby.permissions import Permission
from moseby.runtime.enums import RunStatus
from moseby.runtime.models.incoming_thread_records import (
    IncomingThreadRecordDeliveryMode,
)
from moseby.runtime.models.thread_records import ThreadRecordKind


def record_id(thread, sequence):
    """Make IDs run backwards so the tests can distinguish them from sequence order."""
    return identifier("thread_record", thread * 100 + 100 - sequence)


def input_id(thread, sequence):
    return identifier("incoming_thread_record", thread * 100 + 100 - sequence)


class ThreadRepositoryTests(StayDatabaseTestCase):
    def setUp(self):
        """Give two colleagues and a staff member at another hotel their own threads."""
        super().setUp()
        self.scope = {"creator_staff_member_id": identifier("staff_member")}
        with transaction(self.engine, write=True) as connection:
            for number in (1, 2, 3):
                self.insert(
                    connection,
                    "staff_members",
                    id=identifier("staff_member", number),
                    hotel_id=identifier("hotel", 2 if number == 3 else 1),
                    staff_code=f"STAFF-{number}",
                    first_name="Sam",
                    last_name="Staff",
                    role="STAFF_ROLE_CONCIERGE",
                )
            for thread in (1, 2, 3, 4):
                self.seed_thread(connection, thread)

    def seed_thread(self, connection, thread):
        """Save history and input with reversed timestamps, so only sequences order them."""
        actor = identifier("staff_member", 1 if thread == 4 else thread)
        old_run = identifier("run", thread * 10 + 1)
        active_run = identifier("run", thread * 10 + 2)
        self.insert(
            connection,
            "threads",
            id=identifier("thread", thread),
            creator_staff_member_id=actor,
            title=f"Thread {thread}",
            permissions_json='["moseby.threads:read"]',
            projection_sequence=0,
            projection_format_version=1,
            projection_json='{"summary":"Saved summary"}',
            archived_at=NOW + 100 if thread == 4 else None,
            updated_at=NOW + 100,
        )
        self.insert(
            connection,
            "runs",
            id=old_run,
            thread_id=identifier("thread", thread),
            status=RunStatus.COMPLETED.value,
            recovery_attempts=0,
            finished_at=NOW + 5,
            updated_at=NOW + 5,
        )
        if thread != 4:
            self.insert(
                connection,
                "runs",
                id=active_run,
                thread_id=identifier("thread", thread),
                status=RunStatus.WAITING.value
                if thread == 1
                else RunStatus.RUNNING.value,
                wake_at=NOW + 1000 if thread == 1 else None,
                recovery_attempts=1,
                created_at=NOW + 6,
            )
        else:
            active_run = old_run
        records = (
            (
                ThreadRecordKind.THREAD_CREATED,
                {
                    "creator_staff_member_id": actor,
                    "permissions": ["moseby.threads:read"],
                },
            ),
            (ThreadRecordKind.USER_MESSAGE, {"text": "Find a room"}),
            (
                ThreadRecordKind.ASSISTANT_MESSAGE,
                {
                    "tool_calls": [
                        {"id": "call-1", "name": "search_rooms", "arguments": {}}
                    ]
                },
            ),
            (ThreadRecordKind.CONTROL_EVENT, {"name": "run.waiting", "data": {}}),
            (
                ThreadRecordKind.TOOL_RESULT,
                {"status": "TOOL_RESULT_STATUS_SUCCEEDED", "result": {"rooms": []}},
            ),
            (ThreadRecordKind.USER_MESSAGE, {"text": "Try tomorrow"}),
            (ThreadRecordKind.ASSISTANT_MESSAGE, {"text": "I will check again"}),
        )
        for sequence, (kind, payload) in enumerate(records, start=1):
            self.insert(
                connection,
                "thread_records",
                id=record_id(thread, sequence),
                thread_id=identifier("thread", thread),
                sequence=sequence,
                kind=kind.value,
                format_version=1,
                payload_json=json.dumps(payload),
                run_id=None if sequence == 1 else active_run,
                actor_staff_member_id=actor,
                created_at=NOW + 100 - sequence,
                source_record_id=record_id(thread, 3) if sequence == 5 else None,
                tool_call_id="call-1" if sequence == 5 else None,
            )
        for sequence in range(1, 6):
            changes = {}
            if sequence == 2:
                changes = dict(record_id=record_id(thread, 2), appended_at=NOW + 200)
            elif sequence == 3:
                changes = dict(
                    cancelled_at=NOW + 200, cancelled_by_staff_member_id=actor
                )
            elif sequence == 4:
                changes = dict(
                    delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE",
                    target_run_id=old_run,
                )
            elif sequence == 5:
                changes = dict(
                    kind="INCOMING_THREAD_RECORD_KIND_SCHEDULED_INPUT",
                    request_id=None,
                    payload_json=json.dumps(
                        {
                            "occurrence_id": identifier("occurrence", thread),
                            "text": "Prepare briefing",
                        }
                    ),
                )
            self.add_input(
                connection, thread, sequence, actor_staff_member_id=actor, **changes
            )

    def add_input(self, connection, thread, sequence, **changes):
        """Save a pending message unless the test supplies delivery or receipt fields."""
        values = dict(
            id=input_id(thread, sequence),
            thread_id=identifier("thread", thread),
            sequence=sequence,
            kind="INCOMING_THREAD_RECORD_KIND_USER_MESSAGE",
            delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE",
            actor_staff_member_id=identifier("staff_member"),
            request_id=f"input-{thread}-{sequence}",
            format_version=1,
            payload_json='{"text":"Please check availability"}',
            created_at=NOW + 100 - sequence,
            updated_at=NOW + 200,
        )
        self.insert(connection, "incoming_thread_records", **(values | changes))

    def test_single_and_batch_reads_follow_the_creator_not_the_hotel(self):
        """When two colleagues share a hotel, neither can read the other's thread data."""
        cases = (
            (threads, [identifier("thread", n) for n in (1, 2, 3, 999)]),
            (runs, [identifier("run", n) for n in (12, 22, 32, 999)]),
            (thread_records, [record_id(n, 2) for n in (1, 2, 3, 999)]),
            (incoming_thread_records, [input_id(n, 1) for n in (1, 2, 3, 999)]),
        )
        with transaction(self.engine) as connection:
            for repository, ids in cases:
                with self.subTest(repository=repository.__name__):
                    self.assertIsNotNone(
                        repository.find_by_id(connection, ids[0], **self.scope)
                    )
                    for id in ids[1:]:
                        self.assertIsNone(
                            repository.find_by_id(connection, id, **self.scope)
                        )
                    found = repository.find_by_ids(
                        connection, ids + [ids[0]], **self.scope
                    )
                    self.assertEqual(list(found), [ids[0]])
                    self.assertEqual(
                        repository.find_by_ids(connection, [], **self.scope), {}
                    )
                    with self.assertRaises(ValueError):
                        repository.find_by_ids(connection, [ids[0]] * 101, **self.scope)

    def test_thread_reads_decode_the_summary_and_permissions_and_include_archived(self):
        """When a thread is archived, its creator can still read its saved summary."""
        with transaction(self.engine) as connection:
            first = threads.find_all(
                connection, **self.scope, page=PageRequest(limit=1)
            )
            self.assertEqual(
                first.items[0].permissions, [Permission("moseby.threads:read")]
            )
            self.assertEqual(first.items[0].projection, {"summary": "Saved summary"})
            rest = threads.find_all(
                connection, **self.scope, page=PageRequest(cursor=first.next_cursor)
            )
            self.assertEqual([row.id for row in rest.items], [identifier("thread", 4)])
            self.assertIsNotNone(rest.items[0].archived_at)
            self.assertIsNone(rest.next_cursor)
            with self.assertRaises(InvalidCursor):
                threads.find_all(
                    connection,
                    creator_staff_member_id=identifier("staff_member", 2),
                    page=PageRequest(cursor=first.next_cursor),
                )

    def test_waiting_run_remains_active_until_cancellation_finishes(self):
        """When a waiting run receives a stop request, it stays active until it stops."""
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == identifier("run", 12))
                .values(
                    cancel_requested_at=NOW + 20,
                    cancel_requested_by_staff_member_id=identifier("staff_member"),
                    updated_at=NOW + 20,
                )
            )
            active = runs.find_active_by_thread_id(
                connection, identifier("thread"), **self.scope
            )
            self.assertIs(active.status, RunStatus.WAITING)
            self.assertEqual(active.wake_at, NOW + 1000)
            self.assertEqual(active.cancel_requested_at, NOW + 20)
            connection.execute(
                update(tables.runs)
                .where(tables.runs.c.id == active.id)
                .values(
                    status=RunStatus.CANCELLED.value,
                    wake_at=None,
                    finished_at=NOW + 30,
                    updated_at=NOW + 30,
                )
            )
            self.assertIsNone(
                runs.find_active_by_thread_id(
                    connection, identifier("thread"), **self.scope
                )
            )
            for number, status in ((13, RunStatus.QUEUED), (14, RunStatus.RUNNING)):
                self.insert(
                    connection,
                    "runs",
                    id=identifier("run", number),
                    thread_id=identifier("thread"),
                    status=status.value,
                    recovery_attempts=0,
                )
                self.assertIs(
                    runs.find_active_by_thread_id(
                        connection, identifier("thread"), **self.scope
                    ).status,
                    status,
                )
                connection.execute(
                    update(tables.runs)
                    .where(tables.runs.c.id == identifier("run", number))
                    .values(
                        status=RunStatus.FAILED.value,
                        finished_at=NOW + 40,
                        updated_at=NOW + 40,
                    )
                )

    def test_run_pages_keep_finished_runs_and_check_thread_ownership(self):
        """When a run finishes, it remains in the thread's history but frees its slot."""
        with transaction(self.engine) as connection:
            first = runs.find_all_by_thread_id(
                connection,
                identifier("thread"),
                **self.scope,
                page=PageRequest(limit=1),
            )
            rest = runs.find_all_by_thread_id(
                connection,
                identifier("thread"),
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.status for row in first.items + rest.items],
                [RunStatus.COMPLETED, RunStatus.WAITING],
            )
            self.assertIsNone(
                runs.find_active_by_thread_id(
                    connection, identifier("thread", 4), **self.scope
                )
            )
            for thread in (2, 3, 999):
                self.assertIsNone(
                    runs.find_active_by_thread_id(
                        connection, identifier("thread", thread), **self.scope
                    )
                )
                self.assertEqual(
                    runs.find_all_by_thread_id(
                        connection, identifier("thread", thread), **self.scope
                    ).items,
                    [],
                )

    def test_history_pages_follow_sequence_even_when_ids_and_times_disagree(self):
        """When timestamps and IDs run backwards, history still follows its sequence."""
        with transaction(self.engine) as connection:
            first = thread_records.find_all_by_thread_id(
                connection,
                identifier("thread"),
                **self.scope,
                page=PageRequest(limit=3),
            )
            rest = thread_records.find_all_by_thread_id(
                connection,
                identifier("thread"),
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.sequence for row in first.items + rest.items], list(range(1, 8))
            )
            self.assertIsNone(rest.next_cursor)
            result = rest.items[1]
            self.assertEqual(
                (result.source_record_id, result.tool_call_id),
                (record_id(1, 3), "call-1"),
            )
            self.assertEqual(result.payload["result"], {"rooms": []})

    def test_history_filters_apply_before_paging_and_preserve_sequence_gaps(self):
        """When internal events are filtered out, a page fills with matching messages."""
        kinds = [
            ThreadRecordKind.USER_MESSAGE,
            ThreadRecordKind.ASSISTANT_MESSAGE,
            ThreadRecordKind.TOOL_RESULT,
        ]
        with transaction(self.engine) as connection:
            filters = ThreadRecordFilters(
                thread_id=identifier("thread"),
                kinds=kinds,
                run_ids=[identifier("run", 12)],
            )
            first = thread_records.search(
                connection, filters, **self.scope, page=PageRequest(limit=3)
            )
            rest = thread_records.search(
                connection,
                filters,
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual([row.sequence for row in first.items], [2, 3, 5])
            self.assertEqual([row.sequence for row in rest.items], [6, 7])
            selected = thread_records.search(
                connection,
                ThreadRecordFilters(
                    thread_id=identifier("thread"),
                    ids=[record_id(1, 2), record_id(1, 3)],
                    kinds=[ThreadRecordKind.USER_MESSAGE],
                ),
                **self.scope,
            )
            self.assertEqual([row.sequence for row in selected.items], [2])

    def test_last_message_lookup_can_step_back_without_repeating_the_same_message(self):
        """When the caller asks for an earlier message, the current one is excluded."""
        with transaction(self.engine) as connection:
            last = thread_records.find_last_by_thread_id(
                connection,
                identifier("thread"),
                kind=ThreadRecordKind.ASSISTANT_MESSAGE,
                **self.scope,
            )
            previous = thread_records.find_last_by_thread_id(
                connection,
                identifier("thread"),
                kind=ThreadRecordKind.ASSISTANT_MESSAGE,
                before_sequence=last.sequence,
                **self.scope,
            )
            self.assertEqual((last.sequence, previous.sequence), (7, 3))
            self.assertIsNone(
                thread_records.find_last_by_thread_id(
                    connection,
                    identifier("thread"),
                    kind=ThreadRecordKind.ASSISTANT_MESSAGE,
                    before_sequence=3,
                    **self.scope,
                )
            )
            user = thread_records.find_last_by_thread_id(
                connection,
                identifier("thread"),
                kind=ThreadRecordKind.USER_MESSAGE,
                **self.scope,
            )
            self.assertEqual(user.sequence, 6)
            self.assertEqual(
                thread_records.find_last_by_thread_id(
                    connection, identifier("thread"), **self.scope
                ),
                last,
            )
            self.assertIsNone(
                thread_records.find_last_by_thread_id(
                    connection, identifier("thread", 2), **self.scope
                )
            )

    def test_pending_input_includes_steers_for_ended_runs_and_scheduled_input(self):
        """When a steer's run ends, the undelivered message stays in the pending list."""
        with transaction(self.engine) as connection:
            page = incoming_thread_records.search(
                connection,
                IncomingThreadRecordFilters(thread_id=identifier("thread")),
                **self.scope,
            )
            self.assertEqual([row.sequence for row in page.items], [1, 4, 5])
            steer = page.items[1]
            self.assertIs(
                steer.delivery_mode, IncomingThreadRecordDeliveryMode.ASSERTIVE
            )
            self.assertEqual(steer.target_run_id, identifier("run", 11))
            self.assertEqual(
                page.items[2].payload["occurrence_id"], identifier("occurrence")
            )
            all_input = incoming_thread_records.find_all_by_thread_id(
                connection, identifier("thread"), **self.scope
            )
            self.assertEqual([row.sequence for row in all_input.items], [1, 2, 3, 4, 5])
            self.assertEqual(all_input.items[1].record_id, record_id(1, 2))
            self.assertEqual(
                all_input.items[2].cancelled_by_staff_member_id,
                identifier("staff_member"),
            )

    def test_pending_pages_handle_delivery_and_new_arrivals_between_reads(self):
        """When input is delivered between pages, later input is still read once."""
        filters = IncomingThreadRecordFilters(thread_id=identifier("thread"))
        with transaction(self.engine) as connection:
            first = incoming_thread_records.search(
                connection, filters, **self.scope, page=PageRequest(limit=1)
            )
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                update(tables.incoming_thread_records)
                .where(tables.incoming_thread_records.c.id == input_id(1, 1))
                .values(
                    record_id=record_id(1, 6),
                    appended_at=NOW + 200,
                    updated_at=NOW + 200,
                )
            )
            self.add_input(connection, 1, 6)
        with transaction(self.engine) as connection:
            rest = incoming_thread_records.search(
                connection,
                filters,
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.sequence for row in first.items + rest.items], [1, 4, 5, 6]
            )
            self.assertIsNone(rest.next_cursor)

    def test_sequence_cursors_reject_changed_scope_filters_and_collection(self):
        """When a cursor is reused for a different view, the repository rejects it."""
        with transaction(self.engine) as connection:
            filters = ThreadRecordFilters(thread_id=identifier("thread"))
            first = thread_records.search(
                connection, filters, **self.scope, page=PageRequest(limit=1)
            )
            continuation = PageRequest(cursor=first.next_cursor)
            for changed, scope in (
                (ThreadRecordFilters(thread_id=identifier("thread", 4)), self.scope),
                (
                    ThreadRecordFilters(
                        thread_id=identifier("thread"),
                        kinds=[ThreadRecordKind.USER_MESSAGE],
                    ),
                    self.scope,
                ),
                (filters, {"creator_staff_member_id": identifier("staff_member", 2)}),
            ):
                with self.assertRaises(InvalidCursor):
                    thread_records.search(
                        connection, changed, **scope, page=continuation
                    )
            with self.assertRaises(InvalidCursor):
                incoming_thread_records.search(
                    connection,
                    IncomingThreadRecordFilters(thread_id=identifier("thread")),
                    **self.scope,
                    page=continuation,
                )
            with self.assertRaises(InvalidCursor):
                threads.find_all(connection, **self.scope, page=continuation)
            for token in ("invalid", first.next_cursor):
                if token == first.next_cursor:
                    data = json.loads(
                        base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
                    )
                    data["sequence"] = True
                    token = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
                with self.assertRaises(InvalidCursor):
                    thread_records.search(
                        connection,
                        filters,
                        **self.scope,
                        page=PageRequest(cursor=token),
                    )
            pending = incoming_thread_records.search(
                connection,
                IncomingThreadRecordFilters(thread_id=identifier("thread")),
                **self.scope,
                page=PageRequest(limit=1),
            )
            with self.assertRaises(InvalidCursor):
                incoming_thread_records.find_all_by_thread_id(
                    connection,
                    identifier("thread"),
                    **self.scope,
                    page=PageRequest(cursor=pending.next_cursor),
                )

    def test_equivalent_filter_lists_keep_the_same_sequence_cursor(self):
        """When filter IDs are reordered or repeated, the next page is unchanged."""
        with transaction(self.engine) as connection:
            values = [record_id(1, n) for n in (2, 3, 6)]
            first = thread_records.search(
                connection,
                ThreadRecordFilters(thread_id=identifier("thread"), ids=values),
                **self.scope,
                page=PageRequest(limit=1),
            )
            rest = thread_records.search(
                connection,
                ThreadRecordFilters(
                    thread_id=identifier("thread"), ids=[*reversed(values), values[0]]
                ),
                **self.scope,
                page=PageRequest(cursor=first.next_cursor),
            )
            self.assertEqual(
                [row.sequence for row in first.items + rest.items], [2, 3, 6]
            )

    def test_thread_scoped_lists_are_empty_for_other_creators_and_missing_threads(self):
        """When a thread is missing or belongs to someone else, its lists are empty."""
        with transaction(self.engine) as connection:
            for thread in (2, 3, 999):
                for repository in (thread_records, incoming_thread_records):
                    result = repository.find_all_by_thread_id(
                        connection, identifier("thread", thread), **self.scope
                    )
                    self.assertEqual(result.items, [])
                    self.assertIsNone(result.next_cursor)

    def test_reads_do_not_advance_the_thread_or_commit_pending_changes(self):
        """When a read sees an uncommitted change, the caller can still roll it back."""
        with self.assertRaisesRegex(RuntimeError, "roll back"):
            with transaction(self.engine, write=True) as connection:
                connection.execute(
                    update(tables.threads)
                    .where(tables.threads.c.id == identifier("thread"))
                    .values(title="Temporary")
                )
                thread = threads.find_by_id(
                    connection, identifier("thread"), **self.scope
                )
                self.assertEqual(thread.title, "Temporary")
                thread_records.find_all_by_thread_id(
                    connection, thread.id, **self.scope
                )
                incoming_thread_records.search(
                    connection,
                    IncomingThreadRecordFilters(thread_id=thread.id),
                    **self.scope,
                )
                self.assertEqual(
                    threads.find_by_id(
                        connection, thread.id, **self.scope
                    ).projection_sequence,
                    0,
                )
                raise RuntimeError("roll back")
        with transaction(self.engine) as connection:
            self.assertEqual(
                threads.find_by_id(
                    connection, identifier("thread"), **self.scope
                ).title,
                "Thread 1",
            )
