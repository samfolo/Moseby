from moseby.identifiers import TaskId

from .common import Row


class TaskClaimRow(Row):
    """The stored claim for one task; it may have expired since it was written."""

    task_id: TaskId
    created_at: int
    updated_at: int
    token: str
    worker_id: str
    claimed_at: int
    heartbeat_at: int
    expires_at: int
