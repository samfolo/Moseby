from pydantic import AwareDatetime

from moseby.identifiers import BookingId, PartyId

from .common import Contract


class Party(Contract):
    """The party for one confirmed booking; guests reference this party."""

    id: PartyId
    booking_id: BookingId
    created_at: AwareDatetime
