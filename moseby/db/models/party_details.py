from typing import Literal

from pydantic import Field

from moseby.domain.enums import GuestReferenceStatus
from moseby.identifiers import GuestId, PartyDetailId, PartyId

from .common import Row, StoredEnum
from .filters import Filters, IdFilter


class PartyDetailRow(Row):
    """Reported evidence and the stored outcome of identifying guests in that text."""

    id: PartyDetailId
    party_id: PartyId
    text: str
    referenced_guest_ids: list[GuestId]
    reference_format_version: Literal[1]
    reference_status: StoredEnum[GuestReferenceStatus]
    created_at: int
    updated_at: int


class PartyDetailFilters(Filters):
    """Search evidence in selected parties, optionally by referenced guest or text."""

    party_ids: IdFilter[PartyId]
    guest_ids: IdFilter[GuestId] | None = None
    text: str | None = Field(default=None, min_length=1)
