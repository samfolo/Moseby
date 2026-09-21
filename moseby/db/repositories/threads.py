"""Read threads belonging to the supplied thread creator."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import StaffMemberId, ThreadId

from ..models.threads import ThreadRow
from ..pagination import Page, PageRequest, read_page
from ..tables import threads
from ._queries import unique_ids


def _select(creator_staff_member_id: StaffMemberId) -> Select:
    """Select the creator's threads and decode their saved JSON fields."""
    return select(
        threads.c.id,
        threads.c.creator_staff_member_id,
        threads.c.title,
        threads.c.created_at,
        threads.c.updated_at,
        threads.c.archived_at,
        threads.c.permissions_json.label("permissions"),
        threads.c.projection_sequence,
        threads.c.projection_format_version,
        threads.c.projection_json.label("projection"),
    ).where(threads.c.creator_staff_member_id == creator_staff_member_id)


def find_by_id(
    connection: Connection, id: ThreadId, *, creator_staff_member_id: StaffMemberId
) -> ThreadRow | None:
    """Return the thread if this staff member created it.

    If the ID is missing or belongs to another creator, return None.
    """
    row = (
        connection.execute(_select(creator_staff_member_id).where(threads.c.id == id))
        .mappings()
        .one_or_none()
    )
    return ThreadRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[ThreadId],
    *,
    creator_staff_member_id: StaffMemberId,
) -> dict[ThreadId, ThreadRow]:
    """Look up at most 100 supplied IDs, counting repeats towards that limit.

    Each matching ID appears once. Missing IDs and other creators' records are
    omitted; an empty input gives an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(creator_staff_member_id).where(threads.c.id.in_(ids))
    ).mappings()
    return {row["id"]: ThreadRow.model_validate(dict(row)) for row in rows}


def find_all(
    connection: Connection,
    *,
    creator_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[ThreadRow]:
    """List this staff member's threads in creation order, including archived ones.

    Threads with the same timestamp sort by ID. Pass the returned next_cursor
    to continue; services check the saved permissions against current grants.
    """
    return read_page(
        connection,
        _select(creator_staff_member_id),
        table=threads,
        row_type=ThreadRow,
        page=page or PageRequest(),
        query="threads.find_all",
        criteria={"creator_staff_member_id": creator_staff_member_id},
    )
