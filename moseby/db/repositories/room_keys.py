"""Issue and revoke keys whose access follows their reservation."""

from sqlalchemy import Connection, Select, and_, insert, select
from sqlalchemy import update as sql_update

from moseby.domain.enums import BookingStatus
from moseby.identifiers import BookingId, HotelId, RoomKeyId, RoomReservationId

from ..errors import IdempotencyConflict, WriteConflict
from ..models.room_keys import RoomKeyRow
from ..pagination import Page, PageRequest, read_page
from ..tables import (
    booking_revisions,
    bookings,
    room_keys,
    room_reservation_revisions,
    room_reservations,
)
from . import bookings as bookings_repository
from . import room_reservations as reservations_repository
from ._queries import latest_revision
from ._writes import require_found, require_reason, require_write_transaction


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


# Writes


def issue(
    connection: Connection,
    id: RoomKeyId,
    room_reservation_id: RoomReservationId,
    *,
    hotel_id: HotelId,
    code: str | None = None,
    now: int,
) -> RoomKeyRow:
    """Issue a key for an uncancelled reservation on a confirmed stay, including a future stay."""
    require_write_transaction(connection)
    reservation = require_found(
        reservations_repository.find_by_id(
            connection, room_reservation_id, hotel_id=hotel_id
        )
    )
    booking = require_found(
        bookings_repository.find_by_id(
            connection, reservation.booking_id, hotel_id=hotel_id
        )
    )
    if (
        reservation.cancelled
        or booking.status != BookingStatus.CONFIRMED
        or now < max(reservation.created_at, booking.updated_at)
    ):
        raise WriteConflict("A key requires a valid reservation and booking")
    if now >= reservation.max_date:
        raise WriteConflict("A key cannot be issued after the reservation ends")
    connection.execute(
        insert(room_keys).values(
            id=id,
            room_reservation_id=room_reservation_id,
            code=code,
            created_at=now,
            updated_at=now,
        )
    )
    return require_found(find_by_id(connection, id, hotel_id=hotel_id, now=now))


def deactivate(
    connection: Connection, id: RoomKeyId, *, reason: str, hotel_id: HotelId, now: int
) -> RoomKeyRow:
    """Revoke a key permanently; repeating the same reason returns the saved revocation."""
    require_write_transaction(connection)
    require_reason(reason)
    saved = require_found(find_by_id(connection, id, hotel_id=hotel_id, now=now))
    if saved.deactivated_at is not None:
        if saved.deactivation_reason != reason:
            raise IdempotencyConflict(
                "The key already has a different revocation reason"
            )
        return saved
    if now < saved.updated_at:
        raise WriteConflict("Deactivation cannot precede the key's last change")
    connection.execute(
        sql_update(room_keys)
        .where(room_keys.c.id == id)
        .values(deactivated_at=now, deactivation_reason=reason, updated_at=now)
    )
    return require_found(find_by_id(connection, id, hotel_id=hotel_id, now=now))
