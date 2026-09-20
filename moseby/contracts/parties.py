from pydantic import AwareDatetime

from moseby.identifiers import BookingId, PartyId

from .common import Contract, IdFilter, Request, SearchRequestPayload


class Party(Contract):
    """The party for one confirmed booking; guests reference this party."""

    id: PartyId
    booking_id: BookingId
    created_at: AwareDatetime


class SearchPartiesRequestPayload(SearchRequestPayload):
    ids: IdFilter[PartyId] | None = None
    booking_ids: IdFilter[BookingId] | None = None


class SearchPartiesRequest(Request[SearchPartiesRequestPayload]):
    pass
