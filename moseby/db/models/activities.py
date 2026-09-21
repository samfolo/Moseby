from typing import Annotated, Self

from pydantic import Field, model_validator

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


class ActivityValues(Row):
    venue_id: VenueId
    title: str = Field(min_length=1)
    type: ActivityTypeCode
    description: str
    date_range: DateRange
    capacity: int | None = Field(ge=0)
    min_booking_size: int = Field(ge=1)
    max_booking_size: int = Field(ge=1)
    minimum_age: int = Field(ge=0)
    price_id: PriceId
    price_unit: ActivityPriceUnit = ActivityPriceUnit.PER_GUEST

    @model_validator(mode="after")
    def check_booking_size(self) -> Self:
        if self.min_booking_size > self.max_booking_size:
            raise ValueError("minimum booking size must not exceed maximum")
        return self


class NewActivity(ActivityValues):
    id: ActivityId
