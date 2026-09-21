"""Create tasks and save attempts under their current worker claims."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, delete, insert, null, select, update

from moseby.identifiers import JobId, StaffMemberId, TaskId
from moseby.runtime.enums import TaskStatus
from moseby.runtime.models.common import JsonObject

from ..errors import ClaimLost, RepositoryInvariantError, WriteConflict
from ..models.tasks import NewTask, TaskFilters, TaskRow
from ..pagination import Page, PageRequest, read_page
from ..tables import jobs, tasks
from ..tables import task_claims as claims_table
from . import task_claims
from ._queries import unique_ids
from ._work_queries import claimed_task_ids, owned_job_ids, unfinished_job_ids
from ._writes import encode_canonical_json, require_write_transaction

# Reads


def _select(actor_staff_member_id: StaffMemberId) -> Select:
    """Decode the saved JSON fields and apply job ownership before returning rows."""
    return select(
        tasks.c.id,
        tasks.c.created_at,
        tasks.c.updated_at,
        tasks.c.job_id,
        tasks.c.step_key,
        tasks.c.handler,
        tasks.c.format_version,
        tasks.c.input_json.label("input"),
        tasks.c.status,
        tasks.c.attempt_count,
        tasks.c.available_at,
        tasks.c.started_at,
        tasks.c.finished_at,
        tasks.c.result_json.label("result"),
        tasks.c.error_json.label("error"),
    ).where(tasks.c.job_id.in_(owned_job_ids(actor_staff_member_id)))


def find_by_id(
    connection: Connection,
    id: TaskId,
    *,
    actor_staff_member_id: StaffMemberId,
) -> TaskRow | None:
    """Return this task if the actor owns its job and any linked thread.

    If the ID is missing or falls outside that scope, return None.
    """
    row = (
        connection.execute(_select(actor_staff_member_id).where(tasks.c.id == id))
        .mappings()
        .one_or_none()
    )
    return TaskRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[TaskId],
    *,
    actor_staff_member_id: StaffMemberId,
) -> dict[TaskId, TaskRow]:
    """Look up at most 100 supplied IDs, counting repeats towards the limit.

    Each matching ID appears once. Missing or inaccessible rows are omitted;
    an empty list gives an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(actor_staff_member_id).where(tasks.c.id.in_(ids))
    ).mappings()
    return {row["id"]: TaskRow.model_validate(dict(row)) for row in rows}


def find_by_job_id_and_step_key(
    connection: Connection,
    job_id: JobId,
    step_key: str,
    *,
    actor_staff_member_id: StaffMemberId,
) -> TaskRow | None:
    """Find the job's named task, including its retry count and saved outcome.

    Retries retain the same task identity. If the step is missing or the actor
    cannot read its job, return None.
    """
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(
                tasks.c.job_id == job_id,
                tasks.c.step_key == step_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    return TaskRow.model_validate(dict(row)) if row is not None else None


def find_all_by_job_id(
    connection: Connection,
    job_id: JobId,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[TaskRow]:
    """List the job's tasks in creation order, including waiting and finished work.

    This reads saved progress. Whether a worker may claim a task also depends on
    its claim, availability time and the runtime's execution rules.
    """
    return search(
        connection,
        TaskFilters(job_id=job_id),
        actor_staff_member_id=actor_staff_member_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: TaskFilters,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[TaskRow]:
    """Read one job's matching tasks, applying ID and status filters before paging.

    If the job is missing or inaccessible, the page is empty. Each task appears
    once even when it has been attempted several times.
    """
    statement = _select(actor_staff_member_id).where(tasks.c.job_id == filters.job_id)
    for column, values in (
        (tasks.c.id, filters.ids),
        (tasks.c.status, filters.statuses),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    return read_page(
        connection,
        statement,
        table=tasks,
        row_type=TaskRow,
        page=page or PageRequest(),
        query="tasks.search",
        criteria={
            "actor_staff_member_id": actor_staff_member_id,
            "filters": filters.model_dump_json(),
        },
    )


# Writes


def create(
    connection: Connection,
    values: NewTask,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> TaskRow:
    """Add a ready task to an unfinished owned job on the caller's transaction.

    The database rejects duplicate IDs or step keys. Creating initial tasks and
    accepting their job belong to one transaction; no method commits on its own.
    """
    require_write_transaction(connection)
    encode_canonical_json(values.input)
    if (
        connection.execute(
            unfinished_job_ids(actor_staff_member_id).where(
                jobs.c.id == values.job_id,
                jobs.c.updated_at <= now,
            )
        ).scalar_one_or_none()
        is None
    ):
        raise WriteConflict(
            "The parent job is missing, inaccessible or already finished"
        )
    fields = values.model_dump(exclude={"input"})
    connection.execute(
        insert(tasks).values(
            **fields,
            input_json=values.input,
            created_at=now,
            updated_at=now,
            status=TaskStatus.READY.value,
            attempt_count=0,
        )
    )
    row = find_by_id(connection, values.id, actor_staff_member_id=actor_staff_member_id)
    if row is None:
        raise RepositoryInvariantError("The saved task could not be read back")
    return row


def _finish(
    connection: Connection,
    task_id: TaskId,
    token: str,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
    status: TaskStatus,
    result: JsonObject | None,
    error: JsonObject | None,
) -> TaskRow:
    """Save one terminal attempt outcome while the worker still owns its claim."""
    require_write_transaction(connection)
    if result is not None:
        encode_canonical_json(result)
    if error is not None:
        encode_canonical_json(error)
    changed = connection.execute(
        update(tasks)
        .where(
            tasks.c.id == task_id,
            tasks.c.id.in_(claimed_task_ids(actor_staff_member_id, token, now)),
        )
        .values(
            status=status.value,
            result_json=result if result is not None else null(),
            error_json=error if error is not None else null(),
            finished_at=now,
            updated_at=now,
        )
    ).rowcount
    if changed != 1:
        raise ClaimLost("The task no longer has this live claim")
    row = find_by_id(connection, task_id, actor_staff_member_id=actor_staff_member_id)
    if row is None:
        raise RepositoryInvariantError("The saved task could not be read back")
    return row


def succeed(
    connection: Connection,
    task_id: TaskId,
    token: str,
    result: JsonObject,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> TaskRow:
    """Save this task's successful result, rejecting expired or replaced claims.

    The caller combines domain changes and parent-job progress in the same
    guarded transaction. Finishing a task alone does not finish or resume its job.
    """
    return _finish(
        connection,
        task_id,
        token,
        actor_staff_member_id=actor_staff_member_id,
        now=now,
        status=TaskStatus.SUCCEEDED,
        result=result,
        error=None,
    )


def fail(
    connection: Connection,
    task_id: TaskId,
    token: str,
    error: JsonObject,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> TaskRow:
    """Keep the final error when this attempt should not be retried.

    The task becomes terminal. The job handler decides what this failure means
    for its other tasks and saves that decision on the same transaction.
    """
    return _finish(
        connection,
        task_id,
        token,
        actor_staff_member_id=actor_staff_member_id,
        now=now,
        status=TaskStatus.FAILED,
        result=None,
        error=error,
    )


def retry(
    connection: Connection,
    task_id: TaskId,
    token: str,
    error: JsonObject,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
    available_at: int,
) -> TaskRow:
    """Release this claim and make the same task ready at the chosen retry time.

    Keep its input, first start time and last error. The next successful claim
    increments the attempt count; the caller chooses backoff and retry limits.
    """
    require_write_transaction(connection)
    encode_canonical_json(error)
    if available_at < now:
        raise ValueError("The retry time must be at or after now")
    with task_claims.guard(
        connection, task_id, token, actor_staff_member_id=actor_staff_member_id, now=now
    ):
        changed = connection.execute(
            update(tasks)
            .where(
                tasks.c.id == task_id,
                tasks.c.id.in_(claimed_task_ids(actor_staff_member_id, token, now)),
            )
            .values(
                status=TaskStatus.READY.value,
                error_json=error,
                result_json=null(),
                available_at=available_at,
                updated_at=now,
            )
        ).rowcount
        if changed != 1:
            raise ClaimLost("The task no longer has this live claim")
        connection.execute(
            delete(claims_table).where(
                claims_table.c.task_id == task_id, claims_table.c.token == token
            )
        )
    row = find_by_id(connection, task_id, actor_staff_member_id=actor_staff_member_id)
    if row is None:
        raise RepositoryInvariantError("The saved task could not be read back")
    return row
