"""Protect a tool's database changes with current authority and its worker claim."""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine

from moseby.db.errors import WriteConflict
from moseby.db.repositories import task_claims
from moseby.db.transaction import transaction
from moseby.permissions import Permission
from moseby.services import authority
from moseby.services.access import require_permission
from moseby.tools.definitions import ToolContext

from .storage import now_microseconds


@contextmanager
def claimed_write(
    engine: Engine, context: ToolContext, *, permissions: Iterable[Permission]
) -> Iterator[tuple[Connection, int]]:
    """Recheck access, then hold a short transaction under the task's live claim."""
    if context.claim is None:
        raise WriteConflict("Changing guest data requires a claimed task")
    current = authority.resolve(
        engine,
        staff_member_id=context.domain_context.staff_member_id,
        hotel_id=context.domain_context.hotel_id,
    )
    for permission in (*context.thread_context.permissions, *permissions):
        require_permission(current.permissions, permission)
    with transaction(engine, write=True) as connection:
        now = now_microseconds()
        with task_claims.guard(
            connection,
            context.claim.task_id,
            context.claim.token,
            actor_staff_member_id=current.staff_member_id,
            now=now,
        ):
            yield connection, now
