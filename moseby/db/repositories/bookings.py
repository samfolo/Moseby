"""Read confirmed stays and append their lifecycle changes."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, and_, insert, select
from sqlalchemy import update as sql_update

from moseby.domain.enums import BookingStatus
from moseby.identifiers import BookingId, HotelId

from ..errors import WriteConflict
from ..models.bookings import BookingRow, NewBooking
from ..pagination import Page, PageRequest, read_page
from ..tables import booking_revisions, bookings
from ._queries import latest_revision, unique_ids
from ._writes import (
    check_revision,
    require_found,
    require_reason,
    require_write_transaction,
)


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


# Writes


def create(
    connection: Connection, values: NewBooking, *, hotel_id: HotelId, now: int
) -> BookingRow:
    """Start a confirmed booking; the caller adds its party and rooms in this transaction."""
    require_write_transaction(connection)
    with connection.begin_nested():
        connection.execute(
            insert(bookings).values(
                **values.model_dump(), hotel_id=hotel_id, created_at=now, updated_at=now
            )
        )
        connection.execute(
            insert(booking_revisions).values(
                booking_id=values.id,
                revision=1,
                status=BookingStatus.CONFIRMED,
                created_at=now,
            )
        )
        return require_found(find_by_id(connection, values.id, hotel_id=hotel_id))


def _finish(
    connection: Connection,
    id: BookingId,
    status: BookingStatus,
    *,
    expected_revision: int,
    reason: str | None,
    hotel_id: HotelId,
    now: int,
) -> BookingRow:
    require_write_transaction(connection)
    saved = require_found(find_by_id(connection, id, hotel_id=hotel_id))
    check_revision(saved.revision, expected_revision)
    if saved.status != BookingStatus.CONFIRMED or now < saved.updated_at:
        raise WriteConflict(
            "Only a confirmed booking can finish, at a current timestamp"
        )
    with connection.begin_nested():
        connection.execute(
            insert(booking_revisions).values(
                booking_id=id,
                revision=saved.revision + 1,
                status=status,
                cancellation_reason=reason,
                created_at=now,
            )
        )
        connection.execute(
            sql_update(bookings).where(bookings.c.id == id).values(updated_at=now)
        )
        return require_found(find_by_id(connection, id, hotel_id=hotel_id))


def cancel(
    connection: Connection,
    id: BookingId,
    *,
    expected_revision: int,
    reason: str,
    hotel_id: HotelId,
    now: int,
) -> BookingRow:
    """Cancel the stay permanently; derived access and activity capacity change with it."""
    require_reason(reason)
    return _finish(
        connection,
        id,
        BookingStatus.CANCELLED,
        expected_revision=expected_revision,
        reason=reason,
        hotel_id=hotel_id,
        now=now,
    )


def complete(
    connection: Connection,
    id: BookingId,
    *,
    expected_revision: int,
    hotel_id: HotelId,
    now: int,
) -> BookingRow:
    """Complete a stay, disabling room access while preserving activity history."""
    return _finish(
        connection,
        id,
        BookingStatus.COMPLETED,
        expected_revision=expected_revision,
        reason=None,
        hotel_id=hotel_id,
        now=now,
    )
