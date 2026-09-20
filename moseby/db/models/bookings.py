from typing import Literal

from moseby.identifiers import BookingId, HotelId

from .common import Row


class BookingRow(Row):
    """Booking identity with its latest accepted lifecycle revision."""

    id: BookingId
    hotel_id: HotelId
    name: str
    created_at: int
    updated_at: int
    revision: int
    status: Literal[
        "BOOKING_STATUS_CONFIRMED",
        "BOOKING_STATUS_CANCELLED",
        "BOOKING_STATUS_COMPLETED",
    ]
    cancellation_reason: str | None
