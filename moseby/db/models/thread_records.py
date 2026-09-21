from typing import Literal

from moseby.identifiers import RunId, StaffMemberId, ThreadId, ThreadRecordId
from moseby.runtime.models.common import JsonObject
from moseby.runtime.models.thread_records import ThreadRecordKind

from .common import Row, StoredEnum
from .filters import Filters, IdFilter


class ThreadRecordRow(Row):
    """The stored envelope; the runtime validates its payload by kind and version."""

    id: ThreadRecordId
    thread_id: ThreadId
    sequence: int
    kind: StoredEnum[ThreadRecordKind]
    format_version: Literal[1]
    created_at: int
    run_id: RunId | None
    actor_staff_member_id: StaffMemberId | None
    source_record_id: ThreadRecordId | None
    tool_call_id: str | None
    payload: JsonObject


class ThreadRecordFilters(Filters):
    thread_id: ThreadId
    ids: IdFilter[ThreadRecordId] | None = None
    run_ids: IdFilter[RunId] | None = None
    kinds: IdFilter[StoredEnum[ThreadRecordKind]] | None = None
