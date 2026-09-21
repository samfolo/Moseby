from typing import Literal

from moseby.identifiers import JobId, RunId, StaffMemberId, ThreadId, ThreadRecordId
from moseby.runtime.enums import JobStatus
from moseby.runtime.models.common import JsonObject

from .common import Row, StoredEnum
from .filters import Filters, IdFilter


class JobRow(Row):
    """The saved operation and outcome, with its internal handler and request identity."""

    id: JobId
    created_at: int
    updated_at: int
    actor_staff_member_id: StaffMemberId
    operation: str
    request_id: str
    thread_id: ThreadId | None
    run_id: RunId | None
    source_record_id: ThreadRecordId | None
    tool_call_id: str | None
    handler: str
    phase: str
    format_version: Literal[1]
    input: JsonObject
    status: StoredEnum[JobStatus]
    result: JsonObject | None
    error: JsonObject | None
    finished_at: int | None


class JobFilters(Filters):
    ids: IdFilter[JobId] | None = None
    thread_ids: IdFilter[ThreadId] | None = None
    run_ids: IdFilter[RunId] | None = None
    statuses: IdFilter[StoredEnum[JobStatus]] | None = None
