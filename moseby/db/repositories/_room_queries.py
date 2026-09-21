"""Use the same overlap rule for room search and reservation writes."""

from sqlalchemy import and_, select
from sqlalchemy.sql.selectable import Exists

from moseby.domain.enums import BookingStatus

from ..models.filters import DateRange
from ..tables import (
    booking_revisions,
    room_reservation_revisions,
    room_reservations,
    rooms,
)
from ._queries import latest_revision


def overlapping_reservation(
    date_range: DateRange, *, exclude_id: str | None = None
) -> Exists:
    """Check for any uncancelled allocation on a confirmed booking for this room.

    Read only the latest reservation dates and booking status. Touching endpoints
    are allowed: a stay can start exactly when the preceding stay ends.
    """
    revision = room_reservation_revisions.c
    return (
        select(1)
        .select_from(room_reservations)
        .join(
            room_reservation_revisions,
            and_(
                revision.room_reservation_id == room_reservations.c.id,
                revision.revision
                == latest_revision(
                    room_reservation_revisions,
                    revision.room_reservation_id,
                    room_reservations.c.id,
                ),
            ),
        )
        .join(
            booking_revisions,
            and_(
                booking_revisions.c.booking_id == room_reservations.c.booking_id,
                booking_revisions.c.revision
                == latest_revision(
                    booking_revisions,
                    booking_revisions.c.booking_id,
                    room_reservations.c.booking_id,
                ),
            ),
        )
        .where(
            room_reservations.c.room_id == rooms.c.id,
            room_reservations.c.id != exclude_id if exclude_id is not None else True,
            revision.cancelled.is_(False),
            booking_revisions.c.status == BookingStatus.CONFIRMED.value,
            revision.min_date < date_range.max_date,
            revision.max_date > date_range.min_date,
        )
        .correlate(rooms)
        .exists()
    )
