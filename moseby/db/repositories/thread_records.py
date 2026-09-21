"""Read thread records belonging to the supplied thread creator."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import StaffMemberId, ThreadId, ThreadRecordId
from moseby.runtime.models.thread_records import ThreadRecordKind

from ..models.thread_records import ThreadRecordFilters, ThreadRecordRow
from ..pagination import Page, PageRequest, read_sequence_page
from ..tables import thread_records
from ._queries import unique_ids
from ._thread_queries import owned_thread_ids


def _select(creator_staff_member_id: StaffMemberId) -> Select:
    """Decode each record's payload after limiting the read to the creator's threads."""
    return select(
        thread_records.c.id,
        thread_records.c.thread_id,
        thread_records.c.sequence,
        thread_records.c.kind,
        thread_records.c.format_version,
        thread_records.c.created_at,
        thread_records.c.run_id,
        thread_records.c.actor_staff_member_id,
        thread_records.c.source_record_id,
        thread_records.c.tool_call_id,
        thread_records.c.payload_json.label("payload"),
    ).where(thread_records.c.thread_id.in_(owned_thread_ids(creator_staff_member_id)))


def find_by_id(
    connection: Connection,
    id: ThreadRecordId,
    *,
    creator_staff_member_id: StaffMemberId,
) -> ThreadRecordRow | None:
    """Return the saved thread record if its thread belongs to this staff member.

    If the ID is missing or belongs to another creator, return None.
    """
    row = (
        connection.execute(
            _select(creator_staff_member_id).where(thread_records.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    return ThreadRecordRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[ThreadRecordId],
    *,
    creator_staff_member_id: StaffMemberId,
) -> dict[ThreadRecordId, ThreadRecordRow]:
    """Look up at most 100 supplied IDs, counting repeats towards that limit.

    Each matching ID appears once. Missing IDs and other creators' records are
    omitted; an empty input gives an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(creator_staff_member_id).where(thread_records.c.id.in_(ids))
    ).mappings()
    return {row["id"]: ThreadRecordRow.model_validate(dict(row)) for row in rows}


def find_all_by_thread_id(
    connection: Connection,
    thread_id: ThreadId,
    *,
    creator_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[ThreadRecordRow]:
    """Read every kind of saved history in its original sequence order.

    This includes internal runtime events. If the thread is missing or belongs
    to another creator, return an empty page.
    """
    return search(
        connection,
        ThreadRecordFilters(thread_id=thread_id),
        creator_staff_member_id=creator_staff_member_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: ThreadRecordFilters,
    *,
    creator_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[ThreadRecordRow]:
    """Read this thread's history in sequence order, applying filters before paging.

    Each list matches any of its values, and all supplied filters must match.
    Kinds are unrestricted unless supplied; services select the conversation
    kinds when preparing a public response.
    """
    statement = _select(creator_staff_member_id).where(
        thread_records.c.thread_id == filters.thread_id
    )
    for column, values in (
        (thread_records.c.id, filters.ids),
        (thread_records.c.run_id, filters.run_ids),
        (thread_records.c.kind, filters.kinds),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    return read_sequence_page(
        connection,
        statement,
        table=thread_records,
        row_type=ThreadRecordRow,
        page=page or PageRequest(),
        query="thread_records.search",
        criteria={
            "creator_staff_member_id": creator_staff_member_id,
            "filters": filters.model_dump_json(),
        },
    )


def find_last_by_thread_id(
    connection: Connection,
    thread_id: ThreadId,
    *,
    creator_staff_member_id: StaffMemberId,
    kind: ThreadRecordKind | None = None,
    before_sequence: int | None = None,
) -> ThreadRecordRow | None:
    """Return the last matching record, or None if none is visible to this creator.

    Supply a kind to find the last user or assistant message. To find the one
    before it, pass that record's sequence as before_sequence.
    """
    statement = _select(creator_staff_member_id).where(
        thread_records.c.thread_id == thread_id
    )
    if kind is not None:
        statement = statement.where(thread_records.c.kind == kind)
    if before_sequence is not None:
        statement = statement.where(thread_records.c.sequence < before_sequence)
    row = (
        connection.execute(
            statement.order_by(thread_records.c.sequence.desc()).limit(1)
        )
        .mappings()
        .one_or_none()
    )
    return ThreadRecordRow.model_validate(dict(row)) if row is not None else None
