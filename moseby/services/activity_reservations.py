"""Read guest itineraries and apply reservation commands within the staff member's hotel."""

from collections.abc import Iterable

from sqlalchemy import Connection, Engine

from moseby.agents.models import AgentDomainContext
from moseby.contracts.activities import ActivityPrice
from moseby.contracts.activity_reservations import (
    ActivityReservation,
    ActivityReservations,
    CancelActivityReservationRequestPayload,
    ReserveActivityRequestPayload,
    ReservedActivity,
    SearchActivityReservationsRequestPayload,
)
from moseby.contracts.amounts import NonNegativeAmount
from moseby.contracts.common import Page
from moseby.contracts.ranges import DateRange
from moseby.db.models.activity_reservations import (
    ActivityAttendee,
    ActivityReservationFilters,
    ActivityReservationRow,
    ReserveActivity,
)
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.operations import commands
from moseby.db.pagination import PageRequest
from moseby.db.repositories import activities, activity_reservations
from moseby.db.timestamps import to_datetime, to_microseconds
from moseby.db.transaction import transaction
from moseby.identifiers import ActivityReservationId, HotelId, new_id
from moseby.permissions import Permission

from .access import require_permission
from .activities import READ_PERMISSION as READ_PERMISSION

WRITE_PERMISSION = Permission("moseby.activities:write")


def search(
    engine: Engine,
    request: SearchActivityReservationsRequestPayload,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
) -> Page[ActivityReservation]:
    """Return a flat, paged itinerary with current event times and saved prices."""
    require_permission(permissions, READ_PERMISSION)
    filters = request.model_dump(exclude={"cursor", "limit"})
    if request.date_range is not None:
        filters["date_range"] = {
            "min_date": to_microseconds(request.date_range.min_date),
            "max_date": to_microseconds(request.date_range.max_date),
        }
    with transaction(engine) as connection:
        page = activity_reservations.search(
            connection,
            ActivityReservationFilters.model_validate(filters),
            hotel_id=hotel_id,
            page=PageRequest(cursor=request.cursor, limit=request.limit),
        )
    return Page[ActivityReservation](
        items=[_reservation(row) for row in page.items], next_cursor=page.next_cursor
    )


def get(
    engine: Engine,
    id: ActivityReservationId,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
) -> ActivityReservation | None:
    """Read one reservation in this hotel, including a cancelled reservation."""
    require_permission(permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        row = activity_reservations.find_by_id(connection, id, hotel_id=hotel_id)
    return _reservation(row) if row is not None else None


def reserve(
    connection: Connection,
    request: ReserveActivityRequestPayload,
    *,
    context: AgentDomainContext,
    request_id: str,
    now: int,
) -> ActivityReservations:
    """Reserve the whole group once; a retry returns the saved response."""
    require_permission(context.permissions, WRITE_PERMISSION)

    def action():
        if activities.find_by_id(connection, request.activity_id) is None:
            raise ValueError(
                "Activity not found. Search activities and use a returned ID."
            )
        rows = activity_reservations.reserve(
            connection,
            ReserveActivity(
                activity_id=request.activity_id,
                attendees=[
                    ActivityAttendee(id=new_id("activity_reservation"), guest_id=id)
                    for id in request.guest_ids
                ],
            ),
            hotel_id=context.hotel_id,
            now=now,
        )
        return ActivityReservations(
            reservations=[_reservation(row) for row in rows]
        ).model_dump(mode="json")

    saved = commands.execute(
        connection,
        RequestKey(
            actor_staff_member_id=context.staff_member_id,
            operation="activity-reservations.reserve",
            request_id=request_id,
        ),
        {"hotel_id": context.hotel_id, "payload": request.model_dump(mode="json")},
        action,
        now=now,
    )
    return ActivityReservations.model_validate(saved)


def cancel(
    connection: Connection,
    id: ActivityReservationId,
    request: CancelActivityReservationRequestPayload,
    *,
    context: AgentDomainContext,
    request_id: str,
    now: int,
) -> ActivityReservation:
    """Cancel the observed revision once, preserving the reason and agreed price."""
    require_permission(context.permissions, WRITE_PERMISSION)

    def action():
        if (
            activity_reservations.find_by_id(connection, id, hotel_id=context.hotel_id)
            is None
        ):
            raise ValueError(
                "Reservation not found in this hotel. Look up the guest's itinerary first."
            )
        row = activity_reservations.cancel(
            connection,
            id,
            expected_revision=request.expected_revision,
            reason=request.reason,
            hotel_id=context.hotel_id,
            now=now,
        )
        return _reservation(row).model_dump(mode="json")

    saved = commands.execute(
        connection,
        RequestKey(
            actor_staff_member_id=context.staff_member_id,
            operation="activity-reservations.cancel",
            request_id=request_id,
        ),
        {
            "hotel_id": context.hotel_id,
            "id": id,
            "payload": request.model_dump(mode="json"),
        },
        action,
        now=now,
    )
    return ActivityReservation.model_validate(saved)


def _reservation(row: ActivityReservationRow) -> ActivityReservation:
    """Combine the saved agreement with the event's current title and times."""
    return ActivityReservation(
        id=row.id,
        revision=row.revision,
        guest_id=row.guest_id,
        party_id=row.party_id,
        activity=ReservedActivity(
            id=row.activity_id,
            venue_id=row.venue_id,
            title=row.title,
            date_range=DateRange(
                min_date=to_datetime(row.min_date), max_date=to_datetime(row.max_date)
            ),
        ),
        cancelled=row.cancelled,
        cancellation_reason=row.cancellation_reason,
        agreed_price=ActivityPrice(
            price_id=row.price_id,
            revision=row.price_revision,
            amount=NonNegativeAmount(value=row.amount_minor, currency=row.currency),
            unit=row.price_unit,
        ),
        effective=row.effective,
        created_at=to_datetime(row.created_at),
    )
