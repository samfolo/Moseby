from moseby.identifiers import BookingId, RoomId, RoomKeyId, RoomReservationId

from .common import Row


class RoomKeyRow(Row):
    """Issued key with its allocation links and access at the requested time."""

    id: RoomKeyId
    room_reservation_id: RoomReservationId
    booking_id: BookingId
    room_id: RoomId
    code: str | None
    deactivated_at: int | None
    deactivation_reason: str | None
    created_at: int
    updated_at: int
    effective: bool
