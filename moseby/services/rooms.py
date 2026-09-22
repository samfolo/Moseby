from collections.abc import Iterable

from sqlalchemy import Engine

from moseby.contracts.common import Page
from moseby.contracts.rooms import Bed, Room, SearchRoomsRequestPayload
from moseby.db.models.rooms import RoomFilters, RoomRow
from moseby.db.pagination import PageRequest
from moseby.db.repositories import rooms as rooms_repository
from moseby.db.timestamps import to_microseconds
from moseby.db.transaction import transaction
from moseby.domain.enums import RoomServiceStatus
from moseby.identifiers import HotelId, RoomId
from moseby.permissions import Permission

from ._prices import nightly_price
from .access import require_permission

READ_PERMISSION = Permission("moseby.rooms:read")


def search(
    engine: Engine,
    request: SearchRoomsRequestPayload,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
) -> Page[Room]:
    """Search rooms within the caller's hotel after checking current read access."""
    require_permission(permissions, READ_PERMISSION)

    filters = request.model_dump(exclude={"cursor", "limit"})
    if request.availability_date_range is not None:
        filters["availability_date_range"] = {
            "min_date": to_microseconds(request.availability_date_range.min_date),
            "max_date": to_microseconds(request.availability_date_range.max_date),
        }

    with transaction(engine) as connection:
        page = rooms_repository.search(
            connection,
            RoomFilters.model_validate(filters),
            hotel_id=hotel_id,
            page=PageRequest(cursor=request.cursor, limit=request.limit),
        )
    return Page[Room](
        items=[_room(row) for row in page.items], next_cursor=page.next_cursor
    )


def get(
    engine: Engine,
    id: RoomId,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
) -> Room | None:
    """Read a room in this hotel with its beds and current rate, or return None."""
    require_permission(permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        row = rooms_repository.find_by_id(connection, id, hotel_id=hotel_id)
    return _room(row) if row is not None else None


def _room(row: RoomRow) -> Room:
    """Present beds and the current rate without exposing database timestamps."""
    return Room(
        id=row.id,
        hotel_id=row.hotel_id,
        label=row.label,
        description=row.description,
        tier=row.tier,
        number_of_bathrooms=row.number_of_bathrooms,
        service_status=(
            RoomServiceStatus.IN_SERVICE
            if row.in_service
            else RoomServiceStatus.OUT_OF_SERVICE
        ),
        beds=[Bed(id=bed.id, type=bed.type) for bed in row.beds],
        price=nightly_price(
            row.price_id, row.price_revision, row.amount_minor, row.currency
        ),
    )
