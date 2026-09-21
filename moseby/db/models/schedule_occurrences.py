from typing import Literal

from moseby.identifiers import JobId, ScheduleId, ScheduleOccurrenceId
from moseby.runtime.models.common import JsonObject

from .common import Row


class ScheduleOccurrenceRow(Row):
    """A recorded firing keeps the revision, input and job accepted at that time."""

    id: ScheduleOccurrenceId
    created_at: int
    schedule_id: ScheduleId
    schedule_revision: int
    due_at: int
    format_version: Literal[1]
    snapshot: JsonObject
    job_id: JobId
