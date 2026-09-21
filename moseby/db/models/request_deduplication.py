from moseby.identifiers import StaffMemberId
from moseby.runtime.models.common import JsonObject

from .common import Row


class RequestDeduplicationRow(Row):
    """An accepted command; a missing response means no response has been saved yet."""

    actor_staff_member_id: StaffMemberId
    operation: str
    request_id: str
    created_at: int
    updated_at: int
    request: JsonObject
    response: JsonObject | None
