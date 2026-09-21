"""Room filters select complete matching pages and use current reservation state."""

from pydantic import ValidationError

from moseby.db.models.filters import AmountRange, DateRange, NumberRange
from moseby.db.models.rooms import RoomFilters
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import rooms
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction


class RoomSearchTests(StayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with transaction(self.engine, write=True) as connection:
            for number, tier, amount, currency, bathrooms, in_service, bed_types in (
                (3, "STANDARD", 10_000, "GBP", 1, 1, ["TWIN"]),
                (4, "VIP", 30_000, "GBP", 2, 1, ["KING", "SINGLE"]),
                (5, "VIP", 30_000, "GBP", 2, 0, ["KING", "SINGLE"]),
                (6, "VIP", 90_000, "GBP", 3, 1, ["KING", "KING"]),
                (7, "VIP", 30_000, "USD", 2, 1, ["KING"]),
                (8, "VIP", 35_000, "GBP", 2, 1, []),
            ):
                self.insert(connection, "prices", id=identifier("price", number))
                self.insert(
                    connection,
                    "price_versions",
                    price_id=identifier("price", number),
                    revision=1,
                    amount_minor=amount,
                    currency=currency,
                )
                self.insert(
                    connection,
                    "rooms",
                    id=identifier("room", number),
                    hotel_id=identifier("hotel"),
                    label=str(number),
                    description="",
                    tier=f"ROOM_TIER_{tier}",
                    number_of_bathrooms=bathrooms,
                    in_service=in_service,
                    price_id=identifier("price", number),
                )
                for index, bed_type in enumerate(bed_types):
                    self.insert(
                        connection,
                        "beds",
                        id=identifier("bed", number * 10 + index),
                        room_id=identifier("room", number),
                        type=f"BED_TYPE_{bed_type}",
                    )

    def search_ids(self, connection, **criteria):
        return [
            row.id
            for row in rooms.search(
                connection, RoomFilters(**criteria), hotel_id=identifier("hotel")
            ).items
        ]

    def test_combined_filters_run_before_limit_and_continue_matching_rooms(self):
        """Filters apply before paging, so each page contains matching rooms."""
        filters = RoomFilters(
            tiers=["ROOM_TIER_VIP"],
            nightly_amount=AmountRange(
                currency="GBP", min_value=30_000, max_value=35_000
            ),
            service_statuses=["ROOM_SERVICE_STATUS_IN_SERVICE"],
        )
        with transaction(self.engine) as connection:
            first = rooms.search(
                connection,
                filters,
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=1),
            )
            self.assertEqual([row.id for row in first.items], [identifier("room", 4)])
            self.assertEqual(len(first.items[0].beds), 2)
            rest = rooms.search(
                connection,
                filters,
                hotel_id=identifier("hotel"),
                page=PageRequest(cursor=first.next_cursor, limit=1),
            )
            self.assertEqual([row.id for row in rest.items], [identifier("room", 8)])
            self.assertIsNone(rest.next_cursor)

    def test_prices_use_current_revision_currency_and_inclusive_bounds(self):
        """Price filters use current rates, matching currency and inclusive bounds."""
        with transaction(self.engine, write=True) as connection:
            exact = AmountRange(currency="GBP", min_value=30_000, max_value=30_000)
            self.assertEqual(
                self.search_ids(connection, nightly_amount=exact),
                [identifier("room", n) for n in (4, 5)],
            )
            self.insert(
                connection,
                "price_versions",
                price_id=identifier("price", 4),
                revision=2,
                amount_minor=40_000,
                currency="GBP",
            )
            self.assertEqual(
                self.search_ids(connection, nightly_amount=exact),
                [identifier("room", 5)],
            )
            self.assertEqual(
                self.search_ids(
                    connection,
                    nightly_amount=AmountRange(currency="USD", max_value=30_000),
                ),
                [identifier("room", 7)],
            )

    def test_bed_types_require_every_type_and_counts_count_actual_beds(self):
        """Rooms must contain every requested bed type and meet the bed count."""
        with transaction(self.engine) as connection:
            self.assertEqual(
                self.search_ids(
                    connection,
                    bed_types=["BED_TYPE_KING", "BED_TYPE_SINGLE", "BED_TYPE_KING"],
                ),
                [identifier("room", n) for n in (4, 5)],
            )
            self.assertEqual(
                self.search_ids(
                    connection,
                    bed_types=["BED_TYPE_KING"],
                    number_of_beds=NumberRange(min_value=2, max_value=2),
                ),
                [identifier("room", n) for n in (4, 5, 6)],
            )
            self.assertEqual(
                self.search_ids(
                    connection,
                    number_of_beds=NumberRange(max_value=0),
                ),
                [identifier("room", n) for n in (1, 8)],
            )
            self.assertEqual(
                self.search_ids(
                    connection,
                    number_of_bathrooms=NumberRange(min_value=3),
                ),
                [identifier("room", 6)],
            )

    def test_request_hotel_ids_only_narrow_the_trusted_scope(self):
        """Requested hotel IDs cannot widen the caller's permitted hotel scope."""
        with transaction(self.engine) as connection:
            self.assertEqual(
                self.search_ids(
                    connection,
                    hotel_ids=[identifier("hotel", 2)],
                ),
                [],
            )
            self.assertEqual(
                self.search_ids(
                    connection,
                    hotel_ids=[identifier("hotel", n) for n in (1, 2)],
                    ids=[identifier("room", n) for n in (1, 2, 3)],
                ),
                [identifier("room", n) for n in (1, 3)],
            )

    def test_availability_excludes_overlaps_and_allows_touching_endpoints(self):
        """Overlapping stays block availability; touching endpoints do not."""
        with transaction(self.engine) as connection:
            for lower, upper, available in (
                (NOW - 10, NOW, True),
                (NOW + 100, NOW + 110, True),
                (NOW - 1, NOW + 1, False),
                (NOW + 99, NOW + 101, False),
                (NOW + 1, NOW + 99, False),
                (NOW - 1, NOW + 101, False),
                (NOW, NOW + 100, False),
            ):
                ids = self.search_ids(
                    connection,
                    ids=[identifier("room")],
                    availability_date_range=DateRange(min_date=lower, max_date=upper),
                )
                self.assertEqual(bool(ids), available)
            self.assertIn(identifier("room"), self.search_ids(connection))

    def test_availability_uses_latest_reservation_dates_and_cancellation(self):
        """Availability follows the latest reservation dates and cancellation state."""
        with transaction(self.engine, write=True) as connection:
            interval = DateRange(min_date=NOW + 100, max_date=NOW + 150)
            self.assertIn(
                identifier("room"),
                self.search_ids(connection, availability_date_range=interval),
            )
            self.revise_room(connection, 2, max_date=NOW + 200)
            self.assertNotIn(
                identifier("room"),
                self.search_ids(connection, availability_date_range=interval),
            )
            self.revise_room(
                connection,
                3,
                max_date=NOW + 200,
                cancelled=1,
                cancellation_reason="Moved rooms",
            )
            self.assertIn(
                identifier("room"),
                self.search_ids(connection, availability_date_range=interval),
            )

    def test_cancelled_and_completed_bookings_release_room_capacity(self):
        """Cancelled and completed bookings release their rooms for future searches."""
        for status in ("BOOKING_STATUS_CANCELLED", "BOOKING_STATUS_COMPLETED"):
            with self.subTest(status=status):
                with self.engine.connect() as connection:
                    transaction_handle = connection.begin()
                    try:
                        self.insert(
                            connection,
                            "booking_revisions",
                            booking_id=identifier("booking"),
                            revision=2,
                            status=status,
                            cancellation_reason="Trip cancelled"
                            if status.endswith("CANCELLED")
                            else None,
                        )
                        self.assertIn(
                            identifier("room"),
                            self.search_ids(
                                connection,
                                availability_date_range=DateRange(
                                    min_date=NOW, max_date=NOW + 100
                                ),
                            ),
                        )
                    finally:
                        transaction_handle.rollback()

    def test_service_status_and_availability_filters_intersect(self):
        """Availability requires an in-service room even when its calendar is free."""
        with transaction(self.engine) as connection:
            self.assertEqual(
                self.search_ids(
                    connection,
                    service_statuses=["ROOM_SERVICE_STATUS_OUT_OF_SERVICE"],
                ),
                [identifier("room", 5)],
            )
            self.assertEqual(
                self.search_ids(
                    connection,
                    service_statuses=["ROOM_SERVICE_STATUS_OUT_OF_SERVICE"],
                    availability_date_range=DateRange(min_date=NOW, max_date=NOW + 100),
                ),
                [],
            )
            self.assertEqual(
                len(
                    self.search_ids(
                        connection,
                        service_statuses=[
                            "ROOM_SERVICE_STATUS_OUT_OF_SERVICE",
                            "ROOM_SERVICE_STATUS_IN_SERVICE",
                        ],
                    )
                ),
                7,
            )

    def test_cursor_binds_all_filters_but_ignores_list_order_and_duplicates(self):
        """Cursors accept reordered filter IDs but reject changed criteria."""
        with transaction(self.engine) as connection:
            first = rooms.search(
                connection,
                RoomFilters(tiers=["ROOM_TIER_VIP", "ROOM_TIER_STANDARD"]),
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=1),
            )
            continuation = PageRequest(cursor=first.next_cursor, limit=1)
            rest = rooms.search(
                connection,
                RoomFilters(
                    tiers=["ROOM_TIER_STANDARD", "ROOM_TIER_VIP", "ROOM_TIER_VIP"]
                ),
                hotel_id=identifier("hotel"),
                page=continuation,
            )
            self.assertEqual(rest.items[0].id, identifier("room", 3))
            for filters, hotel_id in (
                (RoomFilters(tiers=["ROOM_TIER_VIP"]), identifier("hotel")),
                (
                    RoomFilters(tiers=["ROOM_TIER_VIP", "ROOM_TIER_STANDARD"]),
                    identifier("hotel", 2),
                ),
            ):
                with self.assertRaises(InvalidCursor):
                    rooms.search(
                        connection, filters, hotel_id=hotel_id, page=continuation
                    )

    def test_invalid_ranges_and_unknown_filter_values_fail_before_queries(self):
        """Invalid ranges and unknown choices fail before a room query is built."""
        for build in (
            lambda: NumberRange(),
            lambda: NumberRange(min_value=3, max_value=2),
            lambda: AmountRange(currency="gbp", max_value=100),
            lambda: RoomFilters(tiers=["VIP"]),
            lambda: RoomFilters(ids=[]),
            lambda: RoomFilters(service_statuses=["AVAILABLE"]),
            lambda: RoomFilters(bed_types=["SOFA"]),
        ):
            with self.assertRaises(ValidationError):
                build()
