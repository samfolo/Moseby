from pydantic import Field

from moseby.identifiers import StaffMemberId
from moseby.runtime.models.common import JsonObject

from .common import Row


class RequestKey(Row):
    """The staff member, operation and request ID together identify one command."""

    actor_staff_member_id: StaffMemberId
    operation: str = Field(min_length=1)
    request_id: str = Field(min_length=1)


class RequestDeduplicationRow(RequestKey):
    """An accepted command; a missing response means no response has been saved yet."""

    created_at: int
    updated_at: int
    request: JsonObject
    response: JsonObject | None


class RequestAcceptance(Row):
    created: bool
    request: RequestDeduplicationRow
