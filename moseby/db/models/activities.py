from typing import Annotated

from pydantic import Field

from moseby.domain.enums import ActivityPriceUnit
from moseby.identifiers import ActivityId, PriceId, VenueId

from .common import Row, StoredEnum
from .filters import DateRange, Filters, IdFilter

type ActivityTypeCode = Annotated[
    str, Field(pattern=r"^ACTIVITY_TYPE_[A-Z][A-Z0-9_]*$")
]


class ActivityRow(Row):
    """A dated activity, its current catalogue price and its reserved guest places."""

    id: ActivityId
    venue_id: VenueId
    title: str
    type: ActivityTypeCode
    description: str
    min_date: int
    max_date: int
    capacity: int | None
    min_booking_size: int
    max_booking_size: int
    minimum_age: int
    price_id: PriceId
    price_revision: int
    price_unit: StoredEnum[ActivityPriceUnit]
    amount_minor: int
    currency: str
    reserved_places: int
    created_at: int
    updated_at: int


class ActivityFilters(Filters):
    """Search shared activities; date_range matches overlapping event times."""

    ids: IdFilter[ActivityId] | None = None
    venue_ids: IdFilter[VenueId] | None = None
    types: IdFilter[ActivityTypeCode] | None = None
    date_range: DateRange | None = None
    places_required: int | None = Field(default=None, ge=1)
