"""Check complete room coverage without relying on a displayed page of reservations."""

from itertools import pairwise

from sqlalchemy import Connection, case, func, select

from moseby.domain.bed_capacity import BED_CAPACITY
from moseby.identifiers import BookingId

from ..errors import WriteConflict
from ..models.filters import DateRange
from ..tables import (
    activities,
    beds,
    guests,
    parties,
    room_reservation_revisions,
    room_reservations,
)
from ._activity_queries import current_reservations
from ._queries import latest_revision


def room_intervals(
    connection: Connection, booking_id: BookingId
) -> list[tuple[int, int]]:
    revision = room_reservation_revisions.c
    return list(
        connection.execute(
            select(revision.min_date, revision.max_date)
            .join(
                room_reservations,
                room_reservations.c.id == revision.room_reservation_id,
            )
            .where(
                room_reservations.c.booking_id == booking_id,
                revision.cancelled.is_(False),
                revision.revision
                == latest_revision(
                    room_reservation_revisions,
                    revision.room_reservation_id,
                    room_reservations.c.id,
                ),
            )
            .order_by(revision.min_date)
        ).tuples()
    )


def require_coverage(
    connection: Connection, booking_id: BookingId, dates: DateRange
) -> None:
    """Allow adjacent allocations to cover an activity, but reject any gap in the stay."""
    covered_until = dates.min_date
    for start, end in room_intervals(connection, booking_id):
        if start > covered_until:
            break
        covered_until = max(covered_until, end)
        if covered_until >= dates.max_date:
            return
    raise WriteConflict("The activity must fit within the guest's reserved stay")


def check_reserved_activities(connection: Connection, booking_id: BookingId) -> None:
    """A room amendment must leave a room and cover every effective activity in the stay."""
    if not room_intervals(connection, booking_id):
        raise WriteConflict(
            "A confirmed stay must retain at least one room reservation"
        )
    current = current_reservations().subquery()
    rows = connection.execute(
        select(activities.c.min_date, activities.c.max_date)
        .join(current, current.c.activity_id == activities.c.id)
        .where(current.c.booking_id == booking_id, current.c.effective.is_(True))
        .distinct()
    )
    for start, end in rows:
        require_coverage(
            connection, booking_id, DateRange(min_date=start, max_date=end)
        )


def check_room_capacity(connection: Connection, booking_id: BookingId) -> None:
    """Require enough sleeping places for the whole party throughout its reserved stay."""
    people = connection.scalar(
        select(func.count())
        .select_from(guests)
        .join(parties, guests.c.party_id == parties.c.id)
        .where(parties.c.booking_id == booking_id)
    )
    revision = room_reservation_revisions.c
    capacity = (
        select(
            func.coalesce(func.sum(case(BED_CAPACITY, value=beds.c.type, else_=0)), 0)
        )
        .where(beds.c.room_id == room_reservations.c.room_id)
        .scalar_subquery()
    )
    allocations = list(
        connection.execute(
            select(revision.min_date, revision.max_date, capacity)
            .join(
                room_reservations,
                room_reservations.c.id == revision.room_reservation_id,
            )
            .where(
                room_reservations.c.booking_id == booking_id,
                revision.cancelled.is_(False),
                revision.revision
                == latest_revision(
                    room_reservation_revisions,
                    revision.room_reservation_id,
                    room_reservations.c.id,
                ),
            )
        )
    )
    if not allocations or not people:
        raise WriteConflict("A stay requires rooms and at least one guest")
    boundaries = sorted(
        {time for start, end, _ in allocations for time in (start, end)}
    )
    # Sleeping capacity can change at any arrival or departure, so check each interval.
    for start, end in pairwise(boundaries):
        places = sum(
            count
            for arrival, departure, count in allocations
            if arrival <= start and departure >= end
        )
        if places < people:
            raise WriteConflict(
                "The rooms do not provide enough sleeping places throughout the stay"
            )
