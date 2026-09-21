"""Read and configure dated activities and their available places."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, and_, func, insert, or_, select
from sqlalchemy import update as sql_update

from moseby.identifiers import ActivityId

from ..errors import WriteConflict
from ..models.activities import (
    ActivityFilters,
    ActivityRow,
    ActivityValues,
    NewActivity,
)
from ..pagination import Page, PageRequest, read_page
from ..tables import activities, price_versions
from ..tables import guests as guests_table
from . import prices as prices_repository
from ._activity_queries import current_reservations, effective_count
from ._queries import latest_revision, unique_ids
from ._writes import check_updated_at, require_found, require_write_transaction


def _select() -> Select:
    """Attach the current price and count of reserved guest places to each event.

    The price join selects one version. The count includes every hotel's guests
    without joining individual attendees into the result, keeping one row per event.
    """
    return select(
        activities,
        price_versions.c.revision.label("price_revision"),
        price_versions.c.amount_minor,
        price_versions.c.currency,
        effective_count(activities.c.id).label("reserved_places"),
    ).join(
        price_versions,
        and_(
            price_versions.c.price_id == activities.c.price_id,
            price_versions.c.revision
            == latest_revision(
                price_versions, price_versions.c.price_id, activities.c.price_id
            ),
        ),
    )


def find_by_id(connection: Connection, id: ActivityId) -> ActivityRow | None:
    """Fetch a shared activity with its current price and reserved-place count.

    Include past and fully booked events. Return None when the ID is missing.
    """
    row = (
        connection.execute(_select().where(activities.c.id == id))
        .mappings()
        .one_or_none()
    )
    return ActivityRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection, ids: Sequence[ActivityId]
) -> dict[ActivityId, ActivityRow]:
    """Fetch up to 100 supplied activity IDs as a dictionary, omitting missing IDs.

    Repeats appear once and empty input returns an empty dictionary. More than
    100 input IDs raises ValueError, counting repeats towards the limit.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(_select().where(activities.c.id.in_(ids))).mappings()
    return {row["id"]: ActivityRow.model_validate(dict(row)) for row in rows}


def find_all(
    connection: Connection, *, page: PageRequest | None = None
) -> Page[ActivityRow]:
    """Fetch a page of shared activities, including past and fully booked events.

    Order by creation time, then ID. Pass next_cursor to continue the same list.
    """
    return search(connection, ActivityFilters(), page=page)


def search(
    connection: Connection,
    filters: ActivityFilters,
    *,
    page: PageRequest | None = None,
) -> Page[ActivityRow]:
    """Fetch a page matching all supplied filters, ordered by creation time, then ID.

    Match any value within a list. Date ranges overlap when they share time;
    touching endpoints do not overlap. Unlimited activities satisfy any positive
    places_required. Availability is a read of current state, not a reservation.
    """
    statement = _select()
    for column, values in (
        (activities.c.id, filters.ids),
        (activities.c.venue_id, filters.venue_ids),
        (activities.c.type, filters.types),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    if filters.date_range is not None:
        statement = statement.where(
            activities.c.min_date < filters.date_range.max_date,
            activities.c.max_date > filters.date_range.min_date,
        )
    if filters.places_required is not None:
        statement = statement.where(
            or_(
                activities.c.capacity.is_(None),
                activities.c.capacity - effective_count(activities.c.id)
                >= filters.places_required,
            )
        )
    return read_page(
        connection,
        statement,
        table=activities,
        row_type=ActivityRow,
        page=page or PageRequest(),
        query="activities.search",
        criteria={"filters": filters.model_dump_json()},
    )


# Writes


def _values(values: ActivityValues) -> dict:
    return values.model_dump(exclude={"date_range"}) | values.date_range.model_dump()


def create(connection: Connection, values: NewActivity, *, now: int) -> ActivityRow:
    """Create a dated activity using an existing venue, activity type and price."""
    require_write_transaction(connection)
    require_found(prices_repository.find_by_id(connection, values.price_id))
    connection.execute(
        insert(activities).values(**_values(values), created_at=now, updated_at=now)
    )
    return require_found(find_by_id(connection, values.id))


def update_details(
    connection: Connection,
    id: ActivityId,
    values: ActivityValues,
    *,
    expected_updated_at: int,
    now: int,
) -> ActivityRow:
    """Replace activity settings without excluding existing attendees or exceeding capacity.

    Moving a booked event requires notification delivery, so reject changes to
    its times or venue while it has effective reservations.
    """
    require_write_transaction(connection)
    saved = require_found(find_by_id(connection, id))
    check_updated_at(saved.updated_at, expected_updated_at, now)
    require_found(prices_repository.find_by_id(connection, values.price_id))

    # Existing attendees retain their places when activity settings change.
    if values.capacity is not None and values.capacity < saved.reserved_places:
        raise WriteConflict("Capacity cannot fall below the number of reserved places")
    if saved.reserved_places and (
        values.venue_id != saved.venue_id
        or values.date_range.min_date != saved.min_date
        or values.date_range.max_date != saved.max_date
    ):
        raise WriteConflict(
            "Changing a booked event's time or venue requires the notification workflow"
        )
    # The youngest effective attendee determines whether the new age limit is valid.
    current = current_reservations().subquery()
    youngest = connection.scalar(
        select(func.min(guests_table.c.age))
        .join(current, current.c.guest_id == guests_table.c.id)
        .where(current.c.activity_id == id, current.c.effective.is_(True))
    )
    if youngest is not None and youngest < values.minimum_age:
        raise WriteConflict("The new age limit would exclude an existing attendee")
    connection.execute(
        sql_update(activities)
        .where(activities.c.id == id)
        .values(**_values(values), updated_at=now)
    )
    return require_found(find_by_id(connection, id))
