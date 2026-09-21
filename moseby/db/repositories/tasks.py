"""Read saved tasks through the acting staff member's job scope."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import JobId, StaffMemberId, TaskId

from ..models.tasks import TaskFilters, TaskRow
from ..pagination import Page, PageRequest, read_page
from ..tables import tasks
from ._queries import unique_ids
from ._work_queries import owned_job_ids


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
