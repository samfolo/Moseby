"""Read and create the single party attached to a booking."""

from sqlalchemy import Connection, Select, insert, select

from moseby.domain.enums import BookingStatus
from moseby.identifiers import BookingId, HotelId, PartyId

from ..errors import WriteConflict
from ..models.parties import PartyRow
from ..tables import bookings, parties
from . import bookings as bookings_repository
from ._writes import require_found, require_write_transaction


def _select(hotel_id: HotelId) -> Select:
    """Use the party's booking to limit results to this hotel."""
    return (
        select(parties)
        .join(bookings, parties.c.booking_id == bookings.c.id)
        .where(bookings.c.hotel_id == hotel_id)
    )


def find_by_id(
    connection: Connection, id: PartyId, *, hotel_id: HotelId
) -> PartyRow | None:
    """Fetch a party in this hotel, or None for a missing or other hotel's ID."""
    row = (
        connection.execute(_select(hotel_id).where(parties.c.id == id))
        .mappings()
        .one_or_none()
    )
    return PartyRow.model_validate(dict(row)) if row is not None else None


def find_by_booking_id(
    connection: Connection,
    booking_id: BookingId,
    *,
    hotel_id: HotelId,
) -> PartyRow | None:
    """Fetch the booking's single party, including for cancelled or completed stays.

    Return None if no party exists or the booking belongs to another hotel.
    """
    row = (
        connection.execute(_select(hotel_id).where(parties.c.booking_id == booking_id))
        .mappings()
        .one_or_none()
    )
    return PartyRow.model_validate(dict(row)) if row is not None else None


# Writes


def create(
    connection: Connection,
    id: PartyId,
    booking_id: BookingId,
    *,
    hotel_id: HotelId,
    now: int,
) -> PartyRow:
    """Create the booking's single party; the database rejects a second party."""
    require_write_transaction(connection)
    booking = require_found(
        bookings_repository.find_by_id(connection, booking_id, hotel_id=hotel_id)
    )
    if booking.status != BookingStatus.CONFIRMED or now < booking.updated_at:
        raise WriteConflict(
            "A party requires a confirmed booking at a current timestamp"
        )
    connection.execute(
        insert(parties).values(id=id, booking_id=booking_id, created_at=now)
    )
    return require_found(find_by_id(connection, id, hotel_id=hotel_id))
