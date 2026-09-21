from typing import Literal, Self

from pydantic import Field, model_validator

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


class NewPartyDetail(Row):
    id: PartyDetailId
    party_id: PartyId
    text: str = Field(min_length=1)


class GuestReferences(Row):
    """Guest references and their resolution status for one party note."""

    status: GuestReferenceStatus
    guest_ids: list[GuestId] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check_references(self) -> Self:
        if len(set(self.guest_ids)) != len(self.guest_ids):
            raise ValueError("guest references must be unique")
        if self.status != GuestReferenceStatus.RESOLVED and self.guest_ids:
            raise ValueError("only resolved references may identify guests")
        return self
