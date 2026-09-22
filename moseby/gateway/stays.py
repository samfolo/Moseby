"""HTTP commands use the same stay and guest services as the agent tools."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from moseby.agents.models import AgentDomainContext
from moseby.contracts.bookings import Booking
from moseby.contracts.common import Page, PageRequest
from moseby.contracts.guests import Guest, UpdateGuestRequest
from moseby.contracts.route_metadata import access, access_all, query_body
from moseby.contracts.stays import (
    AddStayRoomRequest,
    AmendStayRequest,
    CancelStayRequest,
    CompleteStayRequest,
    CreateStayRequest,
    GetStayRequest,
    Stay,
)
from moseby.identifiers import BookingId, GuestId
from moseby.runtime.storage import now_microseconds
from moseby.services import guests, stays

from .dependencies import get_domain_context, get_engine
from .errors import READ_RESPONSES
from .writes import write_command

router = APIRouter(
    responses=READ_RESPONSES
    | {409: {"description": "The change conflicts with current state."}}
)
Database = Annotated[Engine, Depends(get_engine)]
Caller = Annotated[AgentDomainContext, Depends(get_domain_context)]
Pagination = Annotated[PageRequest, Query()]


@router.get(
    "/bookings",
    operation_id="listBookings",
    openapi_extra=access(stays.READ_PERMISSION),
)
def list_bookings(
    pagination: Pagination, engine: Database, context: Caller
) -> Page[Booking]:
    return stays.list_bookings(engine, pagination, context=context)


@router.get(
    "/bookings/{id}",
    operation_id="getBooking",
    openapi_extra=access(stays.READ_PERMISSION),
    responses={404: {"description": "Booking not found in this hotel."}},
)
def get_booking(id: BookingId, engine: Database, context: Caller) -> Booking:
    try:
        return stays.get_booking(engine, id, context=context)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.api_route(
    "/bookings",
    methods=["QUERY"],
    operation_id="getStay",
    openapi_extra={
        **query_body(GetStayRequest, stays.READ_PERMISSION),
        **access_all(*stays.READ_PERMISSIONS),
    },
)
def get_stay(request: GetStayRequest, engine: Database, context: Caller) -> Stay:
    try:
        return stays.get(
            engine, request.payload, context=context, now=now_microseconds()
        )
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.post(
    "/bookings",
    operation_id="createStay",
    status_code=201,
    openapi_extra=access_all(*stays.CREATE_PERMISSIONS),
)
def create_stay(request: CreateStayRequest, engine: Database, context: Caller) -> Stay:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return stays.create(
            connection,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )


@router.post(
    "/bookings/{id}:amend",
    operation_id="amendStay",
    openapi_extra=access_all(*stays.WRITE_PERMISSIONS),
)
def amend_stay(
    id: BookingId, request: AmendStayRequest, engine: Database, context: Caller
) -> Stay:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return stays.amend(
            connection,
            id,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )


@router.post(
    "/bookings/{id}:cancel",
    operation_id="cancelStay",
    openapi_extra=access_all(*stays.WRITE_PERMISSIONS),
)
def cancel_stay(
    id: BookingId, request: CancelStayRequest, engine: Database, context: Caller
) -> Stay:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return stays.cancel(
            connection,
            id,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )


@router.post(
    "/bookings/{id}:complete",
    operation_id="completeStay",
    openapi_extra=access_all(*stays.WRITE_PERMISSIONS),
)
def complete_stay(
    id: BookingId, request: CompleteStayRequest, engine: Database, context: Caller
) -> Stay:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return stays.complete(
            connection,
            id,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )


@router.patch(
    "/guests/{id}",
    operation_id="updateGuest",
    openapi_extra=access_all(guests.READ_PERMISSION, guests.WRITE_PERMISSION),
)
def update_guest(
    id: GuestId, request: UpdateGuestRequest, engine: Database, context: Caller
) -> Guest:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return guests.update(connection, id, request, context=context, now=now)


@router.post(
    "/bookings/{id}:add-room",
    operation_id="addRoomToStay",
    status_code=201,
    openapi_extra=access_all(*stays.WRITE_PERMISSIONS),
)
def add_room(
    id: BookingId, request: AddStayRoomRequest, engine: Database, context: Caller
) -> Stay:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return stays.add_room(
            connection,
            id,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )
