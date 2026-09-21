"""Save and read completion deliveries within the acting staff member's job scope."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, insert, select, update

from moseby.identifiers import (
    CompletionId,
    JobId,
    StaffMemberId,
    ThreadId,
    ThreadRecordId,
)
from moseby.runtime.models.job_outcomes import JobOutcome, completion_payload

from ..errors import IdempotencyConflict, RepositoryInvariantError, WriteConflict
from ..models.completion_outbox import CompletionFilters, CompletionRow
from ..pagination import Page, PageRequest, read_page
from ..tables import completion_outbox
from . import jobs as jobs_repository
from . import thread_records as records_repository
from ._queries import unique_ids
from ._work_queries import owned_job_ids
from ._writes import encode_canonical_json, require_write_transaction

# Reads


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


# Writes


def create(
    connection: Connection,
    id: CompletionId,
    job_id: JobId,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> CompletionRow:
    """Save one delivery for the job's final outcome, or return its existing entry.

    Derive the payload from the saved job so its two outcomes cannot diverge.
    This belongs to the same transaction that finishes the job.
    """
    require_write_transaction(connection)
    job = jobs_repository.find_by_id(
        connection, job_id, actor_staff_member_id=actor_staff_member_id
    )
    if job is None or job.finished_at is None or job.thread_id is None:
        raise WriteConflict("The job must be finished, thread-linked and accessible")
    outcome = JobOutcome.model_validate(
        {"status": job.status, "result": job.result, "error": job.error}
    )
    payload = outcome.model_dump(mode="json")
    existing = find_by_job_id(
        connection, job_id, actor_staff_member_id=actor_staff_member_id
    )
    if existing is not None:
        if encode_canonical_json(existing.payload) != encode_canonical_json(payload):
            raise IdempotencyConflict("The job already has a different saved delivery")
        return existing
    if now < job.finished_at:
        raise WriteConflict("Delivery cannot be saved before the job finishes")
    connection.execute(
        insert(completion_outbox).values(
            id=id,
            job_id=job_id,
            thread_id=job.thread_id,
            created_at=now,
            updated_at=now,
            format_version=1,
            payload_json=payload,
        )
    )
    saved = find_by_id(connection, id, actor_staff_member_id=actor_staff_member_id)
    if saved is None:
        raise RepositoryInvariantError("The saved completion could not be read back")
    return saved


def mark_delivered(
    connection: Connection,
    id: CompletionId,
    record_id: ThreadRecordId,
    *,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> CompletionRow:
    """Attach the saved result record once; replaying the same receipt is harmless.

    Check its content against the outcome, while database constraints check its
    thread, source call and run. Save the record and projection in this transaction.
    """
    require_write_transaction(connection)
    saved = find_by_id(connection, id, actor_staff_member_id=actor_staff_member_id)
    if saved is None:
        raise WriteConflict("The completion is missing or inaccessible")
    if saved.record_id is not None:
        if saved.record_id != record_id:
            raise IdempotencyConflict(
                "This completion already has a different delivery receipt"
            )
        return saved
    job = jobs_repository.find_by_id(
        connection, saved.job_id, actor_staff_member_id=actor_staff_member_id
    )
    record = records_repository.find_by_id(
        connection, record_id, creator_staff_member_id=actor_staff_member_id
    )
    if job is None or record is None or record.created_at > now:
        raise WriteConflict("The completion's job or result record is unavailable")
    expected = completion_payload(
        job.id,
        JobOutcome.model_validate(saved.payload),
        tool_result=job.tool_call_id is not None,
    )
    if encode_canonical_json(record.payload) != encode_canonical_json(
        expected.model_dump(mode="json")
    ):
        raise WriteConflict("The result record does not contain the saved job outcome")
    changed = connection.execute(
        update(completion_outbox)
        .where(
            completion_outbox.c.id == id,
            completion_outbox.c.record_id.is_(None),
            completion_outbox.c.updated_at <= now,
        )
        .values(record_id=record_id, appended_at=now, updated_at=now)
    ).rowcount
    if changed != 1:
        raise WriteConflict("The delivery receipt changed or its timestamp is stale")
    return saved.model_copy(
        update={"record_id": record_id, "appended_at": now, "updated_at": now}
    )
