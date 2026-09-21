"""Read completion deliveries through the acting staff member's job scope."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import CompletionId, JobId, StaffMemberId, ThreadId

from ..models.completion_outbox import CompletionFilters, CompletionRow
from ..pagination import Page, PageRequest, read_page
from ..tables import completion_outbox
from ._queries import unique_ids
from ._work_queries import owned_job_ids


def _select(actor_staff_member_id: StaffMemberId) -> Select:
    """Decode the saved JSON fields and apply job ownership before returning rows."""
    return select(
        completion_outbox.c.id,
        completion_outbox.c.created_at,
        completion_outbox.c.updated_at,
        completion_outbox.c.job_id,
        completion_outbox.c.thread_id,
        completion_outbox.c.format_version,
        completion_outbox.c.payload_json.label("payload"),
        completion_outbox.c.record_id,
        completion_outbox.c.appended_at,
    ).where(completion_outbox.c.job_id.in_(owned_job_ids(actor_staff_member_id)))


def find_by_id(
    connection: Connection,
    id: CompletionId,
    *,
    actor_staff_member_id: StaffMemberId,
) -> CompletionRow | None:
    """Return this completion if the actor owns its job and any linked thread.

    If the ID is missing or falls outside that scope, return None.
    """
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(completion_outbox.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    return CompletionRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[CompletionId],
    *,
    actor_staff_member_id: StaffMemberId,
) -> dict[CompletionId, CompletionRow]:
    """Look up at most 100 supplied IDs, counting repeats towards the limit.

    Each matching ID appears once. Missing or inaccessible rows are omitted;
    an empty list gives an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(actor_staff_member_id).where(completion_outbox.c.id.in_(ids))
    ).mappings()
    return {row["id"]: CompletionRow.model_validate(dict(row)) for row in rows}


def find_by_job_id(
    connection: Connection,
    job_id: JobId,
    *,
    actor_staff_member_id: StaffMemberId,
) -> CompletionRow | None:
    """Return the job's single completion, whether it is pending or already delivered.

    A completed job without a thread may have no outbox entry. Missing or
    inaccessible jobs also return None.
    """
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(completion_outbox.c.job_id == job_id)
        )
        .mappings()
        .one_or_none()
    )
    return CompletionRow.model_validate(dict(row)) if row is not None else None


def find_all_by_thread_id(
    connection: Connection,
    thread_id: ThreadId,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[CompletionRow]:
    """Read this thread's completion history, including delivered results.

    The actor must own each job as well as the destination thread.
    """
    return search(
        connection,
        CompletionFilters(thread_ids=[thread_id], pending_only=False),
        actor_staff_member_id=actor_staff_member_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: CompletionFilters,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[CompletionRow]:
    """Read matching completions in creation order, showing pending deliveries by default.

    A result stays pending until its history record is saved, even if the run
    has stopped. Reading it neither delivers it nor restarts that run.
    """
    statement = _select(actor_staff_member_id)
    for column, values in (
        (completion_outbox.c.thread_id, filters.thread_ids),
        (completion_outbox.c.job_id, filters.job_ids),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    if filters.pending_only:
        statement = statement.where(completion_outbox.c.record_id.is_(None))
    return read_page(
        connection,
        statement,
        table=completion_outbox,
        row_type=CompletionRow,
        page=page or PageRequest(),
        query="completion_outbox.search",
        criteria={
            "actor_staff_member_id": actor_staff_member_id,
            "filters": filters.model_dump_json(),
        },
    )
