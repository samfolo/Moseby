from pydantic import AwareDatetime, Field

from moseby.domain.enums import StaffRole as StaffRole
from moseby.identifiers import HotelId, StaffMemberId

from .common import Contract


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
