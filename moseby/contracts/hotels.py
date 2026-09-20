from pydantic import AwareDatetime, Field

from moseby.identifiers import HotelId

from .addresses import Address
from .common import Contract


class Hotel(Contract):
    """The location owning a booking and its rooms."""

    id: HotelId
    name: str = Field(min_length=1)
    address: Address
    created_at: AwareDatetime
