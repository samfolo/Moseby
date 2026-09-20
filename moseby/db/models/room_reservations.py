from moseby.identifiers import BookingId, PriceId, RoomId, RoomReservationId

from .common import Row


class RoomReservationRow(Row):
    """Current allocation with the exact nightly rate agreed for this revision."""

    id: RoomReservationId
    booking_id: BookingId
    room_id: RoomId
    created_at: int
    revision: int
    min_date: int
    max_date: int
    cancelled: bool
    cancellation_reason: str | None
    price_id: PriceId
    price_revision: int
    amount_minor: int
    currency: str
