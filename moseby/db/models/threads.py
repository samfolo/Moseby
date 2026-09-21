from typing import Literal

from moseby.identifiers import StaffMemberId, ThreadId
from moseby.permissions import Permission
from moseby.runtime.models.common import JsonObject

from .common import Row


class ThreadRow(Row):
    """The saved thread summary, including the permissions needed to check access."""

    id: ThreadId
    creator_staff_member_id: StaffMemberId
    title: str | None
    created_at: int
    updated_at: int
    archived_at: int | None
    permissions: list[Permission]
    projection_sequence: int
    projection_format_version: Literal[1]
    projection: JsonObject
