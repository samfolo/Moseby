"""Read current schedules belonging to the actor and any attached thread."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, and_, or_, select

from moseby.identifiers import ScheduleId, StaffMemberId, ThreadId

from ..models.schedules import ScheduleFilters, ScheduleRow
from ..pagination import Page, PageRequest, read_page
from ..tables import schedules
from ._queries import unique_ids
from ._thread_queries import owned_thread_ids


def _select(actor_staff_member_id: StaffMemberId) -> Select:
    """Include standalone schedules and require ownership of each linked thread."""
    return select(
        schedules.c.id,
        schedules.c.created_at,
        schedules.c.updated_at,
        schedules.c.actor_staff_member_id,
        schedules.c.revision,
        schedules.c.enabled,
        schedules.c.due_at,
        schedules.c.cron_expression,
        schedules.c.cron_dialect,
        schedules.c.thread_id,
        schedules.c.handler,
        schedules.c.format_version,
        schedules.c.input_json.label("input"),
    ).where(
        and_(
            schedules.c.actor_staff_member_id == actor_staff_member_id,
            or_(
                schedules.c.thread_id.is_(None),
                schedules.c.thread_id.in_(owned_thread_ids(actor_staff_member_id)),
            ),
        )
    )


def find_by_id(
    connection: Connection, id: ScheduleId, *, actor_staff_member_id: StaffMemberId
) -> ScheduleRow | None:
    """Return the saved row if it exists and the caller can read it; otherwise None."""
    row = (
        connection.execute(_select(actor_staff_member_id).where(schedules.c.id == id))
        .mappings()
        .one_or_none()
    )
    return ScheduleRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[ScheduleId],
    *,
    actor_staff_member_id: StaffMemberId,
) -> dict[ScheduleId, ScheduleRow]:
    """Read at most 100 supplied IDs, counting repeats towards the limit.

    Missing or inaccessible IDs are omitted. Repeated IDs appear once, and an
    empty input returns an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(actor_staff_member_id).where(schedules.c.id.in_(ids))
    ).mappings()
    return {row["id"]: ScheduleRow.model_validate(dict(row)) for row in rows}


def find_all(
    connection: Connection,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[ScheduleRow]:
    """List current definitions, including disabled and standalone schedules."""
    return search(
        connection,
        ScheduleFilters(),
        actor_staff_member_id=actor_staff_member_id,
        page=page,
    )


def find_all_by_thread_id(
    connection: Connection,
    thread_id: ThreadId,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[ScheduleRow]:
    """List schedules whose current destination is this owned thread."""
    return search(
        connection,
        ScheduleFilters(thread_ids=[thread_id]),
        actor_staff_member_id=actor_staff_member_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: ScheduleFilters,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[ScheduleRow]:
    """Apply filters before paging current definitions by creation time and ID.

    Reading a rule does not calculate cron matches or accept scheduled work.
    """
    statement = _select(actor_staff_member_id)
    for column, values in (
        (schedules.c.id, filters.ids),
        (schedules.c.thread_id, filters.thread_ids),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    if filters.enabled is not None:
        statement = statement.where(schedules.c.enabled == filters.enabled)
    return read_page(
        connection,
        statement,
        table=schedules,
        row_type=ScheduleRow,
        page=page or PageRequest(),
        query="schedules.search",
        criteria={
            "actor_staff_member_id": actor_staff_member_id,
            "filters": filters.model_dump_json(),
        },
    )
