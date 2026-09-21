"""Read and update guest information within one hotel."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, insert, select
from sqlalchemy import update as sql_update

from moseby.domain.enums import BookingStatus
from moseby.identifiers import BookingId, GuestId, HotelId, PartyId

from ..errors import WriteConflict
from ..models.guests import GuestRow, GuestValues, NewGuest
from ..pagination import Page, PageRequest, read_page
from ..tables import bookings, guests, parties
from . import bookings as bookings_repository
from . import parties as parties_repository
from ._queries import unique_ids
from ._stay_queries import check_room_capacity, room_intervals
from ._writes import check_updated_at, require_found, require_write_transaction


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


# Writes


def create(
    connection: Connection, values: NewGuest, *, hotel_id: HotelId, now: int
) -> GuestRow:
    """Add a guest to a confirmed stay; their party cannot be changed later."""
    require_write_transaction(connection)
    party = require_found(
        parties_repository.find_by_id(connection, values.party_id, hotel_id=hotel_id)
    )
    booking = require_found(
        bookings_repository.find_by_id(connection, party.booking_id, hotel_id=hotel_id)
    )
    if booking.status != BookingStatus.CONFIRMED or now < booking.updated_at:
        raise WriteConflict(
            "Guests can only be added to a confirmed booking at a current timestamp"
        )
    with connection.begin_nested():
        connection.execute(
            insert(guests).values(**values.model_dump(), created_at=now, updated_at=now)
        )
        if room_intervals(connection, booking.id):
            check_room_capacity(connection, booking.id)
        return require_found(find_by_id(connection, values.id, hotel_id=hotel_id))


def update_details(
    connection: Connection,
    id: GuestId,
    values: GuestValues,
    *,
    expected_updated_at: int,
    hotel_id: HotelId,
    now: int,
) -> GuestRow:
    """Replace editable fields from a validated snapshot; reject an intervening edit."""
    require_write_transaction(connection)
    saved = require_found(find_by_id(connection, id, hotel_id=hotel_id))
    check_updated_at(saved.updated_at, expected_updated_at, now)
    connection.execute(
        sql_update(guests)
        .where(guests.c.id == id)
        .values(**values.model_dump(), updated_at=now)
    )
    return require_found(find_by_id(connection, id, hotel_id=hotel_id))
