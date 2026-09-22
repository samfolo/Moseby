"""Reserve and cancel guest places within a hotel."""

from sqlalchemy import Connection, Select, and_, insert, select

from moseby.domain.enums import BookingStatus
from moseby.identifiers import (
    ActivityId,
    ActivityReservationId,
    GuestId,
    HotelId,
    PartyId,
)

from ..errors import ActivityAlreadyReserved, WriteConflict
from ..models.activity_reservations import (
    ActivityReservationFilters,
    ActivityReservationRow,
    ReserveActivity,
)
from ..models.filters import DateRange
from ..pagination import Page, PageRequest, read_page
from ..tables import (
    activities,
    activity_reservation_revisions,
    activity_reservations,
    price_versions,
)
from . import activities as activities_repository
from . import bookings as bookings_repository
from . import guests as guests_repository
from . import parties as parties_repository
from ._activity_queries import current_reservations, effective_count
from ._stay_queries import require_coverage
from ._writes import (
    check_history_time,
    check_revision,
    require_found,
    require_reason,
    require_write_transaction,
)


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


# Writes


def reserve(
    connection: Connection, values: ReserveActivity, *, hotel_id: HotelId, now: int
) -> list[ActivityReservationRow]:
    """Reserve the whole group or none of it, checking age, stay coverage and capacity.

    Guests can come from different parties in this hotel. Overlapping activities
    are allowed; a second effective place for the same guest and event is not.
    """
    require_write_transaction(connection)

    # Check the event and group size while competing reservation writes are held back.
    activity = require_found(
        activities_repository.find_by_id(connection, values.activity_id)
    )
    count = len(values.attendees)
    if not activity.min_booking_size <= count <= activity.max_booking_size:
        raise WriteConflict(
            f"This activity accepts groups of {activity.min_booking_size} to {activity.max_booking_size}; {count} guests were requested"
        )
    if now >= activity.min_date:
        raise WriteConflict("The activity has already started")

    # Resolve every attendee inside this hotel before reporting any saved reservations.
    people = guests_repository.find_by_ids(
        connection, [item.guest_id for item in values.attendees], hotel_id=hotel_id
    )
    if len(people) != count:
        raise WriteConflict("Every attendee must be a guest in this hotel")

    # Use current effective rows so cancelled places and old revisions do not count.
    current = current_reservations().subquery()
    duplicates = connection.execute(
        select(current.c.guest_id, current.c.id)
        .where(
            current.c.hotel_id == hotel_id,
            current.c.activity_id == activity.id,
            current.c.guest_id.in_(people),
            current.c.effective.is_(True),
        )
        .order_by(current.c.guest_id)
    )
    reservations_by_guest = {guest_id: id for guest_id, id in duplicates}
    if reservations_by_guest:
        raise ActivityAlreadyReserved(activity.id, reservations_by_guest)

    # All requested guests need new places; the count includes attendees from every hotel.
    if (
        activity.capacity is not None
        and activity.reserved_places + count > activity.capacity
    ):
        raise WriteConflict(
            f"The activity has {activity.capacity - activity.reserved_places} places remaining; {count} were requested"
        )

    # Each guest needs an eligible booking, sufficient age and rooms covering the event.
    for person in people.values():
        party = require_found(
            parties_repository.find_by_id(
                connection, person.party_id, hotel_id=hotel_id
            )
        )
        booking = require_found(
            bookings_repository.find_by_id(
                connection, party.booking_id, hotel_id=hotel_id
            )
        )
        if booking.status != BookingStatus.CONFIRMED or now < max(
            booking.updated_at, person.updated_at, activity.updated_at
        ):
            raise WriteConflict(
                "New activity reservations require a confirmed stay and current timestamp"
            )
        if person.age < activity.minimum_age:
            raise WriteConflict(
                f"Guest {person.id} does not meet the minimum age of {activity.minimum_age}"
            )
        require_coverage(
            connection,
            booking.id,
            DateRange(min_date=activity.min_date, max_date=activity.max_date),
        )

    # Save the entire group together, even if the caller catches a later insert failure.
    with connection.begin_nested():
        for item in values.attendees:
            connection.execute(
                insert(activity_reservations).values(
                    id=item.id,
                    guest_id=item.guest_id,
                    party_id=people[item.guest_id].party_id,
                    activity_id=activity.id,
                    created_at=now,
                )
            )
            # Pin the rate accepted now so later price changes preserve this agreement.
            connection.execute(
                insert(activity_reservation_revisions).values(
                    activity_reservation_id=item.id,
                    revision=1,
                    cancelled=False,
                    price_id=activity.price_id,
                    price_revision=activity.price_revision,
                    price_unit=activity.price_unit,
                    created_at=now,
                )
            )
        return [
            require_found(find_by_id(connection, item.id, hotel_id=hotel_id))
            for item in values.attendees
        ]


def cancel(
    connection: Connection,
    id: ActivityReservationId,
    *,
    expected_revision: int,
    reason: str,
    hotel_id: HotelId,
    now: int,
) -> ActivityReservationRow:
    """Cancel one guest's place permanently without changing the rest of their group."""
    require_write_transaction(connection)
    require_reason(reason)

    # The caller must cancel the revision it read, at a time consistent with its history.
    saved = require_found(find_by_id(connection, id, hotel_id=hotel_id))
    check_revision(saved.revision, expected_revision)
    check_history_time(
        connection, activity_reservation_revisions, "activity_reservation_id", id, now
    )
    if saved.cancelled or now < saved.created_at:
        raise WriteConflict(
            "The reservation is already cancelled or the timestamp is stale"
        )
    # Append the cancellation with the original rate; current-state reads release the place.
    connection.execute(
        insert(activity_reservation_revisions).values(
            activity_reservation_id=id,
            revision=saved.revision + 1,
            cancelled=True,
            cancellation_reason=reason,
            price_id=saved.price_id,
            price_revision=saved.price_revision,
            price_unit=saved.price_unit,
            created_at=now,
        )
    )
    return require_found(find_by_id(connection, id, hotel_id=hotel_id))
