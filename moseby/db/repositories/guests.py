"""Guest identity and membership lookups for one authorised hotel."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import BookingId, GuestId, HotelId, PartyId

from ..models.guests import GuestRow
from ..pagination import Page, PageRequest, read_page
from ..tables import bookings, guests, parties
from ._queries import unique_ids


def _select(hotel_id: HotelId) -> Select:
    """Follow each guest's party and booking to check which hotel they belong to."""
    return (
        select(guests)
        .join(parties, guests.c.party_id == parties.c.id)
        .join(bookings, parties.c.booking_id == bookings.c.id)
        .where(bookings.c.hotel_id == hotel_id)
    )


def find_by_id(
    connection: Connection, id: GuestId, *, hotel_id: HotelId
) -> GuestRow | None:
    """Fetch a guest in this hotel, or None for a missing or other hotel's ID."""
    row = (
        connection.execute(_select(hotel_id).where(guests.c.id == id))
        .mappings()
        .one_or_none()
    )
    return GuestRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[GuestId],
    *,
    hotel_id: HotelId,
) -> dict[GuestId, GuestRow]:
    """Fetch up to 100 supplied IDs as a dictionary of guests in this hotel.

    Repeated IDs appear once; missing IDs and other hotels' guests are omitted.
    An empty input returns an empty dictionary. More than 100 IDs raises ValueError,
    counting repeats towards the limit.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(_select(hotel_id).where(guests.c.id.in_(ids))).mappings()
    return {row["id"]: GuestRow.model_validate(dict(row)) for row in rows}


def find_all_by_party_id(
    connection: Connection,
    party_id: PartyId,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[GuestRow]:
    """Fetch a page of the party's guests, ordered by creation time, then ID.

    A missing party or one from another hotel returns an empty page. Guests remain
    listed after their booking ends or is cancelled. Pass next_cursor to continue.
    """
    return read_page(
        connection,
        _select(hotel_id).where(guests.c.party_id == party_id),
        table=guests,
        row_type=GuestRow,
        page=page or PageRequest(),
        query="guests.find_all_by_party_id",
        criteria={"hotel_id": hotel_id, "party_id": party_id},
    )


def find_all_by_booking_id(
    connection: Connection,
    booking_id: BookingId,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[GuestRow]:
    """Fetch a page of guests belonging to this booking's party.

    A missing booking or one from another hotel returns an empty page. Include
    cancelled and completed stays; order by creation time, then ID.
    """
    return read_page(
        connection,
        _select(hotel_id).where(parties.c.booking_id == booking_id),
        table=guests,
        row_type=GuestRow,
        page=page or PageRequest(),
        query="guests.find_all_by_booking_id",
        criteria={"hotel_id": hotel_id, "booking_id": booking_id},
    )
