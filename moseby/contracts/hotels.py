from pydantic import AwareDatetime, Field

from .addresses import Address
from .common import Contract
from .identifiers import HotelId


class Hotel(Contract):
    """The location owning a booking and its rooms."""

    id: HotelId
    name: str = Field(min_length=1)
    address: Address
    created_at: AwareDatetime
