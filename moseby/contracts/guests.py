from enum import StrEnum
from typing import Annotated, Self, TypedDict

from pydantic import ConfigDict, Field, model_validator, with_config

from .common import Contract, Request
from .identifiers import GuestId, PartyId


class ContactPreference(StrEnum):
    """Preferred contact channel; null on the guest selects all supplied channels."""

    PHONE = "contact_preference_phone"
    EMAIL = "contact_preference_email"


class UpdateGuestFieldMask(StrEnum):
    """Allowed update_mask entries; values must match payload field names exactly."""

    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    PREFERRED_NAME = "preferred_name"
    AGE = "age"
    DIETARY_REQUIREMENTS = "dietary_requirements"
    PHONE = "phone"
    EMAIL = "email"
    CONTACT_PREFERENCE = "contact_preference"


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
        contacts = {ContactPreference.PHONE: self.phone, ContactPreference.EMAIL: self.email}
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
        min_length=1, description="Unique field names, matching exactly the supplied payload fields."
    )

    @model_validator(mode="after")
    def check_mask(self) -> Self:
        fields = set(self.update_mask)
        if len(fields) != len(self.update_mask) or fields != set(self.payload):
            raise ValueError("update_mask must name each supplied field exactly once")
        return self

