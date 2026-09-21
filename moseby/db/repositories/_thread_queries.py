"""Apply thread ownership before reading related runtime resources."""

from sqlalchemy import Select, select

from moseby.identifiers import StaffMemberId

from ..tables import threads


def owned_thread_ids(creator_staff_member_id: StaffMemberId) -> Select:
    """Select this staff member's threads; services also check current permissions."""
    return select(threads.c.id).where(
        threads.c.creator_staff_member_id == creator_staff_member_id
    )
