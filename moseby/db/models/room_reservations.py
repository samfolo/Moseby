from pydantic import Field

from moseby.identifiers import BookingId, PriceId, RoomId, RoomReservationId

from .common import Row
from .filters import DateRange


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


class RoomReservationValues(Row):
    date_range: DateRange
    price_id: PriceId
    price_revision: int = Field(ge=1)


class NewRoomReservation(RoomReservationValues):
    id: RoomReservationId
    booking_id: BookingId
    room_id: RoomId
