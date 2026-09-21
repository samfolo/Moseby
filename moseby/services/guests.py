"""Guest discovery shared by HTTP routes and agent tools."""

from collections.abc import Iterable

from sqlalchemy import Engine

from moseby.contracts.common import Page
from moseby.contracts.guests import Guest, SearchGuestsRequestPayload
from moseby.db.models.guests import GuestFilters, GuestRow
from moseby.db.pagination import PageRequest
from moseby.db.repositories import guests as guests_repository
from moseby.db.transaction import transaction
from moseby.identifiers import GuestId, HotelId
from moseby.permissions import Permission

from .access import require_permission

READ_PERMISSION = Permission("moseby.guests:read")


def search(
    engine: Engine,
    request: SearchGuestsRequestPayload,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
) -> Page[Guest]:
    """Find matching guests in the caller's hotel, including previous stays."""
    require_permission(permissions, READ_PERMISSION)
    filters = GuestFilters.model_validate(
        request.model_dump(exclude={"cursor", "limit"})
    )
    with transaction(engine) as connection:
        page = guests_repository.search(
            connection,
            filters,
            hotel_id=hotel_id,
            page=PageRequest(cursor=request.cursor, limit=request.limit),
        )
    return Page[Guest](
        items=[_guest(row) for row in page.items], next_cursor=page.next_cursor
    )


def get(
    engine: Engine,
    id: GuestId,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
) -> Guest | None:
    """Read one guest; missing IDs and other hotels' guests both return None."""
    require_permission(permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        row = guests_repository.find_by_id(connection, id, hotel_id=hotel_id)
    return _guest(row) if row is not None else None


def _guest(row: GuestRow) -> Guest:
    return Guest.model_validate(row.model_dump(include=set(Guest.model_fields)))
