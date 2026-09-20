from enum import StrEnum

from pydantic import AwareDatetime, Field

from moseby.identifiers import HotelId, StaffMemberId

from .common import Contract


class StaffRole(StrEnum):
    """Initial demo role; unknown grants no permissions."""

    UNKNOWN = "STAFF_ROLE_UNKNOWN"
    CONCIERGE = "STAFF_ROLE_CONCIERGE"


class StaffMember(Contract):
    """The acting staff identity carried through requests and jobs."""

    id: StaffMemberId
    hotel_id: HotelId
    staff_code: str = Field(
        min_length=1, description="Human-facing code, separate from the resource ID."
    )
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    title: str | None
    role: StaffRole
    created_at: AwareDatetime
