from moseby.domain.enums import BookingStatus
from moseby.identifiers import BookingId, HotelId

from .common import Row, StoredEnum


class BookingRow(Row):
    """Booking identity with its latest accepted lifecycle revision."""

    id: BookingId
    hotel_id: HotelId
    name: str
    created_at: int
    updated_at: int
    revision: int
    status: StoredEnum[BookingStatus]
    cancellation_reason: str | None
