"""Read the single party attached to a booking."""

from sqlalchemy import Connection, Select, select

from moseby.identifiers import BookingId, HotelId, PartyId

from ..models.parties import PartyRow
from ..tables import bookings, parties


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
