"""Compose booking, party and room operations under one hotel and transaction."""

from collections.abc import Callable, Iterable

from sqlalchemy import Connection, Engine

from moseby.agents.models import AgentDomainContext
from moseby.common.types import JsonObject
from moseby.contracts.bookings import Booking, RoomReservation
from moseby.contracts.common import Page, PageRequest
from moseby.contracts.parties import Party
from moseby.contracts.ranges import DateRange
from moseby.contracts.rooms import NightlyPrice
from moseby.contracts.stays import (
    AmendStayRequestPayload,
    CancelStayRequestPayload,
    CompleteStayRequestPayload,
    CreateStayRequestPayload,
    GetStayRequestPayload,
    Stay,
)
from moseby.db.errors import WriteConflict
from moseby.db.models.bookings import NewBooking
from moseby.db.models.filters import DateRange as StoredDateRange
from moseby.db.models.guests import NewGuest
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.models.room_reservations import NewRoomReservation, RoomReservationValues
from moseby.db.models.stays import NewStay
from moseby.db.operations import commands
from moseby.db.operations import stays as stay_operations
from moseby.db.pagination import Page as DatabasePage
from moseby.db.pagination import PageRequest as DatabasePageRequest
from moseby.db.repositories import bookings, guests, parties, room_reservations, rooms
from moseby.db.timestamps import to_datetime, to_microseconds
from moseby.db.transaction import transaction
from moseby.identifiers import BookingId, HotelId, RoomId, new_id
from moseby.permissions import Permission

from . import guests as guest_service
from ._prices import nightly_price
from .access import require_permission

READ_PERMISSION = Permission("moseby.bookings:read")
WRITE_PERMISSION = Permission("moseby.bookings:write")
READ_PERMISSIONS = (READ_PERMISSION, guest_service.READ_PERMISSION)
WRITE_PERMISSIONS = (*READ_PERMISSIONS, WRITE_PERMISSION)
CREATE_PERMISSIONS = (*WRITE_PERMISSIONS, guest_service.WRITE_PERMISSION)


def _all_rows[T](fetch: Callable[[DatabasePageRequest], DatabasePage[T]]) -> list[T]:
    """Read every page when assembling one stay, including large parties and old allocations."""
    rows = []
    cursor = None
    while True:
        page = fetch(DatabasePageRequest(limit=100, cursor=cursor))
        rows.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return rows


def _booking(connection: Connection, id: BookingId, hotel_id: HotelId) -> Booking:
    row = bookings.find_by_id(connection, id, hotel_id=hotel_id)
    if row is None:
        raise ValueError(
            "Booking not found in this hotel. Find the guest and look up their stay."
        )
    # Include cancelled allocations so staff can see what changed during the stay.
    allocations = _all_rows(
        lambda page: room_reservations.find_all_by_booking_id(
            connection, id, hotel_id=hotel_id, page=page
        )
    )
    return Booking(
        id=row.id,
        hotel_id=row.hotel_id,
        name=row.name,
        revision=row.revision,
        status=row.status,
        cancellation_reason=row.cancellation_reason,
        created_at=to_datetime(row.created_at),
        room_reservations=[
            RoomReservation(
                id=item.id,
                revision=item.revision,
                room_id=item.room_id,
                date_range=DateRange(
                    min_date=to_datetime(item.min_date),
                    max_date=to_datetime(item.max_date),
                ),
                cancelled=item.cancelled,
                cancellation_reason=item.cancellation_reason,
                nightly_price=nightly_price(
                    item.price_id, item.price_revision, item.amount_minor, item.currency
                ),
            )
            for item in allocations
        ],
    )


def _stay(connection: Connection, id: BookingId, hotel_id: HotelId) -> Stay:
    booking = _booking(connection, id, hotel_id)
    party = parties.find_by_booking_id(connection, id, hotel_id=hotel_id)
    if party is None:
        raise WriteConflict(
            "The booking has no party; staff must check the saved booking."
        )
    people = _all_rows(
        lambda page: guests.find_all_by_party_id(
            connection, party.id, hotel_id=hotel_id, page=page
        )
    )
    return Stay(
        booking=booking,
        party=Party(
            id=party.id, booking_id=id, created_at=to_datetime(party.created_at)
        ),
        guests=[guest_service.to_contract(person) for person in people],
    )


def get(
    engine: Engine, request: GetStayRequestPayload, *, context: AgentDomainContext
) -> Stay:
    """Resolve one stay by booking or guest ID within a consistent snapshot."""
    for permission in READ_PERMISSIONS:
        require_permission(context.permissions, permission)
    with transaction(engine) as connection:
        id = request.booking_id
        # Each guest belongs to one visit, so their party identifies a single booking.
        if request.guest_id is not None:
            person = guests.find_by_id(
                connection, request.guest_id, hotel_id=context.hotel_id
            )
            if person is None:
                raise ValueError(
                    "Guest not found in this hotel. Search guests and use a returned ID."
                )
            party = parties.find_by_id(
                connection, person.party_id, hotel_id=context.hotel_id
            )
            if party is None:
                raise WriteConflict("The guest has no accessible party.")
            id = party.booking_id
        return _stay(connection, id, context.hotel_id)


def get_booking(
    engine: Engine, id: BookingId, *, context: AgentDomainContext
) -> Booking:
    require_permission(context.permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        return _booking(connection, id, context.hotel_id)


def list_bookings(
    engine: Engine, request: PageRequest, *, context: AgentDomainContext
) -> Page[Booking]:
    require_permission(context.permissions, READ_PERMISSION)
    with transaction(engine) as connection:
        page = bookings.find_all(
            connection,
            hotel_id=context.hotel_id,
            page=DatabasePageRequest(**request.model_dump()),
        )
        return Page[Booking](
            items=[
                _booking(connection, row.id, context.hotel_id) for row in page.items
            ],
            next_cursor=page.next_cursor,
        )


def _check_quote(
    connection: Connection, room_id: RoomId, quote: NightlyPrice, hotel_id: HotelId
) -> None:
    room = rooms.find_by_id(connection, room_id, hotel_id=hotel_id)
    if room is None:
        raise ValueError(f"Room {room_id} not found in this hotel. Search rooms again.")
    if quote != nightly_price(
        room.price_id, room.price_revision, room.amount_minor, room.currency
    ):
        raise WriteConflict(
            f"The price for room {room_id} changed. Search rooms and confirm the new rate before booking."
        )


def _dates(value: DateRange) -> StoredDateRange:
    return StoredDateRange(
        min_date=to_microseconds(value.min_date),
        max_date=to_microseconds(value.max_date),
    )


def _command(
    connection: Connection,
    *,
    context: AgentDomainContext,
    request_id: str,
    operation: str,
    request: JsonObject,
    action: Callable[[], BookingId],
    now: int,
    permissions: Iterable[Permission] = WRITE_PERMISSIONS,
) -> Stay:
    """Check access before replay, then save all changes and the response together."""
    for permission in permissions:
        require_permission(context.permissions, permission)

    def apply():
        # Capture the response before committing, so retries see this exact outcome.
        id = action()
        return _stay(connection, id, context.hotel_id).model_dump(mode="json")

    saved = commands.execute(
        connection,
        RequestKey(
            actor_staff_member_id=context.staff_member_id,
            operation=operation,
            request_id=request_id,
        ),
        {"hotel_id": context.hotel_id, **request},
        apply,
        now=now,
    )
    return Stay.model_validate(saved)


def create(
    connection: Connection,
    request: CreateStayRequestPayload,
    *,
    context: AgentDomainContext,
    request_id: str,
    now: int,
) -> Stay:
    """Confirm the party and all rooms together, using the displayed rates."""

    def action():
        # Check every displayed quote before creating the booking or its guests.
        for room in request.rooms:
            if to_microseconds(room.date_range.max_date) <= now:
                raise ValueError(
                    "A new stay must end in the future. Check the requested dates."
                )
            _check_quote(connection, room.room_id, room.quoted_price, context.hotel_id)
        # The composed operation saves the whole party and checks room capacity together.
        booking_id, party_id = new_id("booking"), new_id("party")
        stay_operations.create(
            connection,
            NewStay(
                booking=NewBooking(id=booking_id, name=request.name),
                party_id=party_id,
                guests=[
                    NewGuest(
                        id=new_id("guest"), party_id=party_id, **person.model_dump()
                    )
                    for person in request.guests
                ],
                rooms=[
                    NewRoomReservation(
                        id=new_id("room_reservation"),
                        booking_id=booking_id,
                        room_id=room.room_id,
                        date_range=_dates(room.date_range),
                        price_id=room.quoted_price.price_id,
                        price_revision=room.quoted_price.revision,
                    )
                    for room in request.rooms
                ],
            ),
            hotel_id=context.hotel_id,
            now=now,
        )
        return booking_id

    return _command(
        connection,
        context=context,
        request_id=request_id,
        operation="stays.create",
        request={"payload": request.model_dump(mode="json")},
        action=action,
        now=now,
        permissions=CREATE_PERMISSIONS,
    )


def amend(
    connection: Connection,
    id: BookingId,
    request: AmendStayRequestPayload,
    *,
    context: AgentDomainContext,
    request_id: str,
    now: int,
) -> Stay:
    """Revise dates or replace a room; rejected changes leave the original allocation intact."""

    def action():
        old = room_reservations.find_by_id(
            connection, request.room_reservation_id, hotel_id=context.hotel_id
        )
        # A valid allocation ID must also belong to the booking being amended.
        if old is None or old.booking_id != id:
            raise ValueError(
                "Room reservation not found on this booking. Read the stay again."
            )
        values = RoomReservationValues(
            date_range=_dates(request.date_range),
            price_id=request.quoted_price.price_id,
            price_revision=request.quoted_price.revision,
        )
        if old.room_id == request.room_id:
            # Date changes retain the rate already agreed for this allocation.
            if request.quoted_price != nightly_price(
                old.price_id, old.price_revision, old.amount_minor, old.currency
            ):
                raise WriteConflict(
                    "Use the allocation's agreed nightly price from the stay lookup."
                )
            room_reservations.revise(
                connection,
                old.id,
                values,
                expected_revision=request.expected_revision,
                hotel_id=context.hotel_id,
                now=now,
            )
        else:
            # Reserve the replacement and cancel the old allocation in one transaction.
            _check_quote(
                connection, request.room_id, request.quoted_price, context.hotel_id
            )
            stay_operations.move_room(
                connection,
                old.id,
                NewRoomReservation(
                    id=new_id("room_reservation"),
                    booking_id=id,
                    room_id=request.room_id,
                    **values.model_dump(),
                ),
                expected_revision=request.expected_revision,
                reason=request.reason,
                hotel_id=context.hotel_id,
                now=now,
            )
        return id

    return _command(
        connection,
        context=context,
        request_id=request_id,
        operation="stays.amend",
        request={"id": id, "payload": request.model_dump(mode="json")},
        action=action,
        now=now,
    )


def cancel(
    connection: Connection,
    id: BookingId,
    request: CancelStayRequestPayload,
    *,
    context: AgentDomainContext,
    request_id: str,
    now: int,
) -> Stay:
    """Cancel the parent booking once; its effective reservations and access follow it."""

    def action():
        _booking(connection, id, context.hotel_id)
        bookings.cancel(
            connection,
            id,
            expected_revision=request.expected_revision,
            reason=request.reason,
            hotel_id=context.hotel_id,
            now=now,
        )
        return id

    return _command(
        connection,
        context=context,
        request_id=request_id,
        operation="stays.cancel",
        request={"id": id, "payload": request.model_dump(mode="json")},
        action=action,
        now=now,
    )


def complete(
    connection: Connection,
    id: BookingId,
    request: CompleteStayRequestPayload,
    *,
    context: AgentDomainContext,
    request_id: str,
    now: int,
) -> Stay:
    """Complete a stay after its last uncancelled room allocation has ended."""

    def action():
        booking = _booking(connection, id, context.hotel_id)
        # Check all current allocations; a party may occupy several rooms.
        if any(
            to_microseconds(room.date_range.max_date) > now
            for room in booking.room_reservations
            if not room.cancelled
        ):
            raise WriteConflict(
                "The stay has not ended. Read the reserved checkout dates before completing it."
            )
        bookings.complete(
            connection,
            id,
            expected_revision=request.expected_revision,
            hotel_id=context.hotel_id,
            now=now,
        )
        return id

    return _command(
        connection,
        context=context,
        request_id=request_id,
        operation="stays.complete",
        request={"id": id, "payload": request.model_dump(mode="json")},
        action=action,
        now=now,
    )
