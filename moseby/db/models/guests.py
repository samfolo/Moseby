from typing import Self

from pydantic import Field, model_validator

from moseby.domain.contacts import validate_contact_preference
from moseby.domain.enums import ContactPreference
from moseby.identifiers import BookingId, GuestId, PartyId

from .common import Row, StoredEnum
from .filters import Filters, IdFilter


class GuestFilters(Filters):
    """Find guests by identity, party, booking or words in their names."""

    ids: IdFilter[GuestId] | None = None
    party_ids: IdFilter[PartyId] | None = None
    booking_ids: IdFilter[BookingId] | None = None
    name: str | None = Field(default=None, min_length=1, pattern=r"\S")


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
        validate_contact_preference(
            self.contact_preference, phone=self.phone, email=self.email
        )
        return self


class NewGuest(GuestValues):
    id: GuestId
    party_id: PartyId
