"""Read guest itineraries within a hotel and count shared activity places."""

from sqlalchemy import Connection, Select, and_, select

from moseby.identifiers import (
    ActivityId,
    ActivityReservationId,
    GuestId,
    HotelId,
    PartyId,
)

from ..models.activity_reservations import (
    ActivityReservationFilters,
    ActivityReservationRow,
)
from ..pagination import Page, PageRequest, read_page
from ..tables import activities, activity_reservations, price_versions
from ._activity_queries import current_reservations, effective_count


def _select(hotel_id: HotelId) -> Select:
    """Read current reservations with their agreed price and the event's current dates.

    Party membership determines the hotel boundary. Price joins use the saved
    version, so catalogue changes cannot rewrite what the guest agreed to pay.
    Each join selects one matching row per reservation.
    """
    statement = current_reservations()
    current = statement.selected_columns
    return (
        statement.add_columns(
            price_versions.c.amount_minor,
            price_versions.c.currency,
            activities.c.venue_id,
            activities.c.title,
            activities.c.min_date,
            activities.c.max_date,
        )
        .join(activities, activity_reservations.c.activity_id == activities.c.id)
        .join(
            price_versions,
            and_(
                price_versions.c.price_id == current.price_id,
                price_versions.c.revision == current.price_revision,
            ),
        )
        .where(current.hotel_id == hotel_id)
    )


def find_by_id(
    connection: Connection, id: ActivityReservationId, *, hotel_id: HotelId
) -> ActivityReservationRow | None:
    """Fetch the latest reservation, including cancelled or otherwise ineffective ones.

    Return None if the ID is missing or belongs to another hotel.
    """
    row = (
        connection.execute(_select(hotel_id).where(activity_reservations.c.id == id))
        .mappings()
        .one_or_none()
    )
    return ActivityReservationRow.model_validate(dict(row)) if row is not None else None


def find_all(
    connection: Connection, *, hotel_id: HotelId, page: PageRequest | None = None
) -> Page[ActivityReservationRow]:
    """Fetch a page of this hotel's effective reservations, including past events.

    Order by creation time, then ID. Use search to include ineffective reservations.
    """
    return search(
        connection, ActivityReservationFilters(), hotel_id=hotel_id, page=page
    )


def find_all_by_guest_id(
    connection: Connection,
    guest_id: GuestId,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[ActivityReservationRow]:
    """Fetch a page of the guest's effective reservations, including past events.

    Order by creation time, then ID. A missing or other hotel's guest gives an
    empty page. Event times are included for the caller to display an itinerary.
    """
    return search(
        connection,
        ActivityReservationFilters(guest_ids=[guest_id]),
        hotel_id=hotel_id,
        page=page,
    )


def find_all_by_party_id(
    connection: Connection,
    party_id: PartyId,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[ActivityReservationRow]:
    """Fetch one flat page of effective reservations for this party's guests.

    Order by creation time, then ID. A missing or other hotel's party gives an
    empty page. Each row identifies its guest and activity.
    """
    return search(
        connection,
        ActivityReservationFilters(party_ids=[party_id]),
        hotel_id=hotel_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: ActivityReservationFilters,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[ActivityReservationRow]:
    """Fetch one page matching all filters, ordered by creation time, then ID.

    Match any ID within each list. Effective defaults to true; false selects
    ineffective reservations and None includes both. Cancellation is an independent
    filter. Date ranges overlap current event times, excluding touching endpoints.
    """
    statement = _select(hotel_id)
    columns = statement.selected_columns
    for column, values in (
        (columns.guest_id, filters.guest_ids),
        (columns.party_id, filters.party_ids),
        (columns.booking_id, filters.booking_ids),
        (columns.activity_id, filters.activity_ids),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    if filters.effective is not None:
        statement = statement.where(columns.effective.is_(filters.effective))
    if filters.cancelled is not None:
        statement = statement.where(columns.cancelled.is_(filters.cancelled))
    if filters.date_range is not None:
        statement = statement.where(
            columns.min_date < filters.date_range.max_date,
            columns.max_date > filters.date_range.min_date,
        )
    return read_page(
        connection,
        statement,
        table=activity_reservations,
        row_type=ActivityReservationRow,
        page=page or PageRequest(),
        query="activity_reservations.search",
        criteria={"hotel_id": hotel_id, "filters": filters.model_dump_json()},
    )


def count_effective_by_activity_id(
    connection: Connection, activity_id: ActivityId
) -> int:
    """Count effective guest places across all hotels, without loading attendees.

    Return zero for an activity with no effective reservations or a missing ID.
    This complete count is independent of pagination; it does not reserve places.
    """
    return connection.execute(select(effective_count(activity_id))).scalar_one()
