from moseby.domain.enums import StaffRole
from moseby.identifiers import HotelId, StaffMemberId

from .common import Row, StoredEnum


class StaffMemberRow(Row):
    id: StaffMemberId
    hotel_id: HotelId
    staff_code: str
    first_name: str
    last_name: str
    title: str | None
    role: StoredEnum[StaffRole]
    created_at: int
    updated_at: int
