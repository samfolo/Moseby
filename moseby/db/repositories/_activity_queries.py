"""Keep activity counts and reservation reads on the same current-state rules."""

from sqlalchemy import Column, Select, and_, func, select
from sqlalchemy.sql.selectable import ScalarSelect

from ..tables import (
    activities,
    activity_reservation_revisions,
    activity_reservations,
    booking_revisions,
    bookings,
    parties,
)
from ._queries import latest_revision


def current_reservations() -> Select:
    """Select one current revision per reservation and follow its party to a booking.

    Cancellation of either the reservation or booking releases the place.
    Completed stays keep their uncancelled reservations effective, including past
    activities. Event dates are filtered separately when reading an itinerary.
    """
    revision = activity_reservation_revisions.c
    return (
        select(
            activity_reservations,
            bookings.c.id.label("booking_id"),
            bookings.c.hotel_id,
            revision.revision,
            revision.cancelled,
            revision.cancellation_reason,
            revision.price_id,
            revision.price_revision,
            revision.price_unit,
            and_(
                revision.cancelled.is_(False),
                booking_revisions.c.status.in_(
                    ("BOOKING_STATUS_CONFIRMED", "BOOKING_STATUS_COMPLETED")
                ),
            ).label("effective"),
        )
        .join(parties, activity_reservations.c.party_id == parties.c.id)
        .join(bookings, parties.c.booking_id == bookings.c.id)
        .join(
            activity_reservation_revisions,
            and_(
                revision.activity_reservation_id == activity_reservations.c.id,
                revision.revision
                == latest_revision(
                    activity_reservation_revisions,
                    revision.activity_reservation_id,
                    activity_reservations.c.id,
                ),
            ),
        )
        .join(
            booking_revisions,
            and_(
                booking_revisions.c.booking_id == bookings.c.id,
                booking_revisions.c.revision
                == latest_revision(
                    booking_revisions, booking_revisions.c.booking_id, bookings.c.id
                ),
            ),
        )
    )


def effective_count(activity_id: Column | str) -> ScalarSelect[int]:
    """Count all effective guest places for the activity, across hotels.

    Counting current reservations avoids counting old revisions as extra guests.
    The query returns only a number, without exposing other hotels' attendees.
    """
    statement = current_reservations()
    return (
        statement.with_only_columns(func.count(), maintain_column_froms=True)
        .where(
            activity_reservations.c.activity_id == activity_id,
            statement.selected_columns.effective.is_(True),
        )
        .correlate(activities)
        .scalar_subquery()
    )
