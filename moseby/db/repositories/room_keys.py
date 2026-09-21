"""Read keys and check their access against the stay at a supplied time."""

from sqlalchemy import Connection, Select, and_, select

from moseby.domain.enums import BookingStatus
from moseby.identifiers import BookingId, HotelId, RoomKeyId, RoomReservationId

from ..models.room_keys import RoomKeyRow
from ..pagination import Page, PageRequest, read_page
from ..tables import (
    booking_revisions,
    bookings,
    room_keys,
    room_reservation_revisions,
    room_reservations,
)
from ._queries import latest_revision


def _select(hotel_id: HotelId, now: int) -> Select:
    """Follow each key to its room reservation and booking to decide access.

    The booking identifies the hotel. Its latest revision tells us whether the
    stay is confirmed; the reservation's latest revision gives its dates and
    cancellation state. Each join picks one row, so each key appears once.

    Access requires an unrevoked key and an uncancelled reservation on a confirmed
    booking. It starts at min_date and ends just before max_date. Return inactive
    keys too, with effective=False, so callers can still inspect them.
    """
    revision = room_reservation_revisions.c
    effective = and_(
        room_keys.c.deactivated_at.is_(None),
        revision.cancelled.is_(False),
        booking_revisions.c.status == BookingStatus.CONFIRMED.value,
        revision.min_date <= now,
        revision.max_date > now,
    )
    return (
        select(
            room_keys,
            room_reservations.c.booking_id,
            room_reservations.c.room_id,
            effective.label("effective"),
        )
        .join(
            room_reservations, room_keys.c.room_reservation_id == room_reservations.c.id
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
    connection: Connection,
    id: RoomKeyId,
    *,
    hotel_id: HotelId,
    now: int,
) -> RoomKeyRow | None:
    """Fetch a key and whether it grants access at now, including inactive keys.

    Supply now as UTC microseconds since the Unix epoch. Return None if the key
    is missing or belongs to another hotel.
    """
    row = (
        connection.execute(_select(hotel_id, now).where(room_keys.c.id == id))
        .mappings()
        .one_or_none()
    )
    return RoomKeyRow.model_validate(dict(row)) if row is not None else None


def find_all_by_booking_id(
    connection: Connection,
    booking_id: BookingId,
    *,
    hotel_id: HotelId,
    now: int,
    page: PageRequest | None = None,
) -> Page[RoomKeyRow]:
    """Fetch one flat page of keys across all rooms reserved by this booking.

    Include inactive keys and check access at now, in UTC microseconds. Order by
    creation time, then ID; a missing or other hotel's booking gives an empty page.
    """
    return read_page(
        connection,
        _select(hotel_id, now).where(room_reservations.c.booking_id == booking_id),
        table=room_keys,
        row_type=RoomKeyRow,
        page=page or PageRequest(),
        query="room_keys.find_all_by_booking_id",
        criteria={"hotel_id": hotel_id, "booking_id": booking_id},
    )


def find_all_by_room_reservation_id(
    connection: Connection,
    room_reservation_id: RoomReservationId,
    *,
    hotel_id: HotelId,
    now: int,
    page: PageRequest | None = None,
) -> Page[RoomKeyRow]:
    """Fetch a page of this reservation's keys, including inactive ones.

    Check access at now, in UTC microseconds, and order by creation time, then ID.
    A missing reservation or one from another hotel returns an empty page.
    """
    return read_page(
        connection,
        _select(hotel_id, now).where(
            room_keys.c.room_reservation_id == room_reservation_id
        ),
        table=room_keys,
        row_type=RoomKeyRow,
        page=page or PageRequest(),
        query="room_keys.find_all_by_room_reservation_id",
        criteria={"hotel_id": hotel_id, "room_reservation_id": room_reservation_id},
    )
