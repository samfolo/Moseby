"""Read stored worker claims through the task's job ownership."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import StaffMemberId, TaskId

from ..models.task_claims import TaskClaimRow
from ..tables import task_claims, tasks
from ._queries import unique_ids
from ._work_queries import owned_job_ids


def _select(actor_staff_member_id: StaffMemberId) -> Select:
    """Follow each claim to its task and job so the same ownership rule applies."""
    return (
        select(task_claims)
        .join(tasks, task_claims.c.task_id == tasks.c.id)
        .where(tasks.c.job_id.in_(owned_job_ids(actor_staff_member_id)))
    )


def find_by_task_id(
    connection: Connection,
    task_id: TaskId,
    *,
    actor_staff_member_id: StaffMemberId,
) -> TaskClaimRow | None:
    """Return the task's stored claim, including one whose lease has expired.

    If there is no claim, or the actor cannot read the job, return None. A saved
    token is internal worker data and is not part of the public job response.
    """
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(task_claims.c.task_id == task_id)
        )
        .mappings()
        .one_or_none()
    )
    return TaskClaimRow.model_validate(dict(row)) if row is not None else None


def find_by_task_ids(
    connection: Connection,
    task_ids: Sequence[TaskId],
    *,
    actor_staff_member_id: StaffMemberId,
) -> dict[TaskId, TaskClaimRow]:
    """Read at most 100 supplied task IDs into a dictionary of their stored claims.

    Repeats count towards the input limit but appear once in the result. Tasks
    with no claim, missing tasks and inaccessible tasks are omitted.
    """
    task_ids = unique_ids(task_ids)
    if not task_ids:
        return {}
    rows = connection.execute(
        _select(actor_staff_member_id).where(task_claims.c.task_id.in_(task_ids))
    ).mappings()
    return {row["task_id"]: TaskClaimRow.model_validate(dict(row)) for row in rows}


def find_unexpired_by_task_id(
    connection: Connection,
    task_id: TaskId,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> TaskClaimRow | None:
    """Return the stored claim only if it has started and has not expired at now.

    At the exact expiry time, return None. This is a read of the lease; a worker's
    protected writes must check the token and expiry again in the write itself.
    """
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(
                task_claims.c.task_id == task_id,
                task_claims.c.claimed_at <= now,
                task_claims.c.expires_at > now,
            )
        )
        .mappings()
        .one_or_none()
    )
    return TaskClaimRow.model_validate(dict(row)) if row is not None else None
