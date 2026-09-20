"""Read current allocations and their pinned nightly rates."""

from sqlalchemy import Connection, Select, and_, select

from moseby.identifiers import BookingId, HotelId, RoomReservationId

from ..models.room_reservations import RoomReservationRow
from ..pagination import Page, PageRequest, read_page
from ..tables import (
    bookings,
    price_versions,
    room_reservation_revisions,
    room_reservations,
)
from ._queries import latest_revision


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
