from typing import Literal

from moseby.identifiers import JobId, TaskId
from moseby.runtime.enums import TaskStatus
from moseby.runtime.models.common import JsonObject

from .common import Row, StoredEnum
from .filters import Filters, IdFilter


class TaskRow(Row):
    """One saved task, including retry progress and the most recent outcome."""

    id: TaskId
    created_at: int
    updated_at: int
    job_id: JobId
    step_key: str
    handler: str
    format_version: Literal[1]
    input: JsonObject
    status: StoredEnum[TaskStatus]
    attempt_count: int
    available_at: int
    started_at: int | None
    finished_at: int | None
    result: JsonObject | None
    error: JsonObject | None


class TaskFilters(Filters):
    job_id: JobId
    ids: IdFilter[TaskId] | None = None
    statuses: IdFilter[StoredEnum[TaskStatus]] | None = None
