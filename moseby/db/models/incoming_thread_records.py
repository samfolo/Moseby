from typing import Literal

from moseby.identifiers import (
    IncomingThreadRecordId,
    RunId,
    StaffMemberId,
    ThreadId,
    ThreadRecordId,
)
from moseby.runtime.models.common import JsonObject
from moseby.runtime.models.incoming_thread_records import (
    IncomingThreadRecordDeliveryMode,
    IncomingThreadRecordKind,
)

from .common import Row, StoredEnum
from .filters import Filters


class IncomingThreadRecordRow(Row):
    """Saved input with separate delivery, append and cancellation details."""

    id: IncomingThreadRecordId
    thread_id: ThreadId
    sequence: int
    kind: StoredEnum[IncomingThreadRecordKind]
    delivery_mode: StoredEnum[IncomingThreadRecordDeliveryMode]
    target_run_id: RunId | None
    actor_staff_member_id: StaffMemberId
    request_id: str | None
    format_version: Literal[1]
    payload: JsonObject
    created_at: int
    updated_at: int
    record_id: ThreadRecordId | None
    appended_at: int | None
    cancelled_at: int | None
    cancelled_by_staff_member_id: StaffMemberId | None


class IncomingThreadRecordFilters(Filters):
    thread_id: ThreadId
    pending_only: bool = True
