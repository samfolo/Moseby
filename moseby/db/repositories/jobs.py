"""Read saved jobs through the acting staff member's job scope."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import JobId, RunId, StaffMemberId, ThreadId, ThreadRecordId

from ..models.jobs import JobFilters, JobRow
from ..pagination import Page, PageRequest, read_page
from ..tables import jobs
from ._queries import unique_ids
from ._work_queries import job_scope


def _select(actor_staff_member_id: StaffMemberId) -> Select:
    """Decode the saved JSON fields and apply job ownership before returning rows."""
    return select(
        jobs.c.id,
        jobs.c.created_at,
        jobs.c.updated_at,
        jobs.c.actor_staff_member_id,
        jobs.c.operation,
        jobs.c.request_id,
        jobs.c.thread_id,
        jobs.c.run_id,
        jobs.c.source_record_id,
        jobs.c.tool_call_id,
        jobs.c.handler,
        jobs.c.phase,
        jobs.c.format_version,
        jobs.c.input_json.label("input"),
        jobs.c.status,
        jobs.c.result_json.label("result"),
        jobs.c.error_json.label("error"),
        jobs.c.finished_at,
    ).where(job_scope(actor_staff_member_id))


def find_by_id(
    connection: Connection,
    id: JobId,
    *,
    actor_staff_member_id: StaffMemberId,
) -> JobRow | None:
    """Return the job if this staff member owns it and any linked thread.

    If the ID is missing or falls outside that scope, return None.
    """
    row = (
        connection.execute(_select(actor_staff_member_id).where(jobs.c.id == id))
        .mappings()
        .one_or_none()
    )
    return JobRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[JobId],
    *,
    actor_staff_member_id: StaffMemberId,
) -> dict[JobId, JobRow]:
    """Look up at most 100 supplied IDs, counting repeats towards the limit.

    Each matching ID appears once. Missing or inaccessible rows are omitted;
    an empty list gives an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(actor_staff_member_id).where(jobs.c.id.in_(ids))
    ).mappings()
    return {row["id"]: JobRow.model_validate(dict(row)) for row in rows}


def find_by_operation_and_request_id(
    connection: Connection,
    operation: str,
    request_id: str,
    *,
    actor_staff_member_id: StaffMemberId,
) -> JobRow | None:
    """Find the job accepted for this actor, operation and request ID.

    The full key identifies at most one job and matches its ledger entry. The
    request ID alone can repeat across actors or operations. Services compare
    the saved input before treating a repeated command as a retry.
    """
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(
                jobs.c.operation == operation,
                jobs.c.request_id == request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    return JobRow.model_validate(dict(row)) if row is not None else None


def find_by_source_record_id_and_tool_call_id(
    connection: Connection,
    source_record_id: ThreadRecordId,
    tool_call_id: str,
    *,
    actor_staff_member_id: StaffMemberId,
) -> JobRow | None:
    """Find the accepted job for a specific call within an assistant or classifier record.

    A call ID only identifies a call within its source record. If there is no
    matching job, or the actor cannot read it, return None.
    """
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(
                jobs.c.source_record_id == source_record_id,
                jobs.c.tool_call_id == tool_call_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    return JobRow.model_validate(dict(row)) if row is not None else None


def find_all(
    connection: Connection,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[JobRow]:
    """List this actor's jobs in creation order, including finished and standalone jobs."""
    return search(
        connection, JobFilters(), actor_staff_member_id=actor_staff_member_id, page=page
    )


def find_all_by_thread_id(
    connection: Connection,
    thread_id: ThreadId,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[JobRow]:
    """List the jobs attached to this thread if the actor owns both the jobs and thread."""
    return search(
        connection,
        JobFilters(thread_ids=[thread_id]),
        actor_staff_member_id=actor_staff_member_id,
        page=page,
    )


def find_all_by_run_id(
    connection: Connection,
    run_id: RunId,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[JobRow]:
    """List this run's accepted jobs, including results that arrived after it stopped."""
    return search(
        connection,
        JobFilters(run_ids=[run_id]),
        actor_staff_member_id=actor_staff_member_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: JobFilters,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[JobRow]:
    """Apply all supplied filters before paging jobs in creation-time and ID order.

    Each list matches any of its values. Ownership is required even when the
    caller supplies exact job, thread or run IDs.
    """
    statement = _select(actor_staff_member_id)
    for column, values in (
        (jobs.c.id, filters.ids),
        (jobs.c.thread_id, filters.thread_ids),
        (jobs.c.run_id, filters.run_ids),
        (jobs.c.status, filters.statuses),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    return read_page(
        connection,
        statement,
        table=jobs,
        row_type=JobRow,
        page=page or PageRequest(),
        query="jobs.search",
        criteria={
            "actor_staff_member_id": actor_staff_member_id,
            "filters": filters.model_dump_json(),
        },
    )
