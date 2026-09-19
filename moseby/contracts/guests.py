from enum import StrEnum
from typing import Annotated, Literal, Self, TypedDict

from pydantic import ConfigDict, Field, model_validator, with_config

from .common import Contract, IdFilter, Request, SearchRequestPayload
from .identifiers import BookingId, GuestId, PartyId


class ContactPreference(StrEnum):
    """Preferred contact channel; null on the guest selects all supplied channels."""

    PHONE = "CONTACT_PREFERENCE_PHONE"
    EMAIL = "CONTACT_PREFERENCE_EMAIL"


# Mask entries are exact payload field names.
type UpdateGuestFieldMask = Literal[
    "first_name",
    "last_name",
    "preferred_name",
    "age",
    "dietary_requirements",
    "phone",
    "email",
    "contact_preference",
]


class Guest(Contract):
    """One person during one stay; returning visitors receive new guest IDs."""

    id: GuestId
    party_id: PartyId = Field(description="Party for this stay; immutable membership.")
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    preferred_name: str | None
    age: int = Field(ge=0, description="Recorded age for activity eligibility.")
    dietary_requirements: str | None = Field(
        description="Reported dietary requirements in the staff member's own words."
    )
    phone: str | None
    email: str | None
    contact_preference: ContactPreference | None = Field(
        description="Null uses every supplied channel; a preference requires that contact."
    )

    @model_validator(mode="after")
    def check_contact(self) -> Self:
        contacts = {
            ContactPreference.PHONE: self.phone,
            ContactPreference.EMAIL: self.email,
        }
        if self.contact_preference and not contacts[self.contact_preference]:
            raise ValueError("contact_preference requires the selected contact")
        return self


@with_config(ConfigDict(extra="forbid"))
class UpdateGuestRequestPayload(TypedDict, total=False):
    """Omitted fields stay unchanged; null clears only nullable guest fields."""

    first_name: Annotated[str, Field(min_length=1)]
    last_name: Annotated[str, Field(min_length=1)]
    preferred_name: str | None
    age: Annotated[int, Field(ge=0)]
    dietary_requirements: str | None
    phone: str | None
    email: str | None
    contact_preference: ContactPreference | None


class UpdateGuestRequest(Request[UpdateGuestRequestPayload]):
    update_mask: list[UpdateGuestFieldMask] = Field(
        min_length=1,
        description="Unique field names matching the supplied payload keys exactly.",
    )

    @model_validator(mode="after")
    def check_mask(self) -> Self:
        fields = set(self.update_mask)
        if len(fields) != len(self.update_mask) or fields != set(self.payload):
            raise ValueError("update_mask must name each supplied field exactly once")
        return self


class SearchGuestsRequestPayload(SearchRequestPayload):
    ids: IdFilter[GuestId] | None = None
    party_ids: IdFilter[PartyId] | None = None
    booking_ids: IdFilter[BookingId] | None = Field(
        default=None, description="Resolve through party membership."
    )
    name: str | None = Field(
        default=None,
        min_length=1,
        description="Lexical match across first, last and preferred names.",
    )


class SearchGuestsRequest(Request[SearchGuestsRequestPayload]):
    pass
