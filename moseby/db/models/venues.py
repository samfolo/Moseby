from moseby.identifiers import VenueId

from .addresses import AddressRow


class VenueRow(AddressRow):
    """A shared location whose administrative capacity is separate from event capacity."""

    id: VenueId
    name: str
    capacity: int
    created_at: int
    updated_at: int
