from moseby.identifiers import RunId, StaffMemberId, ThreadId
from moseby.runtime.enums import RunStatus

from .common import Row, StoredEnum


class RunRow(Row):
    id: RunId
    thread_id: ThreadId
    status: StoredEnum[RunStatus]
    created_at: int
    updated_at: int
    wake_at: int | None
    cancel_requested_at: int | None
    cancel_requested_by_staff_member_id: StaffMemberId | None
    recovery_attempts: int
    finished_at: int | None
