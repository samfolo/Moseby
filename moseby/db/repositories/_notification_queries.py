"""Apply the same audience and hotel checks to messages and their publications."""

from sqlalchemy import ColumnElement, and_, or_, select

from moseby.identifiers import HotelId, StaffMemberId

from ..tables import bookings, guests, notification_requests, parties, staff_members


def notification_scope(
    staff_member_id: StaffMemberId, hotel_id: HotelId
) -> ColumnElement[bool]:
    """Allow the author or staff recipient to read a message within this hotel.

    Guest recipients reach their hotel through their party and booking. Staff
    recipients carry their hotel directly. These subqueries keep one row per
    notification; services separately check the caller's current permissions.
    """
    guest_ids = (
        select(guests.c.id)
        .join(parties, guests.c.party_id == parties.c.id)
        .join(bookings, parties.c.booking_id == bookings.c.id)
        .where(bookings.c.hotel_id == hotel_id)
    )
    staff_ids = select(staff_members.c.id).where(staff_members.c.hotel_id == hotel_id)
    return and_(
        or_(
            notification_requests.c.actor_staff_member_id == staff_member_id,
            notification_requests.c.recipient_staff_member_id == staff_member_id,
        ),
        or_(
            notification_requests.c.recipient_guest_id.in_(guest_ids),
            notification_requests.c.recipient_staff_member_id.in_(staff_ids),
        ),
    )
