"""Activity discovery, private itineraries and complete shared capacity counts."""

from pydantic import ValidationError

from moseby.db import tables
from moseby.db.models.activities import ActivityFilters, ActivityRow
from moseby.db.models.activity_reservations import (
    ActivityReservationFilters,
    ActivityReservationRow,
)
from moseby.db.models.filters import DateRange
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import activities, activity_reservations
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction


class ActivityRepositoryTests(StayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "venues",
                id=identifier("venue"),
                name="Studio",
                capacity=200,
            )
            for number, capacity in ((1, 3), (2, None), (3, 0)):
                self.insert(
                    connection,
                    "activities",
                    id=identifier("activity", number),
                    venue_id=identifier("venue"),
                    title=f"Pottery {number}",
                    type="ACTIVITY_TYPE_POTTERY",
                    description="Make a bowl",
                    min_date=NOW,
                    max_date=NOW + 100,
                    capacity=capacity,
                    min_booking_size=1,
                    max_booking_size=200,
                    minimum_age=0,
                    price_id=identifier("price"),
                    price_unit="ACTIVITY_PRICE_UNIT_PER_GUEST",
                )
            for number in (1, 2):
                self.reserve(connection, number, party=number, guest=number)

    def reserve(self, connection, number, *, party=1, guest=1, activity=1):
        self.insert(
            connection,
            "activity_reservations",
            id=identifier("activity_reservation", number),
            party_id=identifier("party", party),
            guest_id=identifier("guest", guest),
            activity_id=identifier("activity", activity),
        )
        self.revise_reservation(connection, number, 1)

    def revise_reservation(self, connection, number, revision, **changes):
        values = dict(
            activity_reservation_id=identifier("activity_reservation", number),
            revision=revision,
            cancelled=0,
            price_id=identifier("price"),
            price_revision=1,
            price_unit="ACTIVITY_PRICE_UNIT_PER_GUEST",
        )
        self.insert(connection, "activity_reservation_revisions", **(values | changes))

    def test_catalogue_counts_every_hotel_but_itineraries_are_private(self):
        """Activity totals span hotels; reservation reads stay private to each hotel."""
        with transaction(self.engine) as connection:
            event = activities.find_by_id(connection, identifier("activity"))
            self.assertIsInstance(event, ActivityRow)
            self.assertEqual(event.reserved_places, 2)
            self.assertEqual(
                activity_reservations.count_effective_by_activity_id(
                    connection, event.id
                ),
                2,
            )
            page = activity_reservations.find_all(
                connection, hotel_id=identifier("hotel")
            )
            self.assertEqual(len(page.items), 1)
            self.assertIsInstance(page.items[0], ActivityReservationRow)
            self.assertEqual(page.items[0].guest_id, identifier("guest"))
            self.assertEqual(page.items[0].booking_id, identifier("booking"))
            self.assertEqual(page.model_dump()["items"][0]["activity_id"], event.id)
            self.assertIsNone(
                activity_reservations.find_by_id(
                    connection,
                    identifier("activity_reservation", 2),
                    hotel_id=identifier("hotel"),
                )
            )
            for repository_method, prefix in (
                (activity_reservations.find_all_by_guest_id, "guest"),
                (activity_reservations.find_all_by_party_id, "party"),
            ):
                self.assertEqual(
                    repository_method(
                        connection, identifier(prefix, 2), hotel_id=identifier("hotel")
                    ).items,
                    [],
                )

    def test_latest_revision_counts_once_and_keeps_the_agreed_rate(self):
        """Revised reservations count once and retain the agreed price version."""
        with transaction(self.engine, write=True) as connection:
            self.revise_reservation(connection, 1, 2)
            self.insert(
                connection,
                "price_versions",
                price_id=identifier("price"),
                revision=2,
                amount_minor=25_000,
                currency="GBP",
            )
            event = activities.find_by_id(connection, identifier("activity"))
            reservation = activity_reservations.find_by_id(
                connection,
                identifier("activity_reservation"),
                hotel_id=identifier("hotel"),
            )
            self.assertEqual((event.price_revision, event.amount_minor), (2, 25_000))
            self.assertEqual(event.reserved_places, 2)
            self.assertEqual(
                (
                    reservation.revision,
                    reservation.price_revision,
                    reservation.amount_minor,
                ),
                (2, 1, 20_000),
            )

    def test_cancellation_filters_intersect_and_release_capacity(self):
        """Cancelled places are released and excluded from effective-only searches."""
        with transaction(self.engine, write=True) as connection:
            self.revise_reservation(
                connection, 1, 2, cancelled=1, cancellation_reason="Changed plans"
            )
            scope = dict(hotel_id=identifier("hotel"))
            self.assertEqual(
                activity_reservations.find_all(connection, **scope).items, []
            )
            cancelled = activity_reservations.search(
                connection,
                ActivityReservationFilters(effective=False, cancelled=True),
                **scope,
            )
            self.assertEqual(cancelled.items[0].cancellation_reason, "Changed plans")
            self.assertEqual(
                activity_reservations.search(
                    connection, ActivityReservationFilters(cancelled=True), **scope
                ).items,
                [],
            )
            self.assertEqual(
                len(
                    activity_reservations.search(
                        connection, ActivityReservationFilters(effective=None), **scope
                    ).items
                ),
                1,
            )
            self.assertEqual(
                activities.find_by_id(
                    connection, identifier("activity")
                ).reserved_places,
                1,
            )

    def test_booking_cancellation_releases_places_without_rewriting_reservations(self):
        """Booking cancellation releases places without rewriting reservations."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking"),
                revision=2,
                status="BOOKING_STATUS_CANCELLED",
                cancellation_reason="Trip cancelled",
            )
            reservation = activity_reservations.find_by_id(
                connection,
                identifier("activity_reservation"),
                hotel_id=identifier("hotel"),
            )
            self.assertFalse(reservation.effective)
            self.assertFalse(reservation.cancelled)
            self.assertIsNone(reservation.cancellation_reason)
            self.assertEqual(
                activity_reservations.count_effective_by_activity_id(
                    connection, identifier("activity")
                ),
                1,
            )

    def test_completed_bookings_and_past_events_keep_their_itinerary(self):
        """Completing a stay or passing an event's end does not erase its itinerary."""
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "booking_revisions",
                booking_id=identifier("booking"),
                revision=2,
                status="BOOKING_STATUS_COMPLETED",
            )
            connection.execute(
                tables.activities.update()
                .where(tables.activities.c.id == identifier("activity"))
                .values(min_date=NOW - 200, max_date=NOW - 100)
            )
            reservations = activity_reservations.find_all_by_guest_id(
                connection, identifier("guest"), hotel_id=identifier("hotel")
            )
            self.assertTrue(reservations.items[0].effective)
            self.assertEqual(reservations.items[0].max_date, NOW - 100)
            self.assertEqual(
                activities.find_by_id(
                    connection, identifier("activity")
                ).reserved_places,
                2,
            )

    def test_activity_availability_handles_full_empty_and_unlimited_capacity(self):
        """Availability searches distinguish full, empty and unlimited activities."""
        with transaction(self.engine) as connection:
            for needed, expected in ((1, [1, 2]), (2, [2]), (1000, [2])):
                result = activities.search(
                    connection, ActivityFilters(places_required=needed)
                )
                self.assertEqual(
                    [row.id for row in result.items],
                    [identifier("activity", n) for n in expected],
                )
            self.assertIsNone(
                activities.find_by_id(connection, identifier("activity", 2)).capacity
            )
            self.assertEqual(len(activities.find_all(connection).items), 3)

    def test_filters_match_any_id_in_a_list_and_intersect_across_lists(self):
        """IDs within a filter are alternatives; different filters must all match."""
        with transaction(self.engine, write=True) as connection:
            self.add_guest(connection, 3)
            self.reserve(connection, 3, guest=3, activity=2)
            result = activity_reservations.search(
                connection,
                ActivityReservationFilters(
                    guest_ids=[identifier("guest", n) for n in (1, 2, 3)],
                    activity_ids=[identifier("activity", 2)],
                    booking_ids=[identifier("booking")],
                ),
                hotel_id=identifier("hotel"),
            )
            self.assertEqual(
                [row.guest_id for row in result.items], [identifier("guest", 3)]
            )
            result = activities.search(
                connection,
                ActivityFilters(
                    ids=[identifier("activity", n) for n in (1, 2)],
                    venue_ids=[identifier("venue")],
                    types=["ACTIVITY_TYPE_POTTERY"],
                ),
            )
            self.assertEqual(len(result.items), 2)
            self.assertEqual(
                activities.search(
                    connection, ActivityFilters(types=["ACTIVITY_TYPE_TENNIS"])
                ).items,
                [],
            )

    def test_date_filters_exclude_touching_endpoints_for_both_resources(self):
        """Date searches include overlaps and exclude merely touching intervals."""
        with transaction(self.engine) as connection:
            for lower, upper, matches in (
                (NOW - 10, NOW, False),
                (NOW + 100, NOW + 101, False),
                (NOW + 99, NOW + 101, True),
                (NOW, NOW + 100, True),
            ):
                interval = DateRange(min_date=lower, max_date=upper)
                events = activities.search(
                    connection, ActivityFilters(date_range=interval)
                )
                reservations = activity_reservations.search(
                    connection,
                    ActivityReservationFilters(date_range=interval),
                    hotel_id=identifier("hotel"),
                )
                self.assertEqual(bool(events.items), matches)
                self.assertEqual(bool(reservations.items), matches)

    def test_pagination_uses_equivalent_filters_and_rejects_changed_scope(self):
        """Cursors accept equivalent lists but reject changed filters or hotel scope."""
        with transaction(self.engine, write=True) as connection:
            self.reserve(connection, 3, activity=2)
            first = activity_reservations.search(
                connection,
                ActivityReservationFilters(
                    activity_ids=[identifier("activity", n) for n in (2, 1, 1)]
                ),
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=1),
            )
            continuation = PageRequest(cursor=first.next_cursor, limit=1)
            filters = ActivityReservationFilters(
                activity_ids=[identifier("activity", n) for n in (1, 2)]
            )
            rest = activity_reservations.search(
                connection, filters, hotel_id=identifier("hotel"), page=continuation
            )
            self.assertEqual(rest.items[0].id, identifier("activity_reservation", 3))
            self.assertIsNone(rest.next_cursor)
            for changed_filters, hotel in (
                (ActivityReservationFilters(), identifier("hotel")),
                (filters, identifier("hotel", 2)),
            ):
                with self.assertRaises(InvalidCursor):
                    activity_reservations.search(
                        connection, changed_filters, hotel_id=hotel, page=continuation
                    )
            events = activities.find_all(connection, page=PageRequest(limit=1))
            with self.assertRaises(InvalidCursor):
                activities.search(
                    connection,
                    ActivityFilters(places_required=1),
                    page=PageRequest(cursor=events.next_cursor),
                )

    def test_capacity_count_is_complete_even_when_the_itinerary_is_paginated(self):
        """Capacity counts include reservations beyond the current result page."""
        with transaction(self.engine, write=True) as connection:
            for number in range(3, 105):
                self.add_guest(connection, number)
                self.reserve(connection, number, guest=number, activity=2)
            page = activity_reservations.find_all_by_party_id(
                connection,
                identifier("party"),
                hotel_id=identifier("hotel"),
                page=PageRequest(limit=1),
            )
            self.assertEqual(len(page.items), 1)
            self.assertIsNotNone(page.next_cursor)
            self.assertEqual(
                activity_reservations.count_effective_by_activity_id(
                    connection, identifier("activity", 2)
                ),
                102,
            )
            self.assertEqual(
                activities.find_by_id(
                    connection, identifier("activity", 2)
                ).reserved_places,
                102,
            )

    def test_missing_records_and_bounded_batches(self):
        """Missing IDs yield no records, and batches enforce their input limit."""
        with transaction(self.engine) as connection:
            self.assertIsNone(
                activities.find_by_id(connection, identifier("activity", 999))
            )
            self.assertIsNone(
                activity_reservations.find_by_id(
                    connection,
                    identifier("activity_reservation", 999),
                    hotel_id=identifier("hotel"),
                )
            )
            self.assertEqual(
                activity_reservations.count_effective_by_activity_id(
                    connection, identifier("activity", 999)
                ),
                0,
            )
            result = activities.find_by_ids(
                connection, [identifier("activity", n) for n in (1, 1, 999)]
            )
            self.assertEqual(list(result), [identifier("activity")])
            self.assertEqual(activities.find_by_ids(connection, []), {})
            with self.assertRaises(ValueError):
                activities.find_by_ids(connection, [identifier("activity")] * 101)

    def test_invalid_filters_fail_before_querying(self):
        """Invalid search values fail validation before a repository query runs."""
        for values in ([], [identifier("activity")] * 101, [identifier("guest")]):
            with self.assertRaises(ValidationError):
                ActivityFilters(ids=values)
        for size in (0, -1, True):
            with self.assertRaises(ValidationError):
                ActivityFilters(places_required=size)
        for maximum in (NOW, NOW - 1):
            with self.assertRaises(ValidationError):
                DateRange(min_date=NOW, max_date=maximum)
