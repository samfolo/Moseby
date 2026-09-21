"""Claim tasks and protect local writes with their current worker leases."""

import secrets
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from sqlalchemy import Connection, Select, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from moseby.identifiers import StaffMemberId, TaskId
from moseby.runtime.enums import JobStatus, TaskStatus

from ..errors import ClaimLost, RepositoryInvariantError, WriteConflict
from ..models.task_claims import TaskClaimRow
from ..tables import jobs, task_claims, tasks
from ._queries import unique_ids
from ._work_queries import claimable_job_ids, claimed_task_ids, owned_job_ids
from ._writes import require_write_transaction

# Reads


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


# Writes


def _claimable_tasks(actor_staff_member_id: StaffMemberId, now: int) -> Select:
    """Select due tasks with no live owner, including abandoned running attempts."""
    live_claims = select(task_claims.c.task_id).where(task_claims.c.expires_at > now)
    return select(tasks.c.id, tasks.c.job_id).where(
        tasks.c.job_id.in_(claimable_job_ids(actor_staff_member_id, now)),
        tasks.c.status.in_((TaskStatus.READY, TaskStatus.RUNNING)),
        tasks.c.available_at <= now,
        tasks.c.updated_at <= now,
        tasks.c.id.not_in(live_claims),
    )


def _claim(
    connection: Connection,
    candidate: Select,
    *,
    actor_staff_member_id: StaffMemberId,
    worker_id: str,
    now: int,
    expires_at: int,
) -> TaskClaimRow | None:
    """Start one attempt and replace its expired claim in the same savepoint."""
    require_write_transaction(connection)
    if not worker_id or expires_at <= now:
        raise ValueError("Supply a worker ID and an expiry after now")
    with connection.begin_nested():
        # Pick eligible work while this transaction holds SQLite's write lock.
        chosen = connection.execute(candidate.limit(1)).mappings().one_or_none()
        if chosen is None:
            return None
        task_id = chosen["id"]

        # Start one attempt and preserve the task's original start time.
        changed = connection.execute(
            update(tasks)
            .where(
                tasks.c.id == task_id,
                tasks.c.id.in_(
                    _claimable_tasks(actor_staff_member_id, now).with_only_columns(
                        tasks.c.id
                    )
                ),
            )
            .values(
                status=TaskStatus.RUNNING.value,
                updated_at=now,
                started_at=func.coalesce(tasks.c.started_at, now),
                attempt_count=tasks.c.attempt_count + 1,
            )
        ).rowcount
        if changed != 1:
            raise WriteConflict("The task can no longer be claimed")

        # Use a fresh token so the previous worker cannot commit after replacement.
        token = secrets.token_urlsafe(32)
        claim_values = dict(
            token=token,
            worker_id=worker_id,
            claimed_at=now,
            heartbeat_at=now,
            expires_at=expires_at,
            updated_at=now,
        )

        # Replace an existing claim only once its deadline has passed.
        saved = connection.execute(
            sqlite_insert(task_claims)
            .values(task_id=task_id, created_at=now, **claim_values)
            .on_conflict_do_update(
                index_elements=[task_claims.c.task_id],
                set_=claim_values,
                where=task_claims.c.expires_at <= now,
            )
            .returning(task_claims.c.task_id)
        ).scalar_one_or_none()
        if saved is None:
            raise WriteConflict("The task already has a live claim")

        # The first claimed task moves its queued job into progress.
        connection.execute(
            update(jobs)
            .where(
                jobs.c.id == chosen["job_id"],
                jobs.c.status == JobStatus.QUEUED,
            )
            .values(status=JobStatus.RUNNING.value, updated_at=now)
        )
        row = find_by_task_id(
            connection, task_id, actor_staff_member_id=actor_staff_member_id
        )
        if row is None:
            raise RepositoryInvariantError("The saved claim could not be read back")
        return row


def claim(
    connection: Connection,
    task_id: TaskId,
    *,
    actor_staff_member_id: StaffMemberId,
    worker_id: str,
    now: int,
    expires_at: int,
) -> TaskClaimRow | None:
    """Claim this due task, or return None if it is unavailable or inaccessible.

    An expired running attempt can be reclaimed with a fresh token. Each claim
    increments the task's attempt count once and starts a queued parent job.
    """
    return _claim(
        connection,
        _claimable_tasks(actor_staff_member_id, now).where(tasks.c.id == task_id),
        actor_staff_member_id=actor_staff_member_id,
        worker_id=worker_id,
        now=now,
        expires_at=expires_at,
    )


def claim_next(
    connection: Connection,
    *,
    actor_staff_member_id: StaffMemberId,
    worker_id: str,
    now: int,
    expires_at: int,
) -> TaskClaimRow | None:
    """Claim the actor's earliest available task, breaking ties by creation time and ID.

    Paused agent work, future tasks and live claims are skipped before selecting one.
    Return None when there is no eligible work. Do external work after committing.
    """
    return _claim(
        connection,
        _claimable_tasks(actor_staff_member_id, now).order_by(
            tasks.c.available_at, tasks.c.created_at, tasks.c.id
        ),
        actor_staff_member_id=actor_staff_member_id,
        worker_id=worker_id,
        now=now,
        expires_at=expires_at,
    )


def renew(
    connection: Connection,
    task_id: TaskId,
    token: str,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
    expires_at: int,
) -> TaskClaimRow | None:
    """Extend this running task's current lease without shortening its deadline.

    Return None for a lost claim, an expired lease, a finished task or a backwards
    clock. At the exact expiry, renewal is too late and requires a new claim.
    """
    require_write_transaction(connection)
    if expires_at <= now:
        raise ValueError("Supply an expiry after now")
    changed = connection.execute(
        update(task_claims)
        .where(
            task_claims.c.task_id == task_id,
            task_claims.c.task_id.in_(
                claimed_task_ids(actor_staff_member_id, token, now)
            ),
            task_claims.c.expires_at <= expires_at,
        )
        .values(heartbeat_at=now, expires_at=expires_at, updated_at=now)
    ).rowcount
    if changed != 1:
        return None
    return find_by_task_id(
        connection, task_id, actor_staff_member_id=actor_staff_member_id
    )


@contextmanager
def guard(
    connection: Connection,
    task_id: TaskId,
    token: str,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> Iterator[None]:
    """Protect a short group of local writes with the task's current lease.

    Call after external work, inside the caller's write transaction. SQLite keeps
    another worker from replacing the claim during these writes. An exception
    rolls back the group even if the caller catches it and commits other work.
    """
    require_write_transaction(connection)
    with connection.begin_nested():
        owned = connection.execute(
            claimed_task_ids(actor_staff_member_id, token, now).where(
                tasks.c.id == task_id
            )
        ).scalar_one_or_none()
        if owned is None:
            raise ClaimLost(
                "The task's claim has expired or no longer belongs to this worker"
            )
        # Run the caller's block here; its exceptions roll back this savepoint.
        yield
