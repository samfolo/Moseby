"""Issue and deactivate demo keys whose access follows the booked reservation."""

from collections.abc import Iterable

from sqlalchemy import Connection, Engine

from moseby.agents.models import AgentDomainContext
from moseby.contracts.common import Page, PageRequest
from moseby.contracts.room_keys import (
    DeactivateRoomKeyRequestPayload,
    IssueRoomKeyRequestPayload,
    RoomKey,
)
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.models.room_keys import RoomKeyRow
from moseby.db.operations import commands
from moseby.db.pagination import PageRequest as DatabasePageRequest
from moseby.db.repositories import room_keys, room_reservations
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.identifiers import HotelId, RoomKeyId, new_id
from moseby.permissions import Permission

from ._booking_access import READ_PERMISSION as READ_PERMISSION
from ._booking_access import WRITE_PERMISSION as WRITE_PERMISSION
from .access import require_permission


def to_contract(row: RoomKeyRow) -> RoomKey:
    return RoomKey(
        id=row.id,
        room_reservation_id=row.room_reservation_id,
        effective=row.effective,
        code=row.code,
        created_at=to_datetime(row.created_at),
        deactivated_at=to_datetime(row.deactivated_at)
        if row.deactivated_at is not None
        else None,
        deactivation_reason=row.deactivation_reason,
    )


def get(
    engine: Engine,
    id: RoomKeyId,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
    now: int,
) -> RoomKey | None:
    """Read a room key within the selected hotel and check its access at the supplied time."""
    require_permission(permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        row = room_keys.find_by_id(connection, id, hotel_id=hotel_id, now=now)
    return to_contract(row) if row is not None else None


def list_keys(
    engine: Engine,
    request: PageRequest,
    *,
    hotel_id: HotelId,
    permissions: Iterable[Permission],
    now: int,
) -> Page[RoomKey]:
    """List one flat page of this hotel's keys with their current effective access."""
    require_permission(permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        page = room_keys.find_all(
            connection,
            hotel_id=hotel_id,
            now=now,
            page=DatabasePageRequest(**request.model_dump()),
        )
    return Page[RoomKey](
        items=[to_contract(row) for row in page.items], next_cursor=page.next_cursor
    )


def issue(
    connection: Connection,
    request: IssueRoomKeyRequestPayload,
    *,
    context: AgentDomainContext,
    request_id: str,
    now: int,
) -> RoomKey:
    """Issue one key per accepted command; retrying the command returns that same key."""
    require_permission(context.permissions, WRITE_PERMISSION)

    def action():
        reservation = room_reservations.find_by_id(
            connection, request.room_reservation_id, hotel_id=context.hotel_id
        )
        if reservation is None:
            raise ValueError(
                "Room reservation not found in this hotel. Read the guest's stay and use its allocation ID."
            )
        row = room_keys.issue(
            connection,
            new_id("room_key"),
            reservation.id,
            code=request.code,
            hotel_id=context.hotel_id,
            now=now,
        )
        return to_contract(row).model_dump(mode="json")

    saved = commands.execute(
        connection,
        RequestKey(
            actor_staff_member_id=context.staff_member_id,
            operation="room-keys.issue",
            request_id=request_id,
        ),
        {"hotel_id": context.hotel_id, "payload": request.model_dump(mode="json")},
        action,
        now=now,
    )
    return RoomKey.model_validate(saved)


def deactivate(
    connection: Connection,
    id: RoomKeyId,
    request: DeactivateRoomKeyRequestPayload,
    *,
    context: AgentDomainContext,
    request_id: str,
    now: int,
) -> RoomKey:
    """Revoke the selected key while keeping other keys for the reservation usable."""
    require_permission(context.permissions, WRITE_PERMISSION)

    def action():
        if (
            room_keys.find_by_id(connection, id, hotel_id=context.hotel_id, now=now)
            is None
        ):
            raise ValueError(
                "Key not found in this hotel. Read the guest's stay and select one of its keys."
            )
        row = room_keys.deactivate(
            connection, id, reason=request.reason, hotel_id=context.hotel_id, now=now
        )
        return to_contract(row).model_dump(mode="json")

    saved = commands.execute(
        connection,
        RequestKey(
            actor_staff_member_id=context.staff_member_id,
            operation="room-keys.deactivate",
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
    return RoomKey.model_validate(saved)
