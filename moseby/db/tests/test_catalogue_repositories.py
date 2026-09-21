"""Read shared catalogues and hotel-scoped property information."""

from sqlalchemy import event

from moseby.db import tables
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import (
    activity_types,
    hotels,
    prices,
    rooms,
    staff_members,
    venues,
)
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction


class CatalogueRepositoryTests(StayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with transaction(self.engine, write=True) as connection:
            for number in (1, 2):
                self.insert(
                    connection,
                    "staff_members",
                    id=identifier("staff_member", number),
                    hotel_id=identifier("hotel", number),
                    staff_code=f"STAFF-{number}",
                    first_name="Alex",
                    last_name="Concierge",
                    role="STAFF_ROLE_CONCIERGE",
                )
                self.insert(
                    connection,
                    "venues",
                    id=identifier("venue", number),
                    name=f"Studio {number}",
                    capacity=0 if number == 1 else 20,
                    address_line_1="1 Resort Road",
                    city="Bath",
                    country_code="GB",
                )
            self.insert(
                connection,
                "rooms",
                id=identifier("room", 3),
                hotel_id=identifier("hotel"),
                label="Lily",
                description="Garden view",
                tier="ROOM_TIER_VIP",
                number_of_bathrooms=2,
                in_service=0,
                price_id=identifier("price"),
            )
            for number, room, bed_type in (
                (1, 1, "BED_TYPE_KING"),
                (2, 1, "BED_TYPE_TWIN"),
                (3, 2, "BED_TYPE_SINGLE"),
            ):
                self.insert(
                    connection,
                    "beds",
                    id=identifier("bed", number),
                    room_id=identifier("room", room),
                    type=bed_type,
                )

    def test_hotels_and_staff_are_scoped_while_venues_are_shared(self):
        """Hotel and staff reads stay scoped; venues use the shared catalogue."""
        with transaction(self.engine) as connection:
            scope = dict(hotel_id=identifier("hotel"))
            hotel = hotels.find_by_id(connection, identifier("hotel"), **scope)
            self.assertIsNone(hotel.address_line_1)
            self.assertEqual(hotel.created_at, NOW)
            self.assertEqual(hotels.find_all(connection, **scope).items, [hotel])
            self.assertIsNone(
                hotels.find_by_id(connection, identifier("hotel", 2), **scope)
            )
            staff = staff_members.find_by_id(
                connection, identifier("staff_member"), **scope
            )
            self.assertEqual(staff.staff_code, "STAFF-1")
            self.assertEqual(staff_members.find_all(connection, **scope).items, [staff])
            self.assertIsNone(
                staff_members.find_by_id(
                    connection, identifier("staff_member", 2), **scope
                )
            )
            self.assertEqual(len(venues.find_all(connection).items), 2)
            venue = venues.find_by_id(connection, identifier("venue"))
            self.assertEqual((venue.capacity, venue.country_code), (0, "GB"))
            self.assertIsNone(venue.address_line_2)
            self.assertIsNone(venues.find_by_id(connection, identifier("venue", 999)))
            self.assertEqual(venues.find_by_ids(connection, []), {})
            found = venues.find_by_ids(
                connection, [identifier("venue", n) for n in (1, 1, 999)]
            )
            self.assertEqual(list(found), [identifier("venue")])

    def test_staff_pages_include_unknown_roles_and_reject_other_hotel_cursors(self):
        """Staff paging includes unknown roles and rejects another hotel's cursor."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "staff_members",
                id=identifier("staff_member", 3),
                hotel_id=identifier("hotel"),
                staff_code="NEW",
                first_name="Sam",
                last_name="New",
                role="STAFF_ROLE_UNKNOWN",
            )
            first = staff_members.find_all(
                connection, hotel_id=identifier("hotel"), page=PageRequest(limit=1)
            )
            rest = staff_members.find_all(
                connection,
                hotel_id=identifier("hotel"),
                page=PageRequest(cursor=first.next_cursor, limit=1),
            )
            self.assertEqual(rest.items[0].role, "STAFF_ROLE_UNKNOWN")
            self.assertIsNone(rest.next_cursor)
            with self.assertRaises(InvalidCursor):
                staff_members.find_all(
                    connection,
                    hotel_id=identifier("hotel", 2),
                    page=PageRequest(cursor=first.next_cursor),
                )

    def test_activity_categories_include_new_rows_and_unknown(self):
        """Category reads include added and unknown entries without code changes."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "activity_types",
                code="ACTIVITY_TYPE_SWIMMING",
                name="Swimming",
            )
            result = activity_types.find_all(connection)
            codes = [row.code for row in result]
            self.assertEqual(codes, sorted(codes))
            self.assertIn("ACTIVITY_TYPE_UNKNOWN", codes)
            self.assertIn("ACTIVITY_TYPE_SWIMMING", codes)
            self.assertEqual(
                activity_types.find_by_code(connection, "ACTIVITY_TYPE_SWIMMING").name,
                "Swimming",
            )
            self.assertIsNone(
                activity_types.find_by_code(connection, "ACTIVITY_TYPE_MISSING")
            )

    def test_price_reads_distinguish_current_and_exact_versions(self):
        """New revisions change current prices but leave saved rates readable."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "price_versions",
                price_id=identifier("price"),
                revision=2,
                amount_minor=30_000,
                currency="USD",
                created_at=NOW + 10,
            )
            self.insert(connection, "prices", id=identifier("price", 2))
            current = prices.find_by_id(connection, identifier("price"))
            previous = prices.find_by_id_and_revision(
                connection, identifier("price"), 1
            )
            self.assertEqual((current.amount_minor, current.currency), (30_000, "USD"))
            self.assertEqual((current.created_at, current.revised_at), (NOW, NOW + 10))
            self.assertEqual(
                (previous.amount_minor, previous.currency), (20_000, "GBP")
            )
            self.assertIsNone(
                prices.find_by_id_and_revision(connection, identifier("price"), 3)
            )
            self.assertIsNone(prices.find_by_id(connection, identifier("price", 2)))
            self.assertEqual(prices.find_by_ids(connection, []), {})
            self.assertEqual(
                list(
                    prices.find_by_ids(
                        connection, [identifier("price", n) for n in (1, 1, 2, 999)]
                    )
                ),
                [identifier("price")],
            )

    def test_rooms_include_all_beds_without_multiplying_page_entries(self):
        """Room pages include every bed using one additional query per page."""
        with transaction(self.engine) as connection:
            statements = []

            def record_sql(_conn, _cursor, statement, _parameters, _context, _many):
                statements.append(statement)

            event.listen(connection, "before_cursor_execute", record_sql)
            try:
                first = rooms.find_all(
                    connection, hotel_id=identifier("hotel"), page=PageRequest(limit=1)
                )
            finally:
                event.remove(connection, "before_cursor_execute", record_sql)
            self.assertEqual(len(statements), 2)
            self.assertEqual(len(first.items), 1)
            self.assertEqual(
                [bed.type for bed in first.items[0].beds],
                ["BED_TYPE_KING", "BED_TYPE_TWIN"],
            )
            self.assertEqual(
                first.model_dump()["items"][0]["beds"][0]["id"], identifier("bed")
            )
            rest = rooms.find_all(
                connection,
                hotel_id=identifier("hotel"),
                page=PageRequest(cursor=first.next_cursor, limit=1),
            )
            self.assertIsNone(rest.next_cursor)
            self.assertFalse(rest.items[0].in_service)
            self.assertEqual(rest.items[0].beds, [])
            self.assertEqual(rest.items[0].label, "Lily")

    def test_room_single_and_batch_reads_preserve_scope_and_price_changes(self):
        """Room lookups respect hotel boundaries and return current prices."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "price_versions",
                price_id=identifier("price"),
                revision=2,
                amount_minor=40_000,
                currency="GBP",
            )
            scope = dict(hotel_id=identifier("hotel"))
            row = rooms.find_by_id(connection, identifier("room"), **scope)
            self.assertEqual((row.price_revision, row.amount_minor), (2, 40_000))
            self.assertEqual(len(row.beds), 2)
            self.assertIsNone(
                rooms.find_by_id(connection, identifier("room", 2), **scope)
            )
            self.assertIsNone(
                rooms.find_by_id(connection, identifier("room", 999), **scope)
            )
            result = rooms.find_by_ids(
                connection, [identifier("room", n) for n in (1, 1, 2, 3, 999)], **scope
            )
            self.assertEqual(set(result), {identifier("room"), identifier("room", 3)})
            self.assertEqual(len(result[identifier("room")].beds), 2)
            self.assertEqual(rooms.find_by_ids(connection, [], **scope), {})

    def test_batches_reject_over_the_input_limit(self):
        """A batch exceeding 100 supplied IDs fails before running its lookup."""
        with transaction(self.engine) as connection:
            for repository, prefix, scope in (
                (venues, "venue", {}),
                (prices, "price", {}),
                (rooms, "room", {"hotel_id": identifier("hotel")}),
            ):
                for invalid in ([identifier(prefix)] * 101, identifier(prefix)):
                    with (
                        self.subTest(repository=repository.__name__),
                        self.assertRaises(ValueError),
                    ):
                        repository.find_by_ids(connection, invalid, **scope)

    def test_reads_share_the_callers_rollback_boundary(self):
        """Reads see pending writes that disappear when the caller rolls back."""
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with transaction(self.engine, write=True) as connection:
                connection.execute(
                    tables.rooms.update()
                    .where(tables.rooms.c.id == identifier("room"))
                    .values(label="Changed")
                )
                self.assertEqual(
                    rooms.find_by_id(
                        connection, identifier("room"), hotel_id=identifier("hotel")
                    ).label,
                    "Changed",
                )
                raise RuntimeError("rollback")
        with transaction(self.engine) as connection:
            self.assertEqual(
                rooms.find_by_id(
                    connection, identifier("room"), hotel_id=identifier("hotel")
                ).label,
                "Rose",
            )
