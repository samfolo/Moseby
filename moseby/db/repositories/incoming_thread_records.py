"""Read incoming thread records belonging to the supplied thread creator."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import IncomingThreadRecordId, StaffMemberId, ThreadId

from ..models.incoming_thread_records import (
    IncomingThreadRecordFilters,
    IncomingThreadRecordRow,
)
from ..pagination import Page, PageRequest, read_sequence_page
from ..tables import incoming_thread_records
from ._queries import unique_ids
from ._thread_queries import owned_thread_ids


def _select(creator_staff_member_id: StaffMemberId) -> Select:
    """Select input through the thread's creator, rather than the message's sender."""
    return select(
        incoming_thread_records.c.id,
        incoming_thread_records.c.thread_id,
        incoming_thread_records.c.sequence,
        incoming_thread_records.c.kind,
        incoming_thread_records.c.delivery_mode,
        incoming_thread_records.c.target_run_id,
        incoming_thread_records.c.actor_staff_member_id,
        incoming_thread_records.c.request_id,
        incoming_thread_records.c.format_version,
        incoming_thread_records.c.created_at,
        incoming_thread_records.c.updated_at,
        incoming_thread_records.c.record_id,
        incoming_thread_records.c.appended_at,
        incoming_thread_records.c.cancelled_at,
        incoming_thread_records.c.cancelled_by_staff_member_id,
        incoming_thread_records.c.payload_json.label("payload"),
    ).where(
        incoming_thread_records.c.thread_id.in_(
            owned_thread_ids(creator_staff_member_id)
        )
    )


def find_by_id(
    connection: Connection,
    id: IncomingThreadRecordId,
    *,
    creator_staff_member_id: StaffMemberId,
) -> IncomingThreadRecordRow | None:
    """Return the saved input if its thread belongs to this staff member.

    If the ID is missing or belongs to another creator, return None.
    """
    row = (
        connection.execute(
            _select(creator_staff_member_id).where(incoming_thread_records.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    return (
        IncomingThreadRecordRow.model_validate(dict(row)) if row is not None else None
    )


def find_by_ids(
    connection: Connection,
    ids: Sequence[IncomingThreadRecordId],
    *,
    creator_staff_member_id: StaffMemberId,
) -> dict[IncomingThreadRecordId, IncomingThreadRecordRow]:
    """Look up at most 100 supplied IDs, counting repeats towards that limit.

    Each matching ID appears once. Missing IDs and other creators' records are
    omitted; an empty input gives an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(creator_staff_member_id).where(incoming_thread_records.c.id.in_(ids))
    ).mappings()
    return {
        row["id"]: IncomingThreadRecordRow.model_validate(dict(row)) for row in rows
    }


def find_all_by_thread_id(
    connection: Connection,
    thread_id: ThreadId,
    *,
    creator_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[IncomingThreadRecordRow]:
    """Read all saved input in arrival order, including appended or cancelled input.

    If the thread is missing or belongs to another creator, return an empty page.
    """
    return search(
        connection,
        IncomingThreadRecordFilters(thread_id=thread_id, pending_only=False),
        creator_staff_member_id=creator_staff_member_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: IncomingThreadRecordFilters,
    *,
    creator_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[IncomingThreadRecordRow]:
    """Read input in arrival order, showing only pending input by default.

    An input is pending until it is appended or cancelled. If a steer's target
    run has ended, the message stays pending; the turn loop decides when to use it.
    """
    statement = _select(creator_staff_member_id).where(
        incoming_thread_records.c.thread_id == filters.thread_id
    )
    if filters.pending_only:
        statement = statement.where(
            incoming_thread_records.c.record_id.is_(None),
            incoming_thread_records.c.cancelled_at.is_(None),
        )
    return read_sequence_page(
        connection,
        statement,
        table=incoming_thread_records,
        row_type=IncomingThreadRecordRow,
        page=page or PageRequest(),
        query="incoming_thread_records.search",
        criteria={
            "creator_staff_member_id": creator_staff_member_id,
            "filters": filters.model_dump_json(),
        },
    )
