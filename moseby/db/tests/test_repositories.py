"""Read real migrated stays, including scope boundaries and changing page results."""

import base64
import json
import tempfile
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from pydantic import ValidationError

from moseby.db import tables
from moseby.db.connection import create_database_engine
from moseby.db.models.bookings import BookingRow
from moseby.db.models.guests import GuestRow
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import (
    bookings,
    guests,
    parties,
    room_keys,
    room_reservations,
)
from moseby.db.transaction import transaction

ROOT = Path(__file__).resolve().parents[3]
NOW = 1_800_000_000_123_456


def identifier(prefix, number=1):
    return f"{prefix}_{number:026d}"


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_database_engine(
            sa.URL.create("sqlite", database=f"{directory.name}/test.db")
        )
        self.addCleanup(self.engine.dispose)
        self.metadata = sa.MetaData()
        with transaction(self.engine, write=True) as connection:
            config = Config(str(ROOT / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            self.metadata.reflect(connection)
            self.seed(connection)

    def insert(self, connection, table, **values):
        target = self.metadata.tables[table]
        if "created_at" in target.c:
            values.setdefault("created_at", NOW)
        if "updated_at" in target.c:
            values.setdefault("updated_at", values["created_at"])
        connection.execute(target.insert().values(**values))

    def seed(self, connection):
        self.insert(connection, "prices", id=identifier("price"))
        self.insert(
            connection,
            "price_versions",
            price_id=identifier("price"),
            revision=1,
            amount_minor=20_000,
            currency="GBP",
        )
        for number in (1, 2):
            self.insert(
                connection, "hotels", id=identifier("hotel", number), name="Hotel"
            )
            self.insert(
                connection,
                "bookings",
                id=identifier("booking", number),
                hotel_id=identifier("hotel", number),
                name="Stay",
            )
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking", number),
                revision=1,
                status="BOOKING_STATUS_CONFIRMED",
            )
            self.insert(
                connection,
                "parties",
                id=identifier("party", number),
                booking_id=identifier("booking", number),
            )
            self.insert(
                connection,
                "guests",
                id=identifier("guest", number),
                party_id=identifier("party", number),
                first_name="Dan",
                last_name="Guest",
                age=30,
            )
            self.insert(
                connection,
                "rooms",
                id=identifier("room", number),
                hotel_id=identifier("hotel", number),
                label="Rose",
                description="",
                tier="ROOM_TIER_STANDARD",
                number_of_bathrooms=1,
                in_service=1,
                price_id=identifier("price"),
            )
            self.insert(
                connection,
                "room_reservations",
                id=identifier("room_reservation", number),
                room_id=identifier("room", number),
                booking_id=identifier("booking", number),
            )
            self.insert(
                connection,
                "room_reservation_revisions",
                room_reservation_id=identifier("room_reservation", number),
                revision=1,
                min_date=NOW,
                max_date=NOW + 100,
                cancelled=0,
                price_id=identifier("price"),
                price_revision=1,
            )
            self.insert(
                connection,
                "room_keys",
                id=identifier("room_key", number),
                room_reservation_id=identifier("room_reservation", number),
            )

    def add_guest(self, connection, number, **changes):
        values = dict(
            id=identifier("guest", number),
            party_id=identifier("party"),
            first_name="Guest",
            last_name=str(number),
            age=30,
        )
        self.insert(connection, "guests", **(values | changes))

    def revise_room(self, connection, revision, **changes):
        values = dict(
            room_reservation_id=identifier("room_reservation"),
            revision=revision,
            min_date=NOW,
            max_date=NOW + 100,
            cancelled=0,
            price_id=identifier("price"),
            price_revision=1,
        )
        self.insert(connection, "room_reservation_revisions", **(values | changes))

    def test_typed_reads_compose_on_one_connection(self):
        with transaction(self.engine) as connection:
            booking = bookings.find_by_id(
                connection, identifier("booking"), hotel_id=identifier("hotel")
            )
            party = parties.find_by_booking_id(
                connection, booking.id, hotel_id=booking.hotel_id
            )
            people = guests.find_all_by_party_id(
                connection, party.id, hotel_id=booking.hotel_id
            )
            allocations = room_reservations.find_all_by_booking_id(
                connection, booking.id, hotel_id=booking.hotel_id
            )
            keys = room_keys.find_all_by_booking_id(
                connection, booking.id, hotel_id=booking.hotel_id, now=NOW
            )
            self.assertIsInstance(booking, BookingRow)
            self.assertIsInstance(people.items[0], GuestRow)
            self.assertEqual(people.model_dump()["items"][0]["id"], identifier("guest"))
            self.assertEqual(booking.created_at, NOW)
            self.assertIsNone(people.items[0].preferred_name)
            self.assertEqual(allocations.items[0].amount_minor, 20_000)
            self.assertEqual(keys.items[0].room_id, allocations.items[0].room_id)
            self.assertTrue(keys.items[0].effective)
            self.assertTrue(connection.in_transaction())
            with self.assertRaises(ValidationError):
                booking.name = "Changed"

    def test_scope_applies_to_single_batch_and_relationship_reads(self):
        with transaction(self.engine) as connection:
            scope = dict(hotel_id=identifier("hotel"))
            for repository, prefix in (
                (bookings, "booking"),
                (parties, "party"),
                (guests, "guest"),
                (room_reservations, "room_reservation"),
            ):
                self.assertIsNone(
                    repository.find_by_id(connection, identifier(prefix, 2), **scope)
                )
                self.assertIsNone(
                    repository.find_by_id(connection, identifier(prefix, 999), **scope)
                )
            self.assertIsNone(
                room_keys.find_by_id(
                    connection, identifier("room_key", 2), now=NOW, **scope
                )
            )
            self.assertIsNone(
                parties.find_by_booking_id(
                    connection, identifier("booking", 2), **scope
                )
            )
            self.assertEqual(
                guests.find_all_by_booking_id(
                    connection, identifier("booking", 2), **scope
                ).items,
                [],
            )
            self.assertEqual(
                guests.find_all_by_party_id(
                    connection, identifier("party", 2), **scope
                ).items,
                [],
            )
            self.assertEqual(
                room_reservations.find_all_by_booking_id(
                    connection, identifier("booking", 2), **scope
                ).items,
                [],
            )
            self.assertEqual(
                room_keys.find_all_by_booking_id(
                    connection, identifier("booking", 2), now=NOW, **scope
                ).items,
                [],
            )
            self.assertEqual(
                room_keys.find_all_by_room_reservation_id(
                    connection, identifier("room_reservation", 2), now=NOW, **scope
                ).items,
                [],
            )
            self.assertEqual(
                [row.id for row in bookings.find_all(connection, **scope).items],
                [identifier("booking")],
            )

    def test_batch_lookup_is_bounded_deduplicated_and_scope_filtered(self):
        with transaction(self.engine) as connection:
            for repository, prefix in ((bookings, "booking"), (guests, "guest")):
                ids = [identifier(prefix, n) for n in (1, 1, 2, 999)]
                result = repository.find_by_ids(
                    connection, ids, hotel_id=identifier("hotel")
                )
                self.assertEqual(list(result), [identifier(prefix)])
                self.assertEqual(
                    repository.find_by_ids(
                        connection, [], hotel_id=identifier("hotel")
                    ),
                    {},
                )
                for invalid in ([identifier(prefix)] * 101, identifier(prefix)):
                    with self.assertRaises(ValueError):
                        repository.find_by_ids(
                            connection, invalid, hotel_id=identifier("hotel")
                        )

    def test_tied_creation_times_use_ids_and_terminal_pages_have_no_cursor(self):
        with transaction(self.engine, write=True) as connection:
            for number in (5, 3, 4):
                self.add_guest(connection, number)
        seen = []
        cursor = None
        with transaction(self.engine) as connection:
            for _ in range(2):
                page = guests.find_all_by_booking_id(
                    connection,
                    identifier("booking"),
                    hotel_id=identifier("hotel"),
                    page=PageRequest(cursor=cursor, limit=2),
                )
                seen.extend(row.id for row in page.items)
                cursor = page.next_cursor
        self.assertEqual(seen, [identifier("guest", n) for n in (1, 3, 4, 5)])
        self.assertIsNone(cursor)

    def test_removal_before_cursor_does_not_skip_and_new_later_rows_are_visible(self):
        with transaction(self.engine, write=True) as connection:
            for number in (3, 4):
                self.add_guest(connection, number)
        with transaction(self.engine) as connection:
            first = guests.find_all_by_party_id(
                connection,
                identifier("party"),
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=2),
            )
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                tables.guests.delete().where(
                    tables.guests.c.id == identifier("guest", 3)
                )
            )
            self.add_guest(connection, 5, created_at=NOW + 1)
        with transaction(self.engine) as connection:
            rest = guests.find_all_by_party_id(
                connection,
                identifier("party"),
                hotel_id=identifier("hotel"),
                page=PageRequest(cursor=first.next_cursor, limit=2),
            )
        self.assertEqual(
            [row.id for row in rest.items],
            [identifier("guest", 4), identifier("guest", 5)],
        )
        self.assertIsNone(rest.next_cursor)

    def test_cursors_reject_other_scopes_filters_and_query_families(self):
        with transaction(self.engine, write=True) as connection:
            self.add_guest(connection, 3)
            page = guests.find_all_by_booking_id(
                connection,
                identifier("booking"),
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=1),
            )
            continuation = PageRequest(cursor=page.next_cursor)
            for booking_id, hotel_id in (
                (identifier("booking", 2), identifier("hotel")),
                (identifier("booking"), identifier("hotel", 2)),
            ):
                with self.assertRaises(InvalidCursor):
                    guests.find_all_by_booking_id(
                        connection, booking_id, hotel_id=hotel_id, page=continuation
                    )
            with self.assertRaises(InvalidCursor):
                guests.find_all_by_party_id(
                    connection,
                    identifier("party"),
                    hotel_id=identifier("hotel"),
                    page=continuation,
                )
            with self.assertRaises(InvalidCursor):
                bookings.find_all(
                    connection, hotel_id=identifier("hotel"), page=continuation
                )

    def test_bad_cursor_and_limits_are_rejected(self):
        for limit in (0, 101, True, "50"):
            with self.assertRaises(ValidationError):
                PageRequest(limit=limit)
        raw = dict(version=2, query="wrong", created_at=NOW, id=identifier("guest"))
        encoded = base64.urlsafe_b64encode(json.dumps(raw).encode()).decode()
        with transaction(self.engine) as connection:
            for cursor in ("!not-base64", "é", "e30", encoded):
                with self.subTest(cursor=cursor), self.assertRaises(InvalidCursor):
                    bookings.find_all(
                        connection,
                        hotel_id=identifier("hotel"),
                        page=PageRequest(cursor=cursor),
                    )

    def test_more_than_one_hundred_keys_use_one_flat_cursor(self):
        with transaction(self.engine, write=True) as connection:
            for number in range(3, 107):
                self.insert(
                    connection,
                    "room_keys",
                    id=identifier("room_key", number),
                    room_reservation_id=identifier("room_reservation"),
                )
        seen = []
        cursor = None
        with transaction(self.engine) as connection:
            for _ in range(3):
                page = room_keys.find_all_by_booking_id(
                    connection,
                    identifier("booking"),
                    hotel_id=identifier("hotel"),
                    now=NOW,
                    page=PageRequest(cursor=cursor, limit=50),
                )
                seen.extend(row.id for row in page.items)
                cursor = page.next_cursor
        self.assertEqual(len(seen), 105)
        self.assertEqual(len(set(seen)), 105)
        self.assertNotIn(identifier("room_key", 2), seen)
        self.assertIsNone(cursor)

    def test_latest_revision_keeps_the_agreed_price_and_one_row_per_allocation(self):
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "price_versions",
                price_id=identifier("price"),
                revision=2,
                amount_minor=99_000,
                currency="GBP",
            )
            self.revise_room(connection, 2, max_date=NOW + 200)
            result = room_reservations.find_all_by_booking_id(
                connection,
                identifier("booking"),
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=1),
            )
            self.assertEqual(len(result.items), 1)
            self.assertIsNone(result.next_cursor)
            row = result.items[0]
            self.assertEqual(
                (row.revision, row.max_date, row.price_revision, row.amount_minor),
                (2, NOW + 200, 1, 20_000),
            )
            self.assertFalse(row.cancelled)
            self.assertTrue(
                room_keys.find_by_id(
                    connection,
                    identifier("room_key"),
                    hotel_id=identifier("hotel"),
                    now=NOW + 150,
                ).effective
            )

    def test_key_access_uses_half_open_dates(self):
        with transaction(self.engine) as connection:
            for now, effective in (
                (NOW - 1, False),
                (NOW, True),
                (NOW + 99, True),
                (NOW + 100, False),
            ):
                row = room_keys.find_by_id(
                    connection,
                    identifier("room_key"),
                    hotel_id=identifier("hotel"),
                    now=now,
                )
                self.assertEqual(row.effective, effective)

    def test_parent_cancellation_changes_access_without_rewriting_key_receipt(self):
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking"),
                revision=2,
                status="BOOKING_STATUS_CANCELLED",
                cancellation_reason="Changed plans",
            )
            booking = bookings.find_by_id(
                connection, identifier("booking"), hotel_id=identifier("hotel")
            )
            self.assertEqual(
                (booking.revision, booking.status), (2, "BOOKING_STATUS_CANCELLED")
            )
            self.assertEqual(
                len(bookings.find_all(connection, hotel_id=identifier("hotel")).items),
                1,
            )
            key = room_keys.find_by_id(
                connection,
                identifier("room_key"),
                hotel_id=identifier("hotel"),
                now=NOW,
            )
            self.assertFalse(key.effective)
            self.assertIsNone(key.deactivated_at)

    def test_revoked_keys_stay_revoked_after_extensions(self):
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                tables.room_keys.update()
                .where(tables.room_keys.c.id == identifier("room_key"))
                .values(deactivated_at=NOW, deactivation_reason="Lost", updated_at=NOW)
            )
            self.revise_room(connection, 2, max_date=NOW + 200)
            key = room_keys.find_by_id(
                connection,
                identifier("room_key"),
                hotel_id=identifier("hotel"),
                now=NOW + 150,
            )
            self.assertFalse(key.effective)
            self.assertEqual(key.deactivation_reason, "Lost")

    def test_cancelled_allocation_invalidates_key_with_confirmed_parent(self):
        with transaction(self.engine, write=True) as connection:
            self.revise_room(
                connection, 2, cancelled=1, cancellation_reason="Room move"
            )
            self.assertTrue(
                room_reservations.find_by_id(
                    connection,
                    identifier("room_reservation"),
                    hotel_id=identifier("hotel"),
                ).cancelled
            )
            self.assertFalse(
                room_keys.find_by_id(
                    connection,
                    identifier("room_key"),
                    hotel_id=identifier("hotel"),
                    now=NOW,
                ).effective
            )

    def test_repositories_use_bound_values_and_leave_transaction_ownership_to_caller(
        self,
    ):
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction(self.engine, write=True) as connection:
                self.add_guest(connection, 3)
                self.assertIsNotNone(
                    guests.find_by_id(
                        connection, identifier("guest", 3), hotel_id=identifier("hotel")
                    )
                )
                self.assertIsNone(
                    bookings.find_by_id(
                        connection, "' OR 1=1 --", hotel_id=identifier("hotel")
                    )
                )
                raise RuntimeError("rollback")
        with transaction(self.engine) as connection:
            self.assertIsNone(
                guests.find_by_id(
                    connection, identifier("guest", 3), hotel_id=identifier("hotel")
                )
            )

    def test_query_metadata_matches_migrated_columns(self):
        for name, table in tables.metadata.tables.items():
            self.assertEqual(
                set(table.c.keys()), set(self.metadata.tables[name].c.keys())
            )
