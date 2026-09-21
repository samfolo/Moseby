from typing import Self

from pydantic import Field, model_validator

from moseby.domain.enums import ContactPreference
from moseby.identifiers import GuestId, PartyId

from .common import Row, StoredEnum


class GuestRow(Row):
    id: GuestId
    party_id: PartyId
    first_name: str
    last_name: str
    preferred_name: str | None
    age: int
    dietary_requirements: str | None
    phone: str | None
    email: str | None
    contact_preference: StoredEnum[ContactPreference] | None
    created_at: int
    updated_at: int


class GuestValues(Row):
    """Editable guest information; membership stays on the guest identity."""

    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    age: int = Field(ge=0)
    preferred_name: str | None = None
    dietary_requirements: str | None = None
    phone: str | None = None
    email: str | None = None
    contact_preference: ContactPreference | None = None

    @model_validator(mode="after")
    def check_contact(self) -> Self:
        if self.contact_preference == ContactPreference.PHONE and not self.phone:
            raise ValueError("phone preference requires a phone number")
        if self.contact_preference == ContactPreference.EMAIL and not self.email:
            raise ValueError("email preference requires an email address")
        return self


class NewGuest(GuestValues):
    id: GuestId
    party_id: PartyId
