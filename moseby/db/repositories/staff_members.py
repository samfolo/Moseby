"""Read staff identities within one hotel; services resolve their permissions."""

from sqlalchemy import Connection, select

from moseby.identifiers import HotelId, StaffMemberId

from ..models.staff_members import StaffMemberRow
from ..pagination import Page, PageRequest, read_page
from ..tables import staff_members


def find_by_id(
    connection: Connection, id: StaffMemberId, *, hotel_id: HotelId
) -> StaffMemberRow | None:
    """Fetch a staff member in this hotel, or None for a missing or other hotel's ID."""
    row = (
        connection.execute(
            select(staff_members).where(
                staff_members.c.id == id, staff_members.c.hotel_id == hotel_id
            )
        )
        .mappings()
        .one_or_none()
    )
    return StaffMemberRow.model_validate(dict(row)) if row is not None else None


def find_all(
    connection: Connection, *, hotel_id: HotelId, page: PageRequest | None = None
) -> Page[StaffMemberRow]:
    """Fetch this hotel's staff, ordered by creation time, then ID.

    Include unknown roles so the service can handle them explicitly. Pass the
    returned next_cursor to continue, or stop when it is None.
    """
    return read_page(
        connection,
        select(staff_members).where(staff_members.c.hotel_id == hotel_id),
        table=staff_members,
        row_type=StaffMemberRow,
        page=page or PageRequest(),
        query="staff_members.find_all",
        criteria={"hotel_id": hotel_id},
    )
