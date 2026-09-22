"""Guest discovery shared by HTTP routes and agent tools."""

from collections.abc import Iterable

from sqlalchemy import Connection, Engine

from moseby.agents.models import AgentDomainContext
from moseby.contracts.common import Page
from moseby.contracts.guests import (
    Guest,
    SearchGuestsRequestPayload,
    UpdateGuestRequest,
)
from moseby.db.errors import WriteConflict
from moseby.db.models.guests import GuestFilters, GuestRow, GuestValues
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.operations import commands
from moseby.db.pagination import PageRequest
from moseby.db.repositories import guests as guests_repository
from moseby.db.repositories import party_details
from moseby.db.timestamps import to_datetime, to_microseconds
from moseby.db.transaction import transaction
from moseby.identifiers import GuestId, HotelId
from moseby.permissions import Permission

from .access import require_permission

READ_PERMISSION = Permission("moseby.guests:read")
WRITE_PERMISSION = Permission("moseby.guests:write")


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
        items=[to_contract(row) for row in page.items], next_cursor=page.next_cursor
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
    return to_contract(row) if row is not None else None


def to_contract(row: GuestRow) -> Guest:
    return Guest.model_validate(
        row.model_dump(include=set(Guest.model_fields))
        | {"updated_at": to_datetime(row.updated_at)}
    )


def update(
    connection: Connection,
    id: GuestId,
    request: UpdateGuestRequest,
    *,
    context: AgentDomainContext,
    now: int,
) -> Guest:
    """Apply selected fields to the observed guest and retain the supporting note ID."""
    require_permission(context.permissions, READ_PERMISSION)
    require_permission(context.permissions, WRITE_PERMISSION)

    def action():
        saved = guests_repository.find_by_id(connection, id, hotel_id=context.hotel_id)
        if saved is None:
            raise ValueError(
                "Guest not found in this hotel. Search guests and use a returned ID."
            )
        if request.evidence_detail_id is not None:
            evidence = party_details.find_by_id(
                connection, request.evidence_detail_id, hotel_id=context.hotel_id
            )
            if evidence is None or evidence.party_id != saved.party_id:
                raise ValueError(
                    "The evidence note must belong to this guest's party. Save the reported change there first."
                )
        # Validate the merged guest so partial contact edits cannot leave invalid preferences.
        values = GuestValues.model_validate(
            {field: getattr(saved, field) for field in GuestValues.model_fields}
            | request.payload
        )
        if saved.updated_at != to_microseconds(request.expected_updated_at):
            raise WriteConflict(
                "The guest changed. Search the guest again and use the returned updated_at."
            )
        row = guests_repository.update_details(
            connection,
            id,
            values,
            expected_updated_at=to_microseconds(request.expected_updated_at),
            hotel_id=context.hotel_id,
            now=now,
        )
        return to_contract(row).model_dump(mode="json")

    saved = commands.execute(
        connection,
        RequestKey(
            actor_staff_member_id=context.staff_member_id,
            operation="guests.update",
            request_id=request.request_id,
        ),
        {
            "hotel_id": context.hotel_id,
            "id": id,
            **request.model_dump(mode="json", exclude={"request_id"}),
        },
        action,
        now=now,
    )
    return Guest.model_validate(saved)
