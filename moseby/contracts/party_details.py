from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from moseby.domain.enums import GuestReferenceStatus as GuestReferenceStatus
from moseby.identifiers import GuestId, PartyDetailId, PartyId

from .common import Contract, IdFilter, Request, SearchRequestPayload


class PartyDetail(Contract):
    """Reported evidence about a party; inferred references do not update guest facts."""

    id: PartyDetailId
    party_id: PartyId
    text: str = Field(min_length=1)
    referenced_guest_ids: list[GuestId] = Field(
        description="Classifier-selected members of this party, validated by the service."
    )
    reference_format_version: Literal[1] = Field(
        default=1, description="Version of the stored reference format."
    )
    reference_status: GuestReferenceStatus
    created_at: AwareDatetime

    @model_validator(mode="after")
    def check_references(self) -> Self:
        if len(set(self.referenced_guest_ids)) != len(self.referenced_guest_ids):
            raise ValueError("referenced_guest_ids must be unique")
        if (
            self.reference_status != GuestReferenceStatus.RESOLVED
            and self.referenced_guest_ids
        ):
            raise ValueError("unresolved references must not assert guest identities")
        return self


class SearchPartyDetailsRequestPayload(SearchRequestPayload):
    party_ids: IdFilter[PartyId]
    guest_ids: IdFilter[GuestId] | None = Field(
        default=None, description="Restrict to details referencing any listed guest."
    )
    text: str | None = Field(
        default=None,
        min_length=1,
        description="Whole-word keywords, all required in any order; case and Latin accents are ignored. Punctuation separates words.",
    )


class SearchPartyDetailsRequest(Request[SearchPartyDetailsRequestPayload]):
    pass


class CreatePartyDetailRequestPayload(Contract):
    party_id: PartyId
    text: str = Field(
        min_length=1,
        description="Record the evidence; the service resolves guest references.",
    )


class CreatePartyDetailRequest(Request[CreatePartyDetailRequestPayload]):
    pass
