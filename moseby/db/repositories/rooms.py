"""Read hotel rooms with their current catalogue rate and complete bed configuration."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, and_, func, select
from sqlalchemy.sql.selectable import Exists

from moseby.domain.enums import BookingStatus, RoomServiceStatus
from moseby.identifiers import HotelId, RoomId

from ..models.filters import DateRange
from ..models.rooms import BedRow, RoomFilters, RoomRow
from ..pagination import Page, PageRequest, read_page
from ..tables import (
    beds,
    booking_revisions,
    price_versions,
    room_reservation_revisions,
    room_reservations,
    rooms,
)
from ._queries import latest_revision, unique_ids


def _select(hotel_id: HotelId) -> Select:
    """Join one current price per room and apply the hotel's boundary before paging."""
    return (
        select(
            rooms,
            price_versions.c.revision.label("price_revision"),
            price_versions.c.amount_minor,
            price_versions.c.currency,
        )
        .join(
            price_versions,
            and_(
                price_versions.c.price_id == rooms.c.price_id,
                price_versions.c.revision
                == latest_revision(
                    price_versions, price_versions.c.price_id, rooms.c.price_id
                ),
            ),
        )
        .where(rooms.c.hotel_id == hotel_id)
    )


def _with_beds(connection: Connection, rows: list[RoomRow]) -> list[RoomRow]:
    """Fetch all beds for these already-scoped rooms in one additional query.

    Rooms with no beds keep an empty list. Paging rooms before fetching beds
    prevents a room with several beds from using several places in the page.
    """
    if not rows:
        return []
    grouped: dict[RoomId, list[BedRow]] = {row.id: [] for row in rows}
    found = connection.execute(
        select(beds)
        .where(beds.c.room_id.in_(grouped))
        .order_by(beds.c.created_at, beds.c.id)
    ).mappings()
    for values in found:
        bed = BedRow.model_validate(dict(values))
        grouped[bed.room_id].append(bed)
    return [row.model_copy(update={"beds": grouped[row.id]}) for row in rows]


def find_by_id(
    connection: Connection, id: RoomId, *, hotel_id: HotelId
) -> RoomRow | None:
    """Fetch a room, its current price and all its beds, including out-of-service rooms.

    Return None if the ID is missing, belongs to another hotel or has no price
    version. This reads configuration; it does not claim dated availability.
    """
    values = (
        connection.execute(_select(hotel_id).where(rooms.c.id == id))
        .mappings()
        .one_or_none()
    )
    if values is None:
        return None
    return _with_beds(connection, [RoomRow.model_validate(dict(values))])[0]


def find_by_ids(
    connection: Connection, ids: Sequence[RoomId], *, hotel_id: HotelId
) -> dict[RoomId, RoomRow]:
    """Fetch up to 100 supplied room IDs with current prices and all their beds.

    Return a dictionary of found rooms; omit missing, unpriced or other hotels'
    rooms. Repeats appear once and empty input returns an empty dictionary. More
    than 100 input IDs raises ValueError. Use two queries for a nonempty result.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    values = connection.execute(_select(hotel_id).where(rooms.c.id.in_(ids))).mappings()
    rows = _with_beds(connection, [RoomRow.model_validate(dict(row)) for row in values])
    return {row.id: row for row in rows}


def find_all(
    connection: Connection, *, hotel_id: HotelId, page: PageRequest | None = None
) -> Page[RoomRow]:
    """Fetch this hotel's priced rooms, ordered by creation time, then ID.

    Include out-of-service rooms and all beds for each returned room. Each room
    occupies one page entry; pass next_cursor to continue the room list.
    """
    return search(connection, RoomFilters(), hotel_id=hotel_id, page=page)


def _overlapping_reservation(date_range: DateRange) -> Exists:
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
            revision.cancelled.is_(False),
            booking_revisions.c.status == BookingStatus.CONFIRMED.value,
            revision.min_date < date_range.max_date,
            revision.max_date > date_range.min_date,
        )
        .correlate(rooms)
        .exists()
    )


def _search_statement(hotel_id: HotelId, filters: RoomFilters) -> Select:
    """Apply all filters to one row per room before ordering or limiting the query.

    Bed counts and existence checks avoid joining each bed into the room page.
    The price comparison uses the single current catalogue revision.
    """
    statement = _select(hotel_id)
    for column, values in (
        (rooms.c.hotel_id, filters.hotel_ids),
        (rooms.c.id, filters.ids),
        (rooms.c.tier, filters.tiers),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    if filters.service_statuses is not None:
        in_service = [
            status == RoomServiceStatus.IN_SERVICE
            for status in filters.service_statuses
        ]
        statement = statement.where(rooms.c.in_service.in_(in_service))
    for bed_type in filters.bed_types or ():
        statement = statement.where(
            select(1)
            .select_from(beds)
            .where(beds.c.room_id == rooms.c.id, beds.c.type == bed_type)
            .correlate(rooms)
            .exists()
        )
    bed_count = (
        select(func.count())
        .select_from(beds)
        .where(beds.c.room_id == rooms.c.id)
        .correlate(rooms)
        .scalar_subquery()
    )
    for value, bounds in (
        (bed_count, filters.number_of_beds),
        (rooms.c.number_of_bathrooms, filters.number_of_bathrooms),
        (price_versions.c.amount_minor, filters.nightly_amount),
    ):
        if bounds is not None:
            if bounds.min_value is not None:
                statement = statement.where(value >= bounds.min_value)
            if bounds.max_value is not None:
                statement = statement.where(value <= bounds.max_value)
    if filters.nightly_amount is not None:
        statement = statement.where(
            price_versions.c.currency == filters.nightly_amount.currency
        )
    if filters.availability_date_range is not None:
        statement = statement.where(
            rooms.c.in_service.is_(True),
            ~_overlapping_reservation(filters.availability_date_range),
        )
    return statement


def search(
    connection: Connection,
    filters: RoomFilters,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[RoomRow]:
    """Fetch matching rooms in creation-time and ID order, with all their beds.

    Apply filters before pagination. Match any ID, tier or service status in each
    list, but require every requested bed type. Amount bounds are inclusive and
    use the supplied currency. A hotel filter can only narrow the service's scope.

    A date range requires an in-service room with no overlapping current
    reservation on a confirmed booking. Omitting it ignores dated availability.
    Search observes capacity; the booking service must recheck it when reserving.
    """
    result = read_page(
        connection,
        _search_statement(hotel_id, filters),
        table=rooms,
        row_type=RoomRow,
        page=page or PageRequest(),
        query="rooms.search",
        criteria={"hotel_id": hotel_id, "filters": filters.model_dump_json()},
    )
    return result.model_copy(update={"items": _with_beds(connection, result.items)})
