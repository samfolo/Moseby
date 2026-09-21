from typing import Annotated

from pydantic import Field

from moseby.domain.enums import BedType as BedType
from moseby.domain.enums import RoomServiceStatus as RoomServiceStatus
from moseby.domain.enums import RoomTier as RoomTier
from moseby.identifiers import BedId, HotelId, PriceId, RoomId

from .amounts import NonNegativeAmount
from .common import Contract, IdFilter, Request, SearchRequestPayload
from .ranges import AmountRange, DateRange, NumberRange


class Bed(Contract):
    id: BedId
    type: BedType


class NightlyPrice(Contract):
    price_id: PriceId = Field(description="Shared price identity across revisions.")
    revision: int = Field(ge=1, description="Version of the displayed nightly rate.")
    amount: NonNegativeAmount


class Room(Contract):
    """Room configuration with its current price; availability depends on dates."""

    id: RoomId
    hotel_id: HotelId
    label: str = Field(
        min_length=1, description="Room number or name as shown to guests."
    )
    description: str
    tier: RoomTier
    number_of_bathrooms: int = Field(ge=0)
    service_status: RoomServiceStatus
    beds: list[Bed]
    price: NightlyPrice


class SearchRoomsRequestPayload(SearchRequestPayload):
    """Combine supplied filters; omit availability_date_range to ignore dated availability."""

    hotel_ids: IdFilter[HotelId] | None = None
    ids: IdFilter[RoomId] | None = None
    tiers: Annotated[list[RoomTier], Field(min_length=1)] | None = Field(
        default=None, description="Match any listed room tier."
    )
    bed_types: Annotated[list[BedType], Field(min_length=1)] | None = Field(
        default=None, description="Match rooms containing every listed bed type."
    )
    number_of_beds: NumberRange | None = None
    number_of_bathrooms: NumberRange | None = None
    nightly_amount: AmountRange | None = None
    service_statuses: Annotated[list[RoomServiceStatus], Field(min_length=1)] | None = (
        Field(default=None, description="Match any listed service status.")
    )
    availability_date_range: DateRange | None = Field(
        default=None,
        description="Require an in-service room with no reservation or live hold overlapping this interval.",
    )


class SearchRoomsRequest(Request[SearchRoomsRequestPayload]):
    pass
