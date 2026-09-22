"""Read runs belonging to the supplied thread creator."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, insert, select, update

from moseby.identifiers import AgentId, RunId, StaffMemberId, ThreadId
from moseby.runtime.enums import RunStatus

from ..errors import WriteConflict
from ..models.runs import RunRow
from ..pagination import Page, PageRequest, read_page
from ..tables import runs
from . import threads as threads_repository
from ._queries import unique_ids
from ._thread_queries import owned_thread_ids
from ._writes import require_found, require_write_transaction


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


def find_all_by_agent_id(
    connection: Connection,
    agent_id: AgentId,
    *,
    creator_staff_member_id: StaffMemberId,
    agent_version: int | None = None,
    page: PageRequest | None = None,
) -> Page[RunRow]:
    """List this creator's runs for an agent, optionally limited to one version."""
    statement = _select(creator_staff_member_id).where(runs.c.agent_id == agent_id)
    if agent_version is not None:
        statement = statement.where(runs.c.agent_version == agent_version)
    return read_page(
        connection,
        statement,
        table=runs,
        row_type=RunRow,
        page=page or PageRequest(),
        query="runs.find_all_by_agent_id",
        criteria={
            "creator_staff_member_id": creator_staff_member_id,
            "agent_id": agent_id,
            "agent_version": str(agent_version),
        },
    )


def create(
    connection: Connection,
    id: RunId,
    thread_id: ThreadId,
    *,
    creator_staff_member_id: StaffMemberId,
    now: int,
) -> RunRow:
    """Start one run with its thread's agent selection; reject another active run."""
    require_write_transaction(connection)
    thread = require_found(
        threads_repository.find_by_id(
            connection, thread_id, creator_staff_member_id=creator_staff_member_id
        )
    )
    if (
        thread.archived_at is not None
        or find_active_by_thread_id(
            connection, thread_id, creator_staff_member_id=creator_staff_member_id
        )
        is not None
    ):
        raise WriteConflict("The thread is archived or already has an active run")
    connection.execute(
        insert(runs).values(
            id=id,
            thread_id=thread_id,
            agent_id=thread.agent_id,
            agent_version=thread.agent_version,
            status=RunStatus.RUNNING,
            recovery_attempts=0,
            created_at=now,
            updated_at=now,
        )
    )
    return require_found(
        find_by_id(connection, id, creator_staff_member_id=creator_staff_member_id)
    )


def require_running(
    connection: Connection, id: RunId, *, creator_staff_member_id: StaffMemberId
) -> RunRow:
    """Reject stopped runs and pending cancellation before accepting more work."""
    run = require_found(
        find_by_id(connection, id, creator_staff_member_id=creator_staff_member_id)
    )
    if run.status != RunStatus.RUNNING or run.cancel_requested_at is not None:
        raise WriteConflict("The run is stopped or cancellation was requested")
    return run


def finish(
    connection: Connection,
    id: RunId,
    status: RunStatus,
    *,
    creator_staff_member_id: StaffMemberId,
    now: int,
) -> RunRow:
    """Set the terminal state once; a retry of the same outcome returns the saved run."""
    require_write_transaction(connection)
    if status not in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
        raise ValueError("Finishing a run requires a terminal status")
    saved = require_found(
        find_by_id(connection, id, creator_staff_member_id=creator_staff_member_id)
    )
    if saved.finished_at is not None:
        if saved.status != status:
            raise WriteConflict("The run already finished with a different outcome")
        return saved
    if now < saved.updated_at:
        raise WriteConflict("The finish time precedes the saved run")
    if saved.cancel_requested_at is not None and status == RunStatus.COMPLETED:
        raise WriteConflict("A cancelled run cannot be marked completed")
    connection.execute(
        update(runs)
        .where(runs.c.id == id)
        .values(
            status=status,
            finished_at=now,
            updated_at=now,
            wake_at=None,
        )
    )
    return require_found(
        find_by_id(connection, id, creator_staff_member_id=creator_staff_member_id)
    )
