from typing import Literal

from moseby.identifiers import CompletionId, JobId, ThreadId, ThreadRecordId
from moseby.runtime.models.common import JsonObject

from .common import Row
from .filters import Filters, IdFilter


class CompletionRow(Row):
    """A job's saved result delivery, with a receipt once it enters thread history."""

    id: CompletionId
    created_at: int
    updated_at: int
    job_id: JobId
    thread_id: ThreadId
    format_version: Literal[1]
    payload: JsonObject
    record_id: ThreadRecordId | None
    appended_at: int | None


class CompletionFilters(Filters):
    thread_ids: IdFilter[ThreadId] | None = None
    job_ids: IdFilter[JobId] | None = None
    pending_only: bool = True
