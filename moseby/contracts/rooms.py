from enum import StrEnum
from typing import Annotated

from pydantic import Field

from .amounts import NonNegativeAmount
from .common import Contract, PageRequest, Request
from .identifiers import BedId, HotelId, PriceId, RoomId
from .ranges import AmountRange, AvailabilityWindow, NumberRange


class BedType(StrEnum):
    """Supported bed categories; dimensions and sleeping capacity are defined separately."""

    SINGLE = "bed_type_single"
    TWIN = "bed_type_twin"
    DOUBLE = "bed_type_double"
    QUEEN = "bed_type_queen"
    KING = "bed_type_king"


class RoomServiceStatus(StrEnum):
    """Room condition, independent of reservations and temporary holds."""

    IN_SERVICE = "room_service_status_in_service"
    OUT_OF_SERVICE = "room_service_status_out_of_service"


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
    label: str = Field(min_length=1, description="Room number or name as shown to guests.")
    description: str
    tier: str | None
    number_of_bathrooms: int = Field(ge=0)
    service_status: RoomServiceStatus
    beds: list[Bed]
    price: NightlyPrice


class SearchRoomsRequestPayload(PageRequest):
    """Combine supplied filters; omit availability_window to ignore dated availability."""

    hotel_id: HotelId | None = None
    ids: Annotated[list[RoomId], Field(min_length=1)] | None = None
    tier: str | None = None
    bed_types: Annotated[list[BedType], Field(min_length=1)] | None = Field(
        default=None, description="Match rooms containing every listed bed type."
    )
    number_of_beds: NumberRange | None = None
    number_of_bathrooms: NumberRange | None = None
    nightly_amount: AmountRange | None = None
    service_statuses: Annotated[list[RoomServiceStatus], Field(min_length=1)] | None = Field(
        default=None, description="Match any listed service status."
    )
    availability_window: AvailabilityWindow | None = Field(
        default=None,
        description="Require an in-service room with no reservation or live hold overlapping this interval.",
    )


class SearchRoomsRequest(Request[SearchRoomsRequestPayload]):
    pass
