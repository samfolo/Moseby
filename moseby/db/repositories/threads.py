"""Read threads and advance their saved summaries within the creator's scope."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, func, select, update

from moseby.identifiers import AgentId, StaffMemberId, ThreadId

from ..errors import RepositoryInvariantError, WriteConflict
from ..models.threads import ProjectionUpdate, ThreadRow
from ..pagination import Page, PageRequest, read_page
from ..tables import thread_records, threads
from ._queries import unique_ids
from ._writes import encode_canonical_json, require_write_transaction

# Reads


def _select(creator_staff_member_id: StaffMemberId) -> Select:
    """Select the creator's threads and decode their saved JSON fields."""
    return select(
        threads.c.id,
        threads.c.agent_id,
        threads.c.agent_version,
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


def find_all_by_agent_id(
    connection: Connection,
    agent_id: AgentId,
    *,
    creator_staff_member_id: StaffMemberId,
    agent_version: int | None = None,
    page: PageRequest | None = None,
) -> Page[ThreadRow]:
    """List this creator's threads for an agent, optionally limited to one version."""
    statement = _select(creator_staff_member_id).where(threads.c.agent_id == agent_id)
    if agent_version is not None:
        statement = statement.where(threads.c.agent_version == agent_version)
    return read_page(
        connection,
        statement,
        table=threads,
        row_type=ThreadRow,
        page=page or PageRequest(),
        query="threads.find_all_by_agent_id",
        criteria={
            "creator_staff_member_id": creator_staff_member_id,
            "agent_id": agent_id,
            "agent_version": str(agent_version),
        },
    )


# Writes


def save_projection(
    connection: Connection,
    id: ThreadId,
    projection: ProjectionUpdate,
    *,
    creator_staff_member_id: StaffMemberId,
    now: int,
) -> ThreadRow:
    """Advance the summary after appending the next record to the expected history.

    Reject a changed projection or history position. The runtime supplies the
    summary content; save it together with the record it describes.
    """
    require_write_transaction(connection)
    encode_canonical_json(projection.value)
    sequence = projection.expected_history_sequence + 1
    head = (
        select(func.max(thread_records.c.sequence))
        .where(thread_records.c.thread_id == id)
        .scalar_subquery()
    )
    changed = connection.execute(
        update(threads)
        .where(
            threads.c.id == id,
            threads.c.creator_staff_member_id == creator_staff_member_id,
            threads.c.projection_sequence == projection.expected_sequence,
            threads.c.updated_at <= now,
            head == sequence,
        )
        .values(
            projection_sequence=sequence,
            projection_format_version=projection.format_version,
            projection_json=projection.value,
            updated_at=now,
        )
    ).rowcount
    if changed != 1:
        raise WriteConflict("The thread's projection or history has changed")
    saved = find_by_id(connection, id, creator_staff_member_id=creator_staff_member_id)
    if saved is None:
        raise RepositoryInvariantError("The thread projection could not be read back")
    return saved
