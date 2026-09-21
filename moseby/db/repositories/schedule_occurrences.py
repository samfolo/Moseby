"""Read accepted firings through their original jobs, even after schedule edits."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import JobId, ScheduleId, ScheduleOccurrenceId, StaffMemberId

from ..models.schedule_occurrences import ScheduleOccurrenceRow
from ..pagination import Page, PageRequest, read_page
from ..tables import schedule_occurrences, schedules
from ._queries import unique_ids
from ._work_queries import owned_job_ids


def _select(actor_staff_member_id: StaffMemberId) -> Select:
    """Check the schedule's owner and the original job's actor and thread.

    The current schedule may point somewhere else or be disabled. Its edits
    do not change the destination or input already accepted for this firing.
    """
    return select(
        schedule_occurrences.c.id,
        schedule_occurrences.c.created_at,
        schedule_occurrences.c.schedule_id,
        schedule_occurrences.c.schedule_revision,
        schedule_occurrences.c.due_at,
        schedule_occurrences.c.format_version,
        schedule_occurrences.c.snapshot_json.label("snapshot"),
        schedule_occurrences.c.job_id,
    ).where(
        schedule_occurrences.c.schedule_id.in_(
            select(schedules.c.id).where(
                schedules.c.actor_staff_member_id == actor_staff_member_id
            )
        ),
        schedule_occurrences.c.job_id.in_(owned_job_ids(actor_staff_member_id)),
    )


def find_by_id(
    connection: Connection,
    id: ScheduleOccurrenceId,
    *,
    actor_staff_member_id: StaffMemberId,
) -> ScheduleOccurrenceRow | None:
    """Return the saved row if it exists and the caller can read it; otherwise None."""
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(schedule_occurrences.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    return ScheduleOccurrenceRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[ScheduleOccurrenceId],
    *,
    actor_staff_member_id: StaffMemberId,
) -> dict[ScheduleOccurrenceId, ScheduleOccurrenceRow]:
    """Read at most 100 supplied IDs, counting repeats towards the limit.

    Missing or inaccessible IDs are omitted. Repeated IDs appear once, and an
    empty input returns an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(actor_staff_member_id).where(schedule_occurrences.c.id.in_(ids))
    ).mappings()
    return {row["id"]: ScheduleOccurrenceRow.model_validate(dict(row)) for row in rows}


def find_by_job_id(
    connection: Connection, job_id: JobId, *, actor_staff_member_id: StaffMemberId
) -> ScheduleOccurrenceRow | None:
    """Find the firing that created this job, or None for missing or inaccessible work."""
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(
                schedule_occurrences.c.job_id == job_id
            )
        )
        .mappings()
        .one_or_none()
    )
    return ScheduleOccurrenceRow.model_validate(dict(row)) if row is not None else None


def find_by_schedule_id_and_due_at(
    connection: Connection,
    schedule_id: ScheduleId,
    due_at: int,
    *,
    actor_staff_member_id: StaffMemberId,
) -> ScheduleOccurrenceRow | None:
    """Find the single accepted firing for this due time, across schedule revisions."""
    row = (
        connection.execute(
            _select(actor_staff_member_id).where(
                schedule_occurrences.c.schedule_id == schedule_id,
                schedule_occurrences.c.due_at == due_at,
            )
        )
        .mappings()
        .one_or_none()
    )
    return ScheduleOccurrenceRow.model_validate(dict(row)) if row is not None else None


def find_all_by_schedule_id(
    connection: Connection,
    schedule_id: ScheduleId,
    *,
    actor_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[ScheduleOccurrenceRow]:
    """List accepted firings in creation order, retaining failed or cancelled jobs.

    The linked job carries the outcome. This list contains recorded firings,
    rather than dates on which the schedule might run in the future.
    """
    return read_page(
        connection,
        _select(actor_staff_member_id).where(
            schedule_occurrences.c.schedule_id == schedule_id
        ),
        table=schedule_occurrences,
        row_type=ScheduleOccurrenceRow,
        page=page or PageRequest(),
        query="schedule_occurrences.find_all_by_schedule_id",
        criteria={
            "actor_staff_member_id": actor_staff_member_id,
            "schedule_id": schedule_id,
        },
    )
