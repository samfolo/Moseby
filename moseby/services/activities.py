"""Browse the shared activity schedule and its current capacity."""

from collections.abc import Iterable

from sqlalchemy import Engine

from moseby.contracts.activities import (
    Activity,
    ActivityPrice,
    BookingSize,
    SearchActivitiesRequestPayload,
)
from moseby.contracts.amounts import NonNegativeAmount
from moseby.contracts.common import Page
from moseby.contracts.ranges import DateRange
from moseby.db.models.activities import ActivityFilters, ActivityRow
from moseby.db.pagination import PageRequest
from moseby.db.repositories import activities as activities_repository
from moseby.db.timestamps import to_datetime, to_microseconds
from moseby.db.transaction import transaction
from moseby.identifiers import ActivityId
from moseby.permissions import Permission

from .access import require_permission

READ_PERMISSION = Permission("moseby.activities:read")


def search(
    engine: Engine,
    request: SearchActivitiesRequestPayload,
    *,
    permissions: Iterable[Permission],
) -> Page[Activity]:
    """Find existing events with their current prices and reserved-place counts."""
    require_permission(permissions, READ_PERMISSION)
    filters = request.model_dump(exclude={"cursor", "limit"})
    if request.date_range is not None:
        filters["date_range"] = {
            "min_date": to_microseconds(request.date_range.min_date),
            "max_date": to_microseconds(request.date_range.max_date),
        }
    with transaction(engine) as connection:
        page = activities_repository.search(
            connection,
            ActivityFilters.model_validate(filters),
            page=PageRequest(cursor=request.cursor, limit=request.limit),
        )
    return Page[Activity](
        items=[_activity(row) for row in page.items], next_cursor=page.next_cursor
    )


def get(
    engine: Engine, id: ActivityId, *, permissions: Iterable[Permission]
) -> Activity | None:
    """Read an event, including past or fully booked events; return None if missing."""
    require_permission(permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        row = activities_repository.find_by_id(connection, id)
    return _activity(row) if row is not None else None


def _activity(row: ActivityRow) -> Activity:
    """Expose the event and its aggregate attendance without revealing guest details."""
    return Activity(
        id=row.id,
        venue_id=row.venue_id,
        title=row.title,
        type=row.type,
        description=row.description,
        date_range=DateRange(
            min_date=to_datetime(row.min_date), max_date=to_datetime(row.max_date)
        ),
        capacity=row.capacity,
        booking_size=BookingSize(
            min_value=row.min_booking_size, max_value=row.max_booking_size
        ),
        minimum_age=row.minimum_age,
        price=ActivityPrice(
            price_id=row.price_id,
            revision=row.price_revision,
            amount=NonNegativeAmount(value=row.amount_minor, currency=row.currency),
            unit=row.price_unit,
        ),
        reserved_places=row.reserved_places,
        created_at=to_datetime(row.created_at),
    )
