"""Read and revise room allocations with pinned nightly rates."""

from sqlalchemy import Connection, Select, and_, insert, select

from moseby.domain.enums import BookingStatus
from moseby.identifiers import BookingId, HotelId, RoomReservationId

from ..errors import WriteConflict
from ..models.room_reservations import (
    NewRoomReservation,
    RoomReservationRow,
    RoomReservationValues,
)
from ..pagination import Page, PageRequest, read_page
from ..tables import (
    bookings,
    price_versions,
    room_reservation_revisions,
    room_reservations,
)
from ..tables import rooms as rooms_table
from . import bookings as bookings_repository
from . import prices as prices_repository
from . import rooms as rooms_repository
from ._queries import latest_revision
from ._room_queries import overlapping_reservation
from ._stay_queries import check_reserved_activities, check_room_capacity
from ._writes import (
    check_history_time,
    check_revision,
    require_found,
    require_reason,
    require_write_transaction,
)


def _select(hotel_id: HotelId) -> Select:
    """Read each reservation's latest dates and the price agreed in that revision.

    The booking supplies the hotel boundary. Each join selects one matching row,
    including the exact price version saved on the reservation.
    """
    revision = room_reservation_revisions.c
    return (
        select(
            room_reservations,
            revision.revision,
            revision.min_date,
            revision.max_date,
            revision.cancelled,
            revision.cancellation_reason,
            revision.price_id,
            revision.price_revision,
            price_versions.c.amount_minor,
            price_versions.c.currency,
        )
        .join(bookings, room_reservations.c.booking_id == bookings.c.id)
        .join(
            room_reservation_revisions,
            and_(
                revision.room_reservation_id == room_reservations.c.id,
                revision.revision
                == latest_revision(
                    room_reservation_revisions,
                    revision.room_reservation_id,
                    room_reservations.c.id,
                ),
            ),
        )
        .join(
            price_versions,
            and_(
                price_versions.c.price_id == revision.price_id,
                price_versions.c.revision == revision.price_revision,
            ),
        )
        .where(bookings.c.hotel_id == hotel_id)
    )


def find_by_id(
    connection: Connection,
    id: RoomReservationId,
    *,
    hotel_id: HotelId,
) -> RoomReservationRow | None:
    """Fetch the latest reservation and its agreed nightly price, even if cancelled.

    Return None if the ID is missing or belongs to another hotel.
    """
    row = (
        connection.execute(_select(hotel_id).where(room_reservations.c.id == id))
        .mappings()
        .one_or_none()
    )
    return RoomReservationRow.model_validate(dict(row)) if row is not None else None


def find_all_by_booking_id(
    connection: Connection,
    booking_id: BookingId,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[RoomReservationRow]:
    """Fetch a page of the booking's room reservations with their agreed prices.

    Include cancelled reservations; order by creation time, then ID. A missing
    booking or one from another hotel returns an empty page.
    """
    return read_page(
        connection,
        _select(hotel_id).where(room_reservations.c.booking_id == booking_id),
        table=room_reservations,
        row_type=RoomReservationRow,
        page=page or PageRequest(),
        query="room_reservations.find_all_by_booking_id",
        criteria={"hotel_id": hotel_id, "booking_id": booking_id},
    )


# Writes


def _require_confirmed(
    connection: Connection, booking_id: BookingId, hotel_id: HotelId, now: int
) -> None:
    """Require a confirmed booking in this hotel and a time at or after its last edit."""
    booking = require_found(
        bookings_repository.find_by_id(connection, booking_id, hotel_id=hotel_id)
    )
    if booking.status != BookingStatus.CONFIRMED or now < booking.updated_at:
        raise WriteConflict(
            "Room changes require a confirmed booking at a current timestamp"
        )


def _check_allocation(
    connection: Connection,
    room_id: str,
    values: RoomReservationValues,
    *,
    hotel_id: HotelId,
    exclude_id: str | None = None,
) -> None:
    """Check the room's hotel, service status, agreed rate and date availability.

    When revising an allocation, exclude its own ID from the overlap check.
    """
    room = require_found(
        rooms_repository.find_by_id(connection, room_id, hotel_id=hotel_id)
    )
    require_found(
        prices_repository.find_by_id_and_revision(
            connection, values.price_id, values.price_revision
        )
    )
    if not room.in_service:
        raise WriteConflict("The room is out of service")
    occupied = connection.scalar(
        select(overlapping_reservation(values.date_range, exclude_id=exclude_id))
        .select_from(rooms_table)
        .where(rooms_table.c.id == room_id)
    )
    if occupied:
        raise WriteConflict("The room is already reserved during those dates")


def create(
    connection: Connection, values: NewRoomReservation, *, hotel_id: HotelId, now: int
) -> RoomReservationRow:
    """Reserve an in-service room after checking overlap under the caller's write lock."""
    require_write_transaction(connection)
    _require_confirmed(connection, values.booking_id, hotel_id, now)
    _check_allocation(connection, values.room_id, values, hotel_id=hotel_id)
    with connection.begin_nested():
        connection.execute(
            insert(room_reservations).values(
                id=values.id,
                booking_id=values.booking_id,
                room_id=values.room_id,
                created_at=now,
            )
        )
        connection.execute(
            insert(room_reservation_revisions).values(
                room_reservation_id=values.id,
                revision=1,
                **values.date_range.model_dump(),
                cancelled=False,
                price_id=values.price_id,
                price_revision=values.price_revision,
                created_at=now,
            )
        )
        return require_found(find_by_id(connection, values.id, hotel_id=hotel_id))


def revise(
    connection: Connection,
    id: RoomReservationId,
    values: RoomReservationValues,
    *,
    expected_revision: int,
    hotel_id: HotelId,
    now: int,
) -> RoomReservationRow:
    """Append accepted dates and rate, rejecting conflicts or activities left outside the stay."""
    require_write_transaction(connection)
    saved = require_found(find_by_id(connection, id, hotel_id=hotel_id))
    check_revision(saved.revision, expected_revision)
    check_history_time(
        connection, room_reservation_revisions, "room_reservation_id", id, now
    )
    _require_confirmed(connection, saved.booking_id, hotel_id, now)
    _check_allocation(
        connection, saved.room_id, values, hotel_id=hotel_id, exclude_id=id
    )
    if saved.cancelled:
        raise WriteConflict("A cancelled room reservation cannot be reinstated")

    # Check the whole stay against the proposed dates; failure rolls back this revision.
    with connection.begin_nested():
        connection.execute(
            insert(room_reservation_revisions).values(
                room_reservation_id=id,
                revision=saved.revision + 1,
                **values.date_range.model_dump(),
                cancelled=False,
                price_id=values.price_id,
                price_revision=values.price_revision,
                created_at=now,
            )
        )
        check_reserved_activities(connection, saved.booking_id)
        check_room_capacity(connection, saved.booking_id)
        return require_found(find_by_id(connection, id, hotel_id=hotel_id))


def cancel(
    connection: Connection,
    id: RoomReservationId,
    *,
    expected_revision: int,
    reason: str,
    hotel_id: HotelId,
    now: int,
) -> RoomReservationRow:
    """Cancel one allocation permanently; its keys stop granting access immediately."""
    require_write_transaction(connection)
    require_reason(reason)
    saved = require_found(find_by_id(connection, id, hotel_id=hotel_id))
    check_revision(saved.revision, expected_revision)
    check_history_time(
        connection, room_reservation_revisions, "room_reservation_id", id, now
    )
    _require_confirmed(connection, saved.booking_id, hotel_id, now)
    if saved.cancelled:
        raise WriteConflict("The room reservation is already cancelled")

    # The remaining allocations must still house the party and cover its activities.
    with connection.begin_nested():
        connection.execute(
            insert(room_reservation_revisions).values(
                room_reservation_id=id,
                revision=saved.revision + 1,
                min_date=saved.min_date,
                max_date=saved.max_date,
                cancelled=True,
                cancellation_reason=reason,
                price_id=saved.price_id,
                price_revision=saved.price_revision,
                created_at=now,
            )
        )
        check_reserved_activities(connection, saved.booking_id)
        check_room_capacity(connection, saved.booking_id)
        return require_found(find_by_id(connection, id, hotel_id=hotel_id))
