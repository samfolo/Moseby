"""Exercise domain writes through the same transactions that services will use."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from moseby.db.errors import ActivityAlreadyReserved, IdempotencyConflict, WriteConflict
from moseby.db.models.activities import ActivityValues, NewActivity
from moseby.db.models.activity_reservations import ActivityAttendee, ReserveActivity
from moseby.db.models.bookings import NewBooking
from moseby.db.models.filters import DateRange
from moseby.db.models.guests import GuestValues, NewGuest
from moseby.db.models.party_details import GuestReferences, NewPartyDetail
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.models.room_reservations import NewRoomReservation, RoomReservationValues
from moseby.db.models.rooms import RoomFilters
from moseby.db.models.stays import NewStay
from moseby.db.operations import commands, stays
from moseby.db.repositories import (
    activities,
    activity_reservations,
    bookings,
    guests,
    parties,
    party_details,
    request_deduplication,
    room_keys,
    room_reservations,
    rooms,
)
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction
from moseby.domain.enums import (
    BedType,
    BookingStatus,
    ContactPreference,
    GuestReferenceStatus,
    RoomTier,
    StaffRole,
)


class DomainMutationTests(StayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.scope = {"hotel_id": identifier("hotel")}
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "staff_members",
                id=identifier("staff_member"),
                hotel_id=identifier("hotel"),
                staff_code="CONCIERGE",
                first_name="Sam",
                last_name="Staff",
                role=StaffRole.CONCIERGE,
            )
            self.insert(
                connection,
                "rooms",
                id=identifier("room", 3),
                hotel_id=identifier("hotel"),
                label="Willow",
                description="",
                tier=RoomTier.STANDARD,
                number_of_bathrooms=1,
                in_service=1,
                price_id=identifier("price"),
            )
            for number in (1, 2, 3):
                self.insert(
                    connection,
                    "beds",
                    id=identifier("bed", number),
                    room_id=identifier("room", number),
                    type=BedType.KING,
                )
            self.insert(
                connection, "venues", id=identifier("venue"), name="Studio", capacity=10
            )
            activities.create(connection, self.activity(), now=NOW)

    def activity(self, number=1, **changes):
        return NewActivity.model_validate(
            dict(
                id=identifier("activity", number),
                venue_id=identifier("venue"),
                title="Pottery",
                type="ACTIVITY_TYPE_POTTERY",
                description="Learn to throw a pot",
                date_range=DateRange(min_date=NOW + 20, max_date=NOW + 40),
                capacity=2,
                min_booking_size=1,
                max_booking_size=4,
                minimum_age=10,
                price_id=identifier("price"),
            )
            | changes
        )

    def reserve(self, connection, number=1, *, activity=1, guest=1, now=NOW + 1):
        return activity_reservations.reserve(
            connection,
            ReserveActivity(
                activity_id=identifier("activity", activity),
                attendees=[
                    ActivityAttendee(
                        id=identifier("activity_reservation", number),
                        guest_id=identifier("guest", guest),
                    )
                ],
            ),
            **self.scope,
            now=now,
        )[0]

    def allocation(self, number=3, *, booking=1, room=3, start=NOW, end=NOW + 100):
        return NewRoomReservation(
            id=identifier("room_reservation", number),
            booking_id=identifier("booking", booking),
            room_id=identifier("room", room),
            date_range=DateRange(min_date=start, max_date=end),
            price_id=identifier("price"),
            price_revision=1,
        )

    def guest_values(self, saved, **changes):
        return GuestValues.model_validate(
            {key: getattr(saved, key) for key in GuestValues.model_fields} | changes
        )

    def activity_values(self, source=None, **changes):
        source = source or self.activity()
        return ActivityValues.model_validate(
            source.model_dump(exclude={"id"}) | changes
        )

    def test_confirmed_stay_is_saved_as_one_group_and_replayed_by_command(self):
        """When the same command is retried, it returns the stay without adding another party or guest."""
        new = NewStay(
            booking=NewBooking(id=identifier("booking", 3), name="New stay"),
            party_id=identifier("party", 3),
            guests=[
                NewGuest(
                    id=identifier("guest", 3),
                    party_id=identifier("party", 3),
                    first_name="Alex",
                    last_name="Guest",
                    age=25,
                )
            ],
            rooms=[self.allocation(booking=3)],
        )
        key = RequestKey(
            actor_staff_member_id=identifier("staff_member"),
            operation="create_stay",
            request_id="create-1",
        )
        request = {
            "hotel_id": identifier("hotel"),
            "payload": new.model_dump(mode="json"),
        }
        with transaction(self.engine, write=True) as connection:

            def action():
                return stays.create(connection, new, **self.scope, now=NOW).model_dump(
                    mode="json"
                )

            first = commands.execute(connection, key, request, action, now=NOW)
            second = commands.execute(connection, key, request, action, now=NOW + 1)
            self.assertEqual(first, second)
            self.assertEqual(first["booking"]["status"], BookingStatus.CONFIRMED)
            self.assertEqual(
                parties.find_by_booking_id(
                    connection, identifier("booking", 3), **self.scope
                ).id,
                identifier("party", 3),
            )
            with self.assertRaises(IdempotencyConflict):
                commands.execute(
                    connection, key, {"different": True}, action, now=NOW + 1
                )

    def test_failed_stay_creation_rolls_back_identity_party_and_command(self):
        """When the requested room is taken, catching the error leaves no partial booking or receipt."""
        new = NewStay(
            booking=NewBooking(id=identifier("booking", 3), name="New stay"),
            party_id=identifier("party", 3),
            guests=[
                NewGuest(
                    id=identifier("guest", 3),
                    party_id=identifier("party", 3),
                    first_name="Alex",
                    last_name="Guest",
                    age=25,
                )
            ],
            rooms=[self.allocation(booking=3, room=1)],
        )
        key = RequestKey(
            actor_staff_member_id=identifier("staff_member"),
            operation="create_stay",
            request_id="bad-stay",
        )
        with transaction(self.engine, write=True) as connection:
            with self.assertRaises(WriteConflict):
                commands.execute(
                    connection,
                    key,
                    {},
                    lambda: stays.create(
                        connection, new, **self.scope, now=NOW
                    ).model_dump(mode="json"),
                    now=NOW,
                )
            self.assertIsNone(
                bookings.find_by_id(connection, new.booking.id, **self.scope)
            )
            self.assertIsNone(
                parties.find_by_id(connection, new.party_id, **self.scope)
            )
            self.assertIsNone(
                request_deduplication.find_by_operation_and_request_id(
                    connection,
                    key.operation,
                    key.request_id,
                    actor_staff_member_id=key.actor_staff_member_id,
                )
            )

    def test_guest_edits_validate_contact_and_reject_stale_snapshots(self):
        """When another edit wins first, an old snapshot cannot overwrite it or change membership."""
        with transaction(self.engine, write=True) as connection:
            saved = guests.find_by_id(connection, identifier("guest"), **self.scope)
            values = self.guest_values(
                saved, phone="123", contact_preference=ContactPreference.PHONE
            )
            changed = guests.update_details(
                connection,
                saved.id,
                values,
                expected_updated_at=NOW,
                **self.scope,
                now=NOW + 1,
            )
            self.assertEqual(changed.phone, "123")
            with self.assertRaises(WriteConflict):
                guests.update_details(
                    connection,
                    saved.id,
                    values,
                    expected_updated_at=NOW,
                    **self.scope,
                    now=NOW + 2,
                )
            with self.assertRaises(ValidationError):
                self.guest_values(changed, phone=None)
            with self.assertRaises(ValidationError):
                GuestValues.model_validate(
                    values.model_dump() | {"party_id": identifier("party", 2)}
                )

    def test_guest_addition_checks_room_capacity_and_party_ownership(self):
        """A second guest fits the king bed, but a third guest cannot be added to that stay."""
        with transaction(self.engine, write=True) as connection:
            guest = NewGuest(
                id=identifier("guest", 3),
                party_id=identifier("party"),
                first_name="Alex",
                last_name="Guest",
                age=25,
            )
            guests.create(connection, guest, **self.scope, now=NOW)
            with self.assertRaises(WriteConflict):
                guests.create(
                    connection,
                    guest.model_copy(update={"id": identifier("guest", 4)}),
                    **self.scope,
                    now=NOW,
                )
            self.assertIsNone(
                guests.find_by_id(connection, identifier("guest", 4), **self.scope)
            )
            with self.assertRaises(WriteConflict):
                guests.create(
                    connection,
                    guest.model_copy(
                        update={
                            "id": identifier("guest", 5),
                            "party_id": identifier("party", 2),
                        }
                    ),
                    **self.scope,
                    now=NOW,
                )
            with self.assertRaises(IntegrityError):
                parties.create(
                    connection,
                    identifier("party", 9),
                    identifier("booking"),
                    **self.scope,
                    now=NOW,
                )

    def test_evidence_references_are_pending_until_settled(self):
        """When reference resolution fails, the note remains saved; every supplied guest must belong to its party."""
        with transaction(self.engine, write=True) as connection:
            note = party_details.create(
                connection,
                NewPartyDetail(
                    id=identifier("party_detail"),
                    party_id=identifier("party"),
                    text="Dan dislikes peanuts",
                ),
                **self.scope,
                now=NOW,
            )
            self.assertEqual(note.reference_status, GuestReferenceStatus.PENDING)
            with self.assertRaises(WriteConflict):
                party_details.save_references(
                    connection,
                    note.id,
                    GuestReferences(
                        status=GuestReferenceStatus.RESOLVED,
                        guest_ids=[identifier("guest", 2)],
                    ),
                    expected_updated_at=NOW,
                    **self.scope,
                    now=NOW + 1,
                )
            failed = party_details.save_references(
                connection,
                note.id,
                GuestReferences(status=GuestReferenceStatus.FAILED),
                expected_updated_at=NOW,
                **self.scope,
                now=NOW + 1,
            )
            self.assertEqual(failed.text, note.text)
            self.assertEqual(failed.referenced_guest_ids, [])
            with self.assertRaises(WriteConflict):
                party_details.save_references(
                    connection,
                    note.id,
                    GuestReferences(status=GuestReferenceStatus.RESOLVED),
                    expected_updated_at=NOW + 1,
                    **self.scope,
                    now=NOW + 2,
                )

    def test_dietary_change_and_evidence_rollback_together(self):
        """If the evidence cannot be saved, the reported dietary field stays unchanged."""
        note = NewPartyDetail(
            id=identifier("party_detail"),
            party_id=identifier("party"),
            text="Dan says no peanuts",
        )
        with transaction(self.engine, write=True) as connection:
            with patch(
                "moseby.db.operations.stays.party_details.create",
                side_effect=RuntimeError("write failed"),
            ):
                with self.assertRaises(RuntimeError):
                    stays.record_dietary_change(
                        connection,
                        identifier("guest"),
                        "No peanuts",
                        note,
                        expected_updated_at=NOW,
                        **self.scope,
                        now=NOW + 1,
                    )
            self.assertIsNone(
                guests.find_by_id(
                    connection, identifier("guest"), **self.scope
                ).dietary_requirements
            )
            guest, saved = stays.record_dietary_change(
                connection,
                identifier("guest"),
                "No peanuts",
                note,
                expected_updated_at=NOW,
                **self.scope,
                now=NOW + 1,
            )
            self.assertEqual(guest.dietary_requirements, "No peanuts")
            self.assertEqual(saved.reference_status, GuestReferenceStatus.PENDING)

    def test_room_move_revokes_old_access_and_failure_keeps_original(self):
        """A room move keeps history and invalidates old keys; a failed move leaves the old room intact."""
        with transaction(self.engine, write=True) as connection:
            with self.assertRaises(WriteConflict):
                stays.move_room(
                    connection,
                    identifier("room_reservation"),
                    self.allocation(room=2),
                    expected_revision=1,
                    reason="Move",
                    **self.scope,
                    now=NOW + 1,
                )
            self.assertTrue(
                room_keys.find_by_id(
                    connection, identifier("room_key"), **self.scope, now=NOW + 1
                ).effective
            )
            replacement = stays.move_room(
                connection,
                identifier("room_reservation"),
                self.allocation(),
                expected_revision=1,
                reason="Move",
                **self.scope,
                now=NOW + 1,
            )
            self.assertEqual(replacement.room_id, identifier("room", 3))
            self.assertFalse(
                room_keys.find_by_id(
                    connection, identifier("room_key"), **self.scope, now=NOW + 1
                ).effective
            )
            self.assertTrue(
                room_reservations.find_by_id(
                    connection, identifier("room_reservation"), **self.scope
                ).cancelled
            )

    def test_extension_moves_key_expiry_and_rejects_stale_or_conflicting_revision(self):
        """Extending a reservation extends its keys, while a stale amendment changes nothing."""
        with transaction(self.engine, write=True) as connection:
            values = RoomReservationValues(
                date_range=DateRange(min_date=NOW, max_date=NOW + 200),
                price_id=identifier("price"),
                price_revision=1,
            )
            saved = room_reservations.revise(
                connection,
                identifier("room_reservation"),
                values,
                expected_revision=1,
                **self.scope,
                now=NOW + 1,
            )
            self.assertEqual(saved.revision, 2)
            self.assertTrue(
                room_keys.find_by_id(
                    connection, identifier("room_key"), **self.scope, now=NOW + 150
                ).effective
            )
            with self.assertRaises(WriteConflict):
                room_reservations.revise(
                    connection,
                    saved.id,
                    values,
                    expected_revision=1,
                    **self.scope,
                    now=NOW + 2,
                )
            with self.assertRaises(WriteConflict):
                room_reservations.revise(
                    connection,
                    saved.id,
                    values,
                    expected_revision=2,
                    **self.scope,
                    now=NOW,
                )

    def test_activity_group_checks_age_duplicates_capacity_and_price(self):
        """A reservation pins its price and rejects a second effective place for the same guest."""
        with transaction(self.engine, write=True) as connection:
            saved = self.reserve(connection)
            self.insert(
                connection,
                "price_versions",
                price_id=identifier("price"),
                revision=2,
                amount_minor=50_000,
                currency="GBP",
            )
            self.assertEqual(
                activity_reservations.find_by_id(
                    connection, saved.id, **self.scope
                ).amount_minor,
                20_000,
            )
            with self.assertRaises(WriteConflict):
                self.reserve(connection, 3)
            child = NewGuest(
                id=identifier("guest", 3),
                party_id=identifier("party"),
                first_name="Child",
                last_name="Guest",
                age=5,
            )
            guests.create(connection, child, **self.scope, now=NOW + 2)
            with self.assertRaises(WriteConflict):
                self.reserve(connection, 4, guest=3, now=NOW + 3)
            with self.assertRaises(WriteConflict):
                self.reserve(connection, 5, guest=2)

    def test_duplicate_error_identifies_every_requested_guest_already_reserved(self):
        """When a full event already has both guests, the error identifies both saved places."""
        with transaction(self.engine, write=True) as connection:
            guests.create(
                connection,
                NewGuest(
                    id=identifier("guest", 3),
                    party_id=identifier("party"),
                    first_name="Alex",
                    last_name="Guest",
                    age=25,
                ),
                **self.scope,
                now=NOW,
            )
            first = self.reserve(connection)
            second = self.reserve(connection, 3, guest=3)
            request = ReserveActivity(
                activity_id=identifier("activity"),
                attendees=[
                    ActivityAttendee(
                        id=identifier("activity_reservation", 4),
                        guest_id=first.guest_id,
                    ),
                    ActivityAttendee(
                        id=identifier("activity_reservation", 5),
                        guest_id=second.guest_id,
                    ),
                ],
            )
            with self.assertRaises(ActivityAlreadyReserved) as raised:
                activity_reservations.reserve(
                    connection, request, **self.scope, now=NOW + 2
                )
            conflict = raised.exception
            self.assertEqual(conflict.code, "ACTIVITY_ALREADY_RESERVED")
            self.assertEqual(conflict.activity_id, request.activity_id)
            self.assertEqual(
                conflict.reservations_by_guest,
                {first.guest_id: first.id, second.guest_id: second.id},
            )
            self.assertIsNone(
                activity_reservations.find_by_id(
                    connection, request.attendees[0].id, **self.scope
                )
            )

    def test_duplicate_error_checks_guest_scope_before_disclosing_reservations(self):
        """A request naming another hotel's guest gets no details of that guest's reservation."""
        with transaction(self.engine, write=True) as connection:
            activity_reservations.reserve(
                connection,
                ReserveActivity(
                    activity_id=identifier("activity"),
                    attendees=[
                        ActivityAttendee(
                            id=identifier("activity_reservation", 2),
                            guest_id=identifier("guest", 2),
                        )
                    ],
                ),
                hotel_id=identifier("hotel", 2),
                now=NOW + 1,
            )
            with self.assertRaises(WriteConflict) as raised:
                self.reserve(connection, 3, guest=2, now=NOW + 2)
            self.assertNotIsInstance(raised.exception, ActivityAlreadyReserved)
            self.assertNotIn(identifier("guest", 2), str(raised.exception))

    def test_group_failure_rolls_back_preceding_attendees(self):
        """If a later reservation ID conflicts, no earlier member of that group is booked."""
        with transaction(self.engine, write=True) as connection:
            self.reserve(connection)
            guests.create(
                connection,
                NewGuest(
                    id=identifier("guest", 3),
                    party_id=identifier("party"),
                    first_name="Alex",
                    last_name="Guest",
                    age=25,
                ),
                **self.scope,
                now=NOW,
            )
            activities.create(connection, self.activity(2), now=NOW)
            request = ReserveActivity(
                activity_id=identifier("activity", 2),
                attendees=[
                    ActivityAttendee(
                        id=identifier("activity_reservation", 3),
                        guest_id=identifier("guest", 3),
                    ),
                    ActivityAttendee(
                        id=identifier("activity_reservation"),
                        guest_id=identifier("guest"),
                    ),
                ],
            )
            with self.assertRaises(IntegrityError):
                activity_reservations.reserve(
                    connection, request, **self.scope, now=NOW + 1
                )
            self.assertEqual(
                activity_reservations.count_effective_by_activity_id(
                    connection, identifier("activity", 2)
                ),
                0,
            )

    def test_stay_coverage_and_guest_overlap_have_distinct_rules(self):
        """Overlapping activities are allowed, but an activity outside the stay is rejected."""
        with transaction(self.engine, write=True) as connection:
            self.reserve(connection)
            activities.create(connection, self.activity(2), now=NOW)
            self.reserve(connection, 2, activity=2)
            activities.create(
                connection,
                self.activity(
                    3, date_range=DateRange(min_date=NOW + 90, max_date=NOW + 110)
                ),
                now=NOW,
            )
            with self.assertRaises(WriteConflict):
                self.reserve(connection, 3, activity=3)
            with self.assertRaises(WriteConflict):
                room_reservations.revise(
                    connection,
                    identifier("room_reservation"),
                    RoomReservationValues(
                        date_range=DateRange(min_date=NOW, max_date=NOW + 30),
                        price_id=identifier("price"),
                        price_revision=1,
                    ),
                    expected_revision=1,
                    **self.scope,
                    now=NOW + 2,
                )
            self.assertEqual(
                room_reservations.find_by_id(
                    connection, identifier("room_reservation"), **self.scope
                ).max_date,
                NOW + 100,
            )

    def test_booking_cancellation_releases_places_and_completion_preserves_them(self):
        """Cancelling a booking releases its places and keys without deleting any reservation history."""
        with transaction(self.engine, write=True) as connection:
            reservation = self.reserve(connection)
            bookings.cancel(
                connection,
                identifier("booking"),
                expected_revision=1,
                reason="Plans changed",
                **self.scope,
                now=NOW + 2,
            )
            self.assertFalse(
                activity_reservations.find_by_id(
                    connection, reservation.id, **self.scope
                ).effective
            )
            self.assertEqual(
                activity_reservations.count_effective_by_activity_id(
                    connection, identifier("activity")
                ),
                0,
            )
            self.assertFalse(
                room_keys.find_by_id(
                    connection, identifier("room_key"), **self.scope, now=NOW + 3
                ).effective
            )
            with self.assertRaises(WriteConflict):
                bookings.complete(
                    connection,
                    identifier("booking"),
                    expected_revision=2,
                    **self.scope,
                    now=NOW + 3,
                )

    def test_completion_preserves_activity_reservations(self):
        """Completing a stay retains its activity history while removing room access."""
        with transaction(self.engine, write=True) as connection:
            reservation = self.reserve(connection)
            bookings.complete(
                connection,
                identifier("booking"),
                expected_revision=1,
                **self.scope,
                now=NOW + 2,
            )
            self.assertTrue(
                activity_reservations.find_by_id(
                    connection, reservation.id, **self.scope
                ).effective
            )
            self.assertFalse(
                room_keys.find_by_id(
                    connection, identifier("room_key"), **self.scope, now=NOW + 3
                ).effective
            )

    def test_activity_cancellation_is_terminal_and_rebooking_requires_new_identity(
        self,
    ):
        """Cancelling releases the place; booking it again creates a new reservation."""
        with transaction(self.engine, write=True) as connection:
            saved = self.reserve(connection)
            activity_reservations.cancel(
                connection,
                saved.id,
                expected_revision=1,
                reason="Changed plans",
                **self.scope,
                now=NOW + 2,
            )
            with self.assertRaises(WriteConflict):
                activity_reservations.cancel(
                    connection,
                    saved.id,
                    expected_revision=2,
                    reason="Again",
                    **self.scope,
                    now=NOW + 3,
                )
            replacement = self.reserve(connection, 2, now=NOW + 3)
            self.assertTrue(replacement.effective)

    def test_activity_edits_protect_existing_attendees(self):
        """Edits cannot reduce capacity below attendance, raise age beyond a guest, or silently move an event."""
        with transaction(self.engine, write=True) as connection:
            self.reserve(connection)
            for changes in (
                {"capacity": 0},
                {"minimum_age": 40},
                {"date_range": DateRange(min_date=NOW + 25, max_date=NOW + 45)},
            ):
                with self.assertRaises(WriteConflict):
                    activities.update_details(
                        connection,
                        identifier("activity"),
                        self.activity_values(**changes),
                        expected_updated_at=NOW,
                        now=NOW + 2,
                    )
            changed = activities.update_details(
                connection,
                identifier("activity"),
                self.activity_values(capacity=3),
                expected_updated_at=NOW,
                now=NOW + 2,
            )
            self.assertEqual(changed.capacity, 3)

    def test_room_keys_are_scoped_and_revocation_is_permanent(self):
        """A key follows its reservation, and repeating its revocation does not create another change."""
        with transaction(self.engine, write=True) as connection:
            with self.assertRaises(WriteConflict):
                room_keys.issue(
                    connection,
                    identifier("room_key", 3),
                    identifier("room_reservation", 2),
                    **self.scope,
                    now=NOW + 1,
                )
            key = room_keys.issue(
                connection,
                identifier("room_key", 3),
                identifier("room_reservation"),
                **self.scope,
                now=NOW + 1,
            )
            self.assertTrue(key.effective)
            first = room_keys.deactivate(
                connection, key.id, reason="Lost", **self.scope, now=NOW + 2
            )
            again = room_keys.deactivate(
                connection, key.id, reason="Lost", **self.scope, now=NOW + 3
            )
            self.assertEqual(first.deactivated_at, again.deactivated_at)
            self.assertFalse(again.effective)
            with self.assertRaises(IdempotencyConflict):
                room_keys.deactivate(
                    connection, key.id, reason="Different", **self.scope, now=NOW + 3
                )

    def test_two_connections_cannot_take_the_last_activity_place(self):
        """When two workers compete for the last place, exactly one reservation commits."""
        with transaction(self.engine, write=True) as connection:
            activities.update_details(
                connection,
                identifier("activity"),
                self.activity_values(capacity=1),
                expected_updated_at=NOW,
                now=NOW + 1,
            )
            guests.create(
                connection,
                NewGuest(
                    id=identifier("guest", 3),
                    party_id=identifier("party"),
                    first_name="Alex",
                    last_name="Guest",
                    age=25,
                ),
                **self.scope,
                now=NOW + 1,
            )
        ready = Barrier(2)

        def book(number):
            ready.wait()
            try:
                with transaction(self.engine, write=True) as connection:
                    self.reserve(connection, number, guest=number, now=NOW + 2)
                return True
            except WriteConflict:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(book, [1, 3])), [False, True])
        with transaction(self.engine) as connection:
            self.assertEqual(
                activity_reservations.count_effective_by_activity_id(
                    connection, identifier("activity")
                ),
                1,
            )

    def test_two_connections_cannot_reserve_the_same_room(self):
        """Concurrent room reservations are serialized around the availability check and insert."""
        ready = Barrier(2)

        def reserve(number):
            ready.wait()
            try:
                with transaction(self.engine, write=True) as connection:
                    room_reservations.create(
                        connection, self.allocation(number), **self.scope, now=NOW + 1
                    )
                return True
            except WriteConflict:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(reserve, [3, 4])), [False, True])

    def test_touching_room_reservations_share_search_overlap_rule(self):
        """A reservation ending at the next one's arrival leaves the room available for that arrival."""
        with transaction(self.engine, write=True) as connection:
            values = self.allocation(room=1, start=NOW + 100, end=NOW + 200)
            page = rooms.search(
                connection,
                RoomFilters(
                    ids=[identifier("room")], availability_date_range=values.date_range
                ),
                **self.scope,
            )
            self.assertEqual(len(page.items), 1)
            saved = room_reservations.create(
                connection, values, **self.scope, now=NOW + 1
            )
            self.assertEqual(saved.min_date, NOW + 100)
            with self.assertRaises(WriteConflict):
                room_reservations.create(
                    connection,
                    self.allocation(4, room=1, start=NOW + 99),
                    **self.scope,
                    now=NOW + 2,
                )

    def test_writes_require_a_write_transaction(self):
        """A read transaction cannot be used to admit a new reservation."""
        with transaction(self.engine) as connection:
            with self.assertRaises(RuntimeError):
                self.reserve(connection)
