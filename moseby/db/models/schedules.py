from typing import Literal

from moseby.identifiers import ScheduleId, StaffMemberId, ThreadId
from moseby.runtime.models.common import JsonObject

from .common import Row
from .filters import Filters, IdFilter


class ScheduleRow(Row):
    """The current rule and input used to accept future work."""

    id: ScheduleId
    created_at: int
    updated_at: int
    actor_staff_member_id: StaffMemberId
    revision: int
    enabled: bool
    due_at: int | None
    cron_expression: str | None
    cron_dialect: str | None
    thread_id: ThreadId | None
    handler: str
    format_version: Literal[1]
    input: JsonObject


class ScheduleFilters(Filters):
    ids: IdFilter[ScheduleId] | None = None
    thread_ids: IdFilter[ThreadId] | None = None
    enabled: bool | None = None
