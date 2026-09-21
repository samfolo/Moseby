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
