"""Keep work and its child records within the acting staff member's scope."""

from sqlalchemy import ColumnElement, Select, and_, or_, select

from moseby.identifiers import StaffMemberId

from ..tables import jobs
from ._thread_queries import owned_thread_ids


def job_scope(actor_staff_member_id: StaffMemberId) -> ColumnElement[bool]:
    """Require the actor to own the job and any thread attached to it.

    Jobs without a thread belong to their actor. Services also check the actor's
    current permissions before returning data or allowing work to execute.
    """
    return and_(
        jobs.c.actor_staff_member_id == actor_staff_member_id,
        or_(
            jobs.c.thread_id.is_(None),
            jobs.c.thread_id.in_(owned_thread_ids(actor_staff_member_id)),
        ),
    )


def owned_job_ids(actor_staff_member_id: StaffMemberId) -> Select:
    """Select accessible jobs so their tasks, claims and results share one rule."""
    return select(jobs.c.id).where(job_scope(actor_staff_member_id))
