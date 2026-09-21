"""Compose the repositories for confirmed stays, room moves and reported dietary changes."""

from sqlalchemy import Connection

from moseby.identifiers import GuestId, HotelId, RoomReservationId

from ..errors import WriteConflict
from ..models.guests import GuestRow, GuestValues
from ..models.party_details import NewPartyDetail, PartyDetailRow
from ..models.room_reservations import NewRoomReservation, RoomReservationRow
from ..models.stays import NewStay, Stay
from ..repositories import bookings, guests, parties, party_details, room_reservations
from ..repositories._stay_queries import check_room_capacity
from ..repositories._writes import require_found, require_write_transaction


def create(
    connection: Connection, values: NewStay, *, hotel_id: HotelId, now: int
) -> Stay:
    """Save the booking, party, guests and rooms together after checking capacity.

    Any failure rolls back this group. The caller commits the outer transaction.
    """
    require_write_transaction(connection)
    with connection.begin_nested():
        booking = bookings.create(
            connection, values.booking, hotel_id=hotel_id, now=now
        )
        party = parties.create(
            connection, values.party_id, booking.id, hotel_id=hotel_id, now=now
        )
        people = [
            guests.create(connection, guest, hotel_id=hotel_id, now=now)
            for guest in values.guests
        ]
        rooms = [
            room_reservations.create(connection, room, hotel_id=hotel_id, now=now)
            for room in values.rooms
        ]
        check_room_capacity(connection, booking.id)
        return Stay(booking=booking, party=party, guests=people, rooms=rooms)


def move_room(
    connection: Connection,
    id: RoomReservationId,
    replacement: NewRoomReservation,
    *,
    expected_revision: int,
    reason: str,
    hotel_id: HotelId,
    now: int,
) -> RoomReservationRow:
    """Replace an allocation atomically; old keys remain tied to the cancelled allocation."""
    require_write_transaction(connection)
    old = require_found(room_reservations.find_by_id(connection, id, hotel_id=hotel_id))
    if replacement.booking_id != old.booking_id or replacement.room_id == old.room_id:
        raise WriteConflict("A room move requires another room on the same booking")
    with connection.begin_nested():
        saved = room_reservations.create(
            connection, replacement, hotel_id=hotel_id, now=now
        )
        room_reservations.cancel(
            connection,
            id,
            expected_revision=expected_revision,
            reason=reason,
            hotel_id=hotel_id,
            now=now,
        )
        return saved


def record_dietary_change(
    connection: Connection,
    id: GuestId,
    requirements: str | None,
    evidence: NewPartyDetail,
    *,
    expected_updated_at: int,
    hotel_id: HotelId,
    now: int,
) -> tuple[GuestRow, PartyDetailRow]:
    """Save a reported dietary change and its original evidence together."""
    require_write_transaction(connection)
    saved = require_found(guests.find_by_id(connection, id, hotel_id=hotel_id))
    if evidence.party_id != saved.party_id:
        raise WriteConflict("The evidence must belong to this guest's party")
    values = GuestValues.model_validate(
        {field: getattr(saved, field) for field in GuestValues.model_fields}
        | {"dietary_requirements": requirements}
    )
    with connection.begin_nested():
        guest = guests.update_details(
            connection,
            id,
            values,
            expected_updated_at=expected_updated_at,
            hotel_id=hotel_id,
            now=now,
        )
        detail = party_details.create(connection, evidence, hotel_id=hotel_id, now=now)
        return guest, detail
