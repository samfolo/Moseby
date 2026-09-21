from pydantic import Field

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


class NewBooking(Row):
    """Identity and name for creating a confirmed booking."""

    id: BookingId
    name: str = Field(min_length=1)
