from pydantic import AwareDatetime, Field

from .addresses import Address
from .common import Contract
from .identifiers import VenueId


class Venue(Contract):
    """A shared activity location without a hotel owner."""

    id: VenueId
    name: str = Field(min_length=1)
    address: Address
    capacity: int = Field(
        ge=0,
        description="Administrative capacity; activities enforce their own limits.",
    )
    created_at: AwareDatetime
