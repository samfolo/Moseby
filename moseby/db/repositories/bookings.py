"""Read bookings within the hotel scope supplied by the service."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, and_, select

from moseby.identifiers import BookingId, HotelId

from ..models.bookings import BookingRow
from ..pagination import Page, PageRequest, read_page
from ..tables import booking_revisions, bookings
from ._queries import latest_revision, unique_ids


def _select(hotel_id: HotelId) -> Select:
    """Join each booking to its latest status and keep it within this hotel."""
    return (
        select(
            bookings,
            booking_revisions.c.revision,
            booking_revisions.c.status,
            booking_revisions.c.cancellation_reason,
        )
        .join(
            booking_revisions,
            and_(
                booking_revisions.c.booking_id == bookings.c.id,
                booking_revisions.c.revision
                == latest_revision(
                    booking_revisions, booking_revisions.c.booking_id, bookings.c.id
                ),
            ),
        )
        .where(bookings.c.hotel_id == hotel_id)
    )


def find_by_id(
    connection: Connection, id: BookingId, *, hotel_id: HotelId
) -> BookingRow | None:
    """Fetch the booking with its latest status, including cancelled bookings.

    Return None if the ID is missing or belongs to another hotel.
    """
    row = (
        connection.execute(_select(hotel_id).where(bookings.c.id == id))
        .mappings()
        .one_or_none()
    )
    return BookingRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[BookingId],
    *,
    hotel_id: HotelId,
) -> dict[BookingId, BookingRow]:
    """Fetch up to 100 supplied IDs as a dictionary of current bookings.

    Repeated IDs appear once; missing IDs and other hotels' bookings are omitted.
    An empty input returns an empty dictionary. More than 100 IDs raises ValueError,
    counting repeats towards the limit.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(hotel_id).where(bookings.c.id.in_(ids))
    ).mappings()
    return {row["id"]: BookingRow.model_validate(dict(row)) for row in rows}


def find_all(
    connection: Connection,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[BookingRow]:
    """Fetch a page of this hotel's bookings, including cancelled and completed stays.

    Order by creation time, then ID. The default page holds up to 50 bookings;
    pass its next_cursor to continue, or stop when that value is None.
    """
    return read_page(
        connection,
        _select(hotel_id),
        table=bookings,
        row_type=BookingRow,
        page=page or PageRequest(),
        query="bookings.find_all",
        criteria={"hotel_id": hotel_id},
    )
