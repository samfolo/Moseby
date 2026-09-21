from pydantic import Field

from moseby.domain.enums import BedType, RoomServiceStatus, RoomTier
from moseby.identifiers import BedId, HotelId, PriceId, RoomId

from .common import Row, StoredEnum
from .filters import AmountRange, DateRange, Filters, IdFilter, NumberRange


class BedRow(Row):
    id: BedId
    room_id: RoomId
    type: StoredEnum[BedType]
    created_at: int
    updated_at: int


class RoomRow(Row):
    """Room configuration with all of its beds and its current catalogue rate."""

    id: RoomId
    hotel_id: HotelId
    label: str
    description: str
    tier: StoredEnum[RoomTier]
    number_of_bathrooms: int
    in_service: bool
    price_id: PriceId
    price_revision: int
    amount_minor: int
    currency: str
    beds: list[BedRow] = Field(default_factory=list)
    created_at: int
    updated_at: int


class RoomFilters(Filters):
    """Combine room filters; bed_types requires every listed type to be present."""

    hotel_ids: IdFilter[HotelId] | None = None
    ids: IdFilter[RoomId] | None = None
    tiers: IdFilter[StoredEnum[RoomTier]] | None = None
    bed_types: IdFilter[StoredEnum[BedType]] | None = None
    number_of_beds: NumberRange | None = None
    number_of_bathrooms: NumberRange | None = None
    nightly_amount: AmountRange | None = None
    service_statuses: IdFilter[StoredEnum[RoomServiceStatus]] | None = None
    availability_date_range: DateRange | None = None
