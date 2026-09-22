"""Keep work and its child records within the acting staff member's scope."""

from sqlalchemy import ColumnElement, Select, and_, or_, select

from moseby.identifiers import StaffMemberId
from moseby.runtime.enums import JobStatus, RunStatus, TaskStatus

from ..tables import jobs, runs, task_claims, tasks
from ._thread_queries import owned_thread_ids


def job_scope(actor_staff_member_id: StaffMemberId) -> ColumnElement[bool]:
    """Require the actor to own the job and any thread attached to it.

    Jobs without a thread belong to their actor. Services also check the actor's
    current permissions before returning data or allowing work to execute.
    """
    return and_(
        jobs.c.actor_staff_member_id == actor_staff_member_id,
        or_(
            jobs.c.thread_id.is_(None),
            jobs.c.thread_id.in_(owned_thread_ids(actor_staff_member_id)),
        ),
    )


def owned_job_ids(actor_staff_member_id: StaffMemberId) -> Select:
    """Select accessible jobs so their tasks, claims and results share one rule."""
    return select(jobs.c.id).where(job_scope(actor_staff_member_id))


def unfinished_job_ids(actor_staff_member_id: StaffMemberId) -> Select:
    """Select owned jobs that can still accept tasks or outcomes."""
    return owned_job_ids(actor_staff_member_id).where(
        jobs.c.status.in_((JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.WAITING))
    )


def claimable_job_ids(actor_staff_member_id: StaffMemberId, now: int) -> Select:
    """Pause agent-driving work during a wait, while letting its tool jobs proceed.

    A stop request blocks new attempts of either kind. Jobs without a run are
    independent work.
    """
    runnable_runs = (
        select(runs.c.id)
        .where(
            or_(
                runs.c.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)),
                and_(
                    runs.c.status == RunStatus.WAITING, jobs.c.tool_call_id.is_not(None)
                ),
            ),
            runs.c.cancel_requested_at.is_(None),
        )
        .correlate(jobs)
    )
    return owned_job_ids(actor_staff_member_id).where(
        jobs.c.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        jobs.c.updated_at <= now,
        or_(jobs.c.run_id.is_(None), jobs.c.run_id.in_(runnable_runs)),
    )


def claimed_task_ids(
    actor_staff_member_id: StaffMemberId, token: str, now: int
) -> Select:
    """Match a running task's current unexpired token and an unfinished owned job.

    A run may have stopped while external work was in flight. Its task may
    still save evidence; this predicate never wakes or changes that run.
    """
    return (
        select(tasks.c.id)
        .join(task_claims, task_claims.c.task_id == tasks.c.id)
        .where(
            tasks.c.job_id.in_(unfinished_job_ids(actor_staff_member_id)),
            tasks.c.status == TaskStatus.RUNNING,
            tasks.c.updated_at <= now,
            task_claims.c.token == token,
            task_claims.c.heartbeat_at <= now,
            task_claims.c.expires_at > now,
        )
    )
