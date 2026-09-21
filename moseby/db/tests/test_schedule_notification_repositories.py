"""Keep accepted work and published messages visible only within their saved scope."""

import json

from pydantic import ValidationError
from sqlalchemy import select, update

from moseby.db import tables
from moseby.db.models.notification_requests import NotificationFilters
from moseby.db.models.published_events import EventPosition
from moseby.db.models.schedules import ScheduleFilters
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import (
    notification_requests,
    published_events,
    schedule_occurrences,
    schedules,
)
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction
from moseby.domain.enums import StaffRole
from moseby.runtime.enums import JobStatus


class ScheduleNotificationRepositoryTests(StayDatabaseTestCase):
    def setUp(self):
        """Give staff separate schedules and messages, including links outside their scope."""
        super().setUp()
        self.actor = {"actor_staff_member_id": identifier("staff_member")}
        self.audience = {
            "staff_member_id": identifier("staff_member"),
            "hotel_id": identifier("hotel"),
        }
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
            for number, actor, thread, enabled in (
                (1, 1, 1, True),
                (2, 1, None, True),
                (3, 2, 2, True),
                (4, 1, 2, True),
                (5, 2, 1, True),
                (6, 1, 1, False),
            ):
                self.insert(
                    connection,
                    "schedules",
                    id=identifier("schedule", number),
                    actor_staff_member_id=identifier("staff_member", actor),
                    thread_id=identifier("thread", thread) if thread else None,
                    revision=1,
                    enabled=int(enabled),
                    due_at=NOW if number == 2 else None,
                    cron_expression=None if number == 2 else "0 9 * * *",
                    cron_dialect=None if number == 2 else "test-five-field",
                    handler="send_reminder",
                    format_version=1,
                    input_json=json.dumps({"text": "Breakfast", "schedule": number}),
                )
            for number, schedule, actor, thread, due_at in (
                (1, 1, 1, 1, NOW - 2),
                (2, 1, 1, 1, NOW - 1),
                (3, 2, 1, None, NOW),
                (4, 3, 2, 2, NOW),
                (5, 4, 1, 2, NOW),
                (6, 5, 2, 1, NOW),
                (7, 1, 1, 2, NOW),
                (8, 3, 1, 1, NOW - 1),
            ):
                actor_id = identifier("staff_member", actor)
                self.insert(
                    connection,
                    "request_deduplication",
                    actor_staff_member_id=actor_id,
                    operation="send_reminder",
                    request_id=f"firing-{number}",
                    request_json="{}",
                )
                self.insert(
                    connection,
                    "jobs",
                    id=identifier("job", number),
                    actor_staff_member_id=actor_id,
                    operation="send_reminder",
                    request_id=f"firing-{number}",
                    thread_id=identifier("thread", thread) if thread else None,
                    handler="send_reminder",
                    phase="START",
                    format_version=1,
                    input_json='{"text":"Breakfast"}',
                    status=JobStatus.QUEUED.value,
                )
                self.insert(
                    connection,
                    "schedule_occurrences",
                    id=identifier("occurrence", number),
                    schedule_id=identifier("schedule", schedule),
                    schedule_revision=1,
                    due_at=due_at,
                    format_version=1,
                    job_id=identifier("job", number),
                    snapshot_json='{"input":{"text":"Breakfast"},"revision":1}',
                )
            for number, actor, guest, staff in (
                (1, 1, 1, None),
                (2, 2, None, 1),
                (3, 2, 1, None),
                (4, 1, 2, None),
                (5, 3, None, 3),
                (6, 1, None, 2),
                (7, 2, None, 1),
                (8, 1, 1, None),
            ):
                self.insert(
                    connection,
                    "notification_requests",
                    id=identifier("notification", number),
                    actor_staff_member_id=identifier("staff_member", actor),
                    recipient_guest_id=identifier("guest", guest) if guest else None,
                    recipient_staff_member_id=identifier("staff_member", staff)
                    if staff
                    else None,
                    request_id="shared" if number in (1, 2) else f"message-{number}",
                    format_version=1,
                    payload_json=json.dumps({"text": f"Message {number}"}),
                )
            for notification, sequence in (
                (1, 2),
                (2, 4),
                (3, 5),
                (4, 7),
                (5, 9),
                (6, 12),
            ):
                self.publish(connection, notification, sequence)

    def publish(self, connection, number, sequence):
        """Save an event and its publication receipt together, as the publisher will."""
        self.insert(
            connection,
            "published_events",
            sequence=sequence,
            notification_id=identifier("notification", number),
            created_at=NOW + 1,
            format_version=1,
            payload_json=json.dumps({"text": f"Message {number}"}),
        )
        connection.execute(
            update(tables.notification_requests)
            .where(
                tables.notification_requests.c.id == identifier("notification", number)
            )
            .values(published_at=NOW + 1, updated_at=NOW + 1)
        )

    def test_schedule_reads_keep_current_timing_and_disabled_rules(self):
        """When a rule is disabled, it remains readable alongside recurring and one-off rules."""
        with self.engine.connect() as connection:
            page = schedules.find_all(connection, **self.actor)
            self.assertEqual(
                [r.id for r in page.items],
                [identifier("schedule", n) for n in (1, 2, 6)],
            )
            recurring, one_off, disabled = page.items
            self.assertEqual(recurring.cron_expression, "0 9 * * *")
            self.assertEqual(recurring.input, {"text": "Breakfast", "schedule": 1})
            self.assertIs(recurring.enabled, True)
            self.assertEqual(one_off.due_at, NOW)
            self.assertIsNone(one_off.thread_id)
            self.assertIsNone(one_off.cron_expression)
            self.assertIs(disabled.enabled, False)
            self.assertEqual(
                len(
                    schedules.find_all_by_thread_id(
                        connection, identifier("thread"), **self.actor
                    ).items
                ),
                2,
            )
            self.assertEqual(
                schedules.find_all_by_thread_id(
                    connection, identifier("thread", 2), **self.actor
                ).items,
                [],
            )

    def test_schedule_filters_and_ownership_apply_before_paging(self):
        """When a search includes another actor's rules, they cannot enter a result page."""
        with self.engine.connect() as connection:
            first = schedules.search(
                connection,
                ScheduleFilters(enabled=True),
                page=PageRequest(limit=1),
                **self.actor,
            )
            self.assertEqual(first.items[0].id, identifier("schedule", 1))
            second = schedules.search(
                connection,
                ScheduleFilters(enabled=True),
                page=PageRequest(limit=1, cursor=first.next_cursor),
                **self.actor,
            )
            self.assertEqual(second.items[0].id, identifier("schedule", 2))
            self.assertIsNone(second.next_cursor)
            filtered = schedules.search(
                connection,
                ScheduleFilters(
                    ids=[identifier("schedule", n) for n in (1, 4, 6)],
                    thread_ids=[identifier("thread")],
                    enabled=False,
                ),
                **self.actor,
            )
            self.assertEqual(
                [r.id for r in filtered.items], [identifier("schedule", 6)]
            )
            with self.assertRaises(InvalidCursor):
                schedules.search(
                    connection,
                    ScheduleFilters(enabled=False),
                    page=PageRequest(cursor=first.next_cursor),
                    **self.actor,
                )
            with self.assertRaises(InvalidCursor):
                schedules.search(
                    connection,
                    ScheduleFilters(enabled=True),
                    page=PageRequest(cursor=first.next_cursor),
                    actor_staff_member_id=identifier("staff_member", 2),
                )

    def test_schedule_and_occurrence_batches_keep_their_ownership_rules(self):
        """When either owner or thread differs, exact IDs do not bypass the scope check."""
        with self.engine.connect() as connection:
            for repo, prefix, visible, hidden in (
                (schedules, "schedule", (1, 2, 6), (3, 4, 5, 999)),
                (schedule_occurrences, "occurrence", (1, 2, 3), (4, 5, 6, 7, 8, 999)),
            ):
                with self.subTest(repo=prefix):
                    ids = [
                        identifier(prefix, n) for n in (*visible, *hidden, visible[0])
                    ]
                    found = repo.find_by_ids(connection, ids, **self.actor)
                    self.assertEqual(
                        set(found), {identifier(prefix, n) for n in visible}
                    )
                    self.assertIsNotNone(
                        repo.find_by_id(
                            connection, identifier(prefix, visible[0]), **self.actor
                        )
                    )
                    for number in hidden:
                        self.assertIsNone(
                            repo.find_by_id(
                                connection, identifier(prefix, number), **self.actor
                            )
                        )
                    self.assertEqual(repo.find_by_ids(connection, [], **self.actor), {})
                    with self.assertRaises(ValueError):
                        repo.find_by_ids(connection, [ids[0]] * 101, **self.actor)

    def test_occurrence_reads_follow_the_original_job_after_schedule_edits(self):
        """When a schedule changes destination, its accepted firings keep their original scope."""
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                update(tables.schedules)
                .where(tables.schedules.c.id == identifier("schedule"))
                .values(
                    revision=2,
                    enabled=False,
                    thread_id=identifier("thread", 2),
                    input_json={"text": "Dinner"},
                    updated_at=NOW + 2,
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
            self.assertIsNone(
                schedules.find_by_id(connection, identifier("schedule"), **self.actor)
            )
            first = schedule_occurrences.find_all_by_schedule_id(
                connection,
                identifier("schedule"),
                page=PageRequest(limit=1),
                **self.actor,
            )
            self.assertEqual(first.items[0].schedule_revision, 1)
            self.assertEqual(first.items[0].snapshot["input"], {"text": "Breakfast"})
            self.assertEqual(first.items[0].job_id, identifier("job"))
            second = schedule_occurrences.find_all_by_schedule_id(
                connection,
                identifier("schedule"),
                page=PageRequest(limit=1, cursor=first.next_cursor),
                **self.actor,
            )
            self.assertEqual(
                [r.id for r in second.items], [identifier("occurrence", 2)]
            )
            self.assertIsNone(second.next_cursor)
            with self.assertRaises(InvalidCursor):
                schedule_occurrences.find_all_by_schedule_id(
                    connection,
                    identifier("schedule", 2),
                    page=PageRequest(cursor=first.next_cursor),
                    **self.actor,
                )

    def test_occurrence_lookups_use_job_or_schedule_and_due_time(self):
        """When the scheduler checks a due time again, it can find the already accepted firing."""
        with self.engine.connect() as connection:
            row = schedule_occurrences.find_by_schedule_id_and_due_at(
                connection, identifier("schedule"), NOW - 2, **self.actor
            )
            self.assertEqual(row.id, identifier("occurrence"))
            self.assertEqual(
                schedule_occurrences.find_by_job_id(
                    connection, identifier("job"), **self.actor
                ),
                row,
            )
            for number in (4, 7, 8, 999):
                self.assertIsNone(
                    schedule_occurrences.find_by_job_id(
                        connection, identifier("job", number), **self.actor
                    )
                )
            self.assertIsNone(
                schedule_occurrences.find_by_schedule_id_and_due_at(
                    connection, identifier("schedule"), NOW, **self.actor
                )
            )
            self.assertIsNone(
                schedule_occurrences.find_by_schedule_id_and_due_at(
                    connection, identifier("schedule"), NOW + 1, **self.actor
                )
            )

    def test_notification_audience_requires_authorship_or_staff_receipt_and_hotel(self):
        """When another concierge contacts a guest, sharing their hotel alone does not expose it."""
        with self.engine.connect() as connection:
            page = notification_requests.find_all(connection, **self.audience)
            self.assertEqual(
                [r.id for r in page.items],
                [identifier("notification", n) for n in (1, 2, 6, 7, 8)],
            )
            self.assertEqual(page.items[0].payload, {"text": "Message 1"})
            for number in (3, 4, 5, 999):
                self.assertIsNone(
                    notification_requests.find_by_id(
                        connection, identifier("notification", number), **self.audience
                    )
                )
                self.assertIsNone(
                    published_events.find_by_notification_id(
                        connection, identifier("notification", number), **self.audience
                    )
                )
            self.assertEqual(
                notification_requests.find_by_id(
                    connection, identifier("notification", 2), **self.audience
                ).recipient_staff_member_id,
                identifier("staff_member"),
            )
            other_hotel = notification_requests.find_all(
                connection,
                staff_member_id=identifier("staff_member", 3),
                hotel_id=identifier("hotel", 2),
            )
            self.assertEqual(
                [r.id for r in other_hotel.items], [identifier("notification", 5)]
            )

    def test_notification_request_id_lookup_only_finds_the_authors_command(self):
        """When authors reuse a request ID, each lookup returns that author's own notification."""
        with self.engine.connect() as connection:
            for actor, expected in ((1, 1), (2, 2)):
                row = notification_requests.find_by_request_id(
                    connection,
                    "shared",
                    actor_staff_member_id=identifier("staff_member", actor),
                    hotel_id=identifier("hotel"),
                )
                self.assertEqual(row.id, identifier("notification", expected))
            self.assertIsNone(
                notification_requests.find_by_request_id(
                    connection, "message-7", hotel_id=identifier("hotel"), **self.actor
                )
            )
            self.assertIsNone(
                notification_requests.find_by_request_id(
                    connection, "message-4", hotel_id=identifier("hotel"), **self.actor
                )
            )
            self.assertIsNone(
                notification_requests.find_by_request_id(
                    connection, "missing", hotel_id=identifier("hotel"), **self.actor
                )
            )

    def test_notification_batches_and_filters_are_bounded_and_scoped(self):
        """When exact IDs or recipient filters are supplied, they still respect audience checks."""
        with self.engine.connect() as connection:
            ids = [identifier("notification", n) for n in (1, 1, 3, 4, 7, 999)]
            self.assertEqual(
                set(
                    notification_requests.find_by_ids(connection, ids, **self.audience)
                ),
                {identifier("notification", n) for n in (1, 7)},
            )
            self.assertEqual(
                notification_requests.find_by_ids(connection, [], **self.audience), {}
            )
            with self.assertRaises(ValueError):
                notification_requests.find_by_ids(
                    connection, [ids[0]] * 101, **self.audience
                )
            page = notification_requests.search(
                connection,
                NotificationFilters(
                    ids=[identifier("notification", n) for n in (1, 2, 3, 4, 8)],
                    recipient_guest_ids=[identifier("guest")],
                    pending_only=True,
                ),
                page=PageRequest(limit=1),
                **self.audience,
            )
            self.assertEqual(
                [r.id for r in page.items], [identifier("notification", 8)]
            )
            staff = notification_requests.search(
                connection,
                NotificationFilters(
                    recipient_staff_member_ids=[identifier("staff_member")]
                ),
                **self.audience,
            )
            self.assertEqual(
                [r.id for r in staff.items],
                [identifier("notification", n) for n in (2, 7)],
            )
            with self.assertRaises(ValidationError):
                NotificationFilters(ids=ids * 21)

    def test_notification_pages_keep_filters_and_audience_bound_to_the_cursor(self):
        """When the audience or search changes, an earlier page's cursor cannot be reused."""
        with self.engine.connect() as connection:
            first = notification_requests.find_all(
                connection, page=PageRequest(limit=1), **self.audience
            )
            second = notification_requests.find_all(
                connection,
                page=PageRequest(limit=1, cursor=first.next_cursor),
                **self.audience,
            )
            self.assertEqual(second.items[0].id, identifier("notification", 2))
            for scope in (
                self.audience | {"staff_member_id": identifier("staff_member", 2)},
                self.audience | {"hotel_id": identifier("hotel", 2)},
            ):
                with self.assertRaises(InvalidCursor):
                    notification_requests.find_all(
                        connection, page=PageRequest(cursor=first.next_cursor), **scope
                    )
            with self.assertRaises(InvalidCursor):
                notification_requests.search(
                    connection,
                    NotificationFilters(pending_only=True),
                    page=PageRequest(cursor=first.next_cursor),
                    **self.audience,
                )

    def test_event_pages_skip_gaps_and_hidden_messages_before_applying_the_limit(self):
        """When hidden events sit between visible ones, the consumer can still fill its next page."""
        with self.engine.connect() as connection:
            first = published_events.find_all_after_sequence(
                connection, EventPosition(limit=2), **self.audience
            )
            self.assertEqual([r.sequence for r in first.items], [2, 4])
            self.assertEqual(first.next_sequence, 4)
            second = published_events.find_all_after_sequence(
                connection, EventPosition(after_sequence=4, limit=2), **self.audience
            )
            self.assertEqual([r.sequence for r in second.items], [12])
            self.assertEqual(second.next_sequence, 12)
            self.assertEqual(second.items[0].payload, {"text": "Message 6"})
            self.assertEqual(
                published_events.find_by_notification_id(
                    connection, identifier("notification", 6), **self.audience
                ),
                second.items[0],
            )
            empty = published_events.find_all_after_sequence(
                connection, EventPosition(after_sequence=12), **self.audience
            )
            self.assertEqual(empty.items, [])
            self.assertEqual(empty.next_sequence, 12)
            self.assertEqual(
                published_events.find_all_after_sequence(
                    connection, EventPosition(limit=2), **self.audience
                ),
                first,
            )

    def test_new_publication_appears_after_an_empty_poll_without_acknowledging_it(self):
        """When a message is published after an empty poll, the saved position finds it next time."""
        with transaction(self.engine, write=True) as connection:
            self.assertIsNone(
                published_events.find_by_notification_id(
                    connection, identifier("notification", 8), **self.audience
                )
            )
            self.publish(connection, 8, 20)
            page = published_events.find_all_after_sequence(
                connection, EventPosition(after_sequence=12), **self.audience
            )
            self.assertEqual([r.sequence for r in page.items], [20])
            notification = notification_requests.find_by_id(
                connection, identifier("notification", 8), **self.audience
            )
            self.assertEqual(notification.published_at, NOW + 1)
            pending = notification_requests.search(
                connection, NotificationFilters(pending_only=True), **self.audience
            )
            self.assertEqual(
                [r.id for r in pending.items], [identifier("notification", 7)]
            )
            self.assertEqual(
                connection.scalar(
                    select(tables.published_events.c.sequence).where(
                        tables.published_events.c.notification_id == notification.id
                    )
                ),
                20,
            )

    def test_event_position_rejects_invalid_limits_and_sequence_values(self):
        """When a caller supplies an invalid position, it fails before SQLite receives the value."""
        for values in (
            {"after_sequence": -1},
            {"after_sequence": 2**63},
            {"after_sequence": "1"},
            {"limit": 0},
            {"limit": 101},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                EventPosition(**values)

    def test_reads_share_the_callers_transaction_without_committing_changes(self):
        """When the caller rolls back, a schedule edit and publication read inside it both disappear."""
        with self.assertRaisesRegex(RuntimeError, "roll back"):
            with transaction(self.engine, write=True) as connection:
                connection.execute(
                    update(tables.schedules)
                    .where(tables.schedules.c.id == identifier("schedule"))
                    .values(revision=2, enabled=False, updated_at=NOW + 2)
                )
                self.publish(connection, 8, 20)
                self.assertFalse(
                    schedules.find_by_id(
                        connection, identifier("schedule"), **self.actor
                    ).enabled
                )
                self.assertIsNotNone(
                    published_events.find_by_notification_id(
                        connection, identifier("notification", 8), **self.audience
                    )
                )
                self.assertEqual(
                    schedule_occurrences.find_by_job_id(
                        connection, identifier("job"), **self.actor
                    ).schedule_revision,
                    1,
                )
                raise RuntimeError("roll back")
        with self.engine.connect() as connection:
            self.assertEqual(
                schedules.find_by_id(
                    connection, identifier("schedule"), **self.actor
                ).revision,
                1,
            )
            self.assertIsNone(
                notification_requests.find_by_id(
                    connection, identifier("notification", 8), **self.audience
                ).published_at
            )
            self.assertIsNone(
                published_events.find_by_notification_id(
                    connection, identifier("notification", 8), **self.audience
                )
            )
