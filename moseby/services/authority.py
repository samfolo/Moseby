from sqlalchemy import Engine

from moseby.agents.models import AgentDomainContext
from moseby.db.repositories import staff_members
from moseby.db.transaction import transaction
from moseby.domain.enums import StaffRole
from moseby.identifiers import HotelId, StaffMemberId

from . import activities, guests, rooms

CONCIERGE_PERMISSIONS = (
    rooms.READ_PERMISSION,
    guests.READ_PERMISSION,
    activities.READ_PERMISSION,
)


def resolve(
    engine: Engine, *, staff_member_id: StaffMemberId, hotel_id: HotelId
) -> AgentDomainContext:
    """Resolve the selected staff member's current hotel and role from trusted storage."""
    with transaction(engine) as connection:
        staff = staff_members.find_by_id(connection, staff_member_id, hotel_id=hotel_id)
    if staff is None:
        raise PermissionError("The acting staff member is unavailable")
    permissions = CONCIERGE_PERMISSIONS if staff.role == StaffRole.CONCIERGE else ()
    return AgentDomainContext(
        staff_member_id=staff.id,
        hotel_id=staff.hotel_id,
        staff_member_display_name=f"{staff.first_name} {staff.last_name}",
        permissions=permissions,
    )
