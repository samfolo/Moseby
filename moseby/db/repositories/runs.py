"""Read runs belonging to the supplied thread creator."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import RunId, StaffMemberId, ThreadId
from moseby.runtime.enums import RunStatus

from ..models.runs import RunRow
from ..pagination import Page, PageRequest, read_page
from ..tables import runs
from ._queries import unique_ids
from ._thread_queries import owned_thread_ids


def _select(creator_staff_member_id: StaffMemberId) -> Select:
    """Limit the runs to threads that this staff member created."""
    return select(runs).where(
        runs.c.thread_id.in_(owned_thread_ids(creator_staff_member_id))
    )


def find_by_id(
    connection: Connection, id: RunId, *, creator_staff_member_id: StaffMemberId
) -> RunRow | None:
    """Return the saved run if its thread belongs to this staff member.

    If the ID is missing or belongs to another creator, return None.
    """
    row = (
        connection.execute(_select(creator_staff_member_id).where(runs.c.id == id))
        .mappings()
        .one_or_none()
    )
    return RunRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[RunId],
    *,
    creator_staff_member_id: StaffMemberId,
) -> dict[RunId, RunRow]:
    """Look up at most 100 supplied IDs, counting repeats towards that limit.

    Each matching ID appears once. Missing IDs and other creators' records are
    omitted; an empty input gives an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(creator_staff_member_id).where(runs.c.id.in_(ids))
    ).mappings()
    return {row["id"]: RunRow.model_validate(dict(row)) for row in rows}


def find_all_by_thread_id(
    connection: Connection,
    thread_id: ThreadId,
    *,
    creator_staff_member_id: StaffMemberId,
    page: PageRequest | None = None,
) -> Page[RunRow]:
    """List the thread's runs in creation order, including runs that have ended.

    If the thread is missing or belongs to another creator, the page is empty.
    """
    return read_page(
        connection,
        _select(creator_staff_member_id).where(runs.c.thread_id == thread_id),
        table=runs,
        row_type=RunRow,
        page=page or PageRequest(),
        query="runs.find_all_by_thread_id",
        criteria={
            "creator_staff_member_id": creator_staff_member_id,
            "thread_id": thread_id,
        },
    )


def find_active_by_thread_id(
    connection: Connection,
    thread_id: ThreadId,
    *,
    creator_staff_member_id: StaffMemberId,
) -> RunRow | None:
    """Return the thread's queued, running or waiting run, if it has one.

    A sleeping run still occupies the slot, as does a run with a pending stop
    request. Return None if there is no active run or the creator does not match.
    """
    row = (
        connection.execute(
            _select(creator_staff_member_id).where(
                runs.c.thread_id == thread_id,
                runs.c.status.in_(
                    (
                        RunStatus.QUEUED.value,
                        RunStatus.RUNNING.value,
                        RunStatus.WAITING.value,
                    )
                ),
            )
        )
        .mappings()
        .one_or_none()
    )
    return RunRow.model_validate(dict(row)) if row is not None else None
