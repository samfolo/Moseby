"""Retrieve saved party evidence with its classification outcome."""

from collections.abc import Iterable

from sqlalchemy import Engine

from moseby.contracts.common import Page
from moseby.contracts.party_details import PartyDetail, SearchPartyDetailsRequestPayload
from moseby.db.models.party_details import PartyDetailFilters, PartyDetailRow
from moseby.db.pagination import PageRequest
from moseby.db.repositories import party_details
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.identifiers import HotelId, PartyDetailId
from moseby.permissions import Permission

from .access import require_permission
from .guests import READ_PERMISSION as READ_PERMISSION


def to_contract(row: PartyDetailRow) -> PartyDetail:
    return PartyDetail.model_validate(
        row.model_dump(exclude={"updated_at"})
        | {"created_at": to_datetime(row.created_at)}
    )


def search(
    engine: Engine,
    request: SearchPartyDetailsRequestPayload,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
) -> Page[PartyDetail]:
    """Find notes in the selected parties, keeping unresolved evidence visible."""
    require_permission(permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        page = party_details.search(
            connection,
            PartyDetailFilters.model_validate(
                request.model_dump(exclude={"cursor", "limit"})
            ),
            hotel_id=hotel_id,
            page=PageRequest(cursor=request.cursor, limit=request.limit),
        )
    return Page[PartyDetail](
        items=[to_contract(row) for row in page.items], next_cursor=page.next_cursor
    )


def get(
    engine: Engine,
    id: PartyDetailId,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
) -> PartyDetail | None:
    """Return one note, or None when its ID is missing or outside this hotel."""
    require_permission(permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        row = party_details.find_by_id(connection, id, hotel_id=hotel_id)
    return to_contract(row) if row is not None else None
