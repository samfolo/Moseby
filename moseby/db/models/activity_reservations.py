from typing import Literal

from moseby.identifiers import (
    ActivityId,
    ActivityReservationId,
    BookingId,
    GuestId,
    HotelId,
    PartyId,
    PriceId,
    VenueId,
)

from .common import Row
from .filters import DateRange, Filters, IdFilter


class ActivityReservationRow(Row):
    """One guest's current reservation, its agreed price and current event times."""

    id: ActivityReservationId
    party_id: PartyId
    guest_id: GuestId
    booking_id: BookingId
    hotel_id: HotelId
    activity_id: ActivityId
    venue_id: VenueId
    title: str
    min_date: int
    max_date: int
    revision: int
    cancelled: bool
    cancellation_reason: str | None
    effective: bool
    price_id: PriceId
    price_revision: int
    price_unit: Literal["ACTIVITY_PRICE_UNIT_PER_GUEST"]
    amount_minor: int
    currency: str
    created_at: int


class ActivityReservationFilters(Filters):
    """Search a hotel's reservations; include effective reservations by default."""

    guest_ids: IdFilter[GuestId] | None = None
    party_ids: IdFilter[PartyId] | None = None
    booking_ids: IdFilter[BookingId] | None = None
    activity_ids: IdFilter[ActivityId] | None = None
    date_range: DateRange | None = None
    effective: bool | None = True
    cancelled: bool | None = None
