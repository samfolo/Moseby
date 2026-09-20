from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field

from .amounts import NonNegativeAmount
from .common import Contract, IdFilter, Request, SearchRequestPayload
from .identifiers import ActivityId, PriceId, VenueId
from .ranges import DateRange, NumberRange

type ActivityTypeCode = Annotated[
    str,
    Field(
        pattern=r"^ACTIVITY_TYPE_[A-Z][A-Z0-9_]*$",
        description="Code from the activity-types table, such as ACTIVITY_TYPE_TENNIS.",
    ),
]


class ActivityPriceUnit(StrEnum):
    """Pricing unit for an activity rate; the demo currently charges per guest."""

    PER_GUEST = "ACTIVITY_PRICE_UNIT_PER_GUEST"


class ActivityPrice(Contract):
    price_id: PriceId
    revision: int = Field(ge=1)
    amount: NonNegativeAmount
    unit: ActivityPriceUnit


class BookingSize(NumberRange):
    """Allowed size of a group request, not the size of each reservation row."""

    min_value: int = Field(ge=1)
    max_value: int = Field(ge=1)


class Activity(Contract):
    """One dated event; reservations and venue sharing do not create recurring templates."""

    id: ActivityId
    venue_id: VenueId
    title: str = Field(min_length=1)
    type: ActivityTypeCode
    description: str
    date_range: DateRange
    capacity: int | None = Field(
        ge=0, description="Null means no activity-level attendance limit."
    )
    booking_size: BookingSize
    minimum_age: int = Field(ge=0)
    price: ActivityPrice
    reserved_places: int = Field(
        ge=0,
        description="Derived count of effective guest reservations, excluding historical revisions.",
    )
    created_at: AwareDatetime


class SearchActivitiesRequestPayload(SearchRequestPayload):
    ids: IdFilter[ActivityId] | None = None
    venue_ids: IdFilter[VenueId] | None = None
    types: Annotated[list[ActivityTypeCode], Field(min_length=1)] | None = None
    date_range: DateRange | None = Field(
        default=None, description="Match events overlapping this interval."
    )
    places_required: int | None = Field(
        default=None,
        ge=1,
        description="Require this many free places; unlimited activities also qualify.",
    )


class SearchActivitiesRequest(Request[SearchActivitiesRequestPayload]):
    pass
