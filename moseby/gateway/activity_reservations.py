"""HTTP access to guest itineraries and reservation commands."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from moseby.agents.models import AgentDomainContext
from moseby.contracts.activity_reservations import (
    ActivityReservation,
    ActivityReservations,
    CancelActivityReservationRequest,
    ReserveActivityRequest,
    SearchActivityReservationsRequest,
    SearchActivityReservationsRequestPayload,
)
from moseby.contracts.common import Page, PageRequest
from moseby.contracts.route_metadata import access, query_body
from moseby.identifiers import ActivityReservationId
from moseby.runtime.storage import now_microseconds
from moseby.services import activity_reservations as service

from .dependencies import get_domain_context, get_engine
from .errors import READ_RESPONSES
from .writes import write_command

router = APIRouter(responses=READ_RESPONSES)
Database = Annotated[Engine, Depends(get_engine)]
Caller = Annotated[AgentDomainContext, Depends(get_domain_context)]
Pagination = Annotated[PageRequest, Query()]
WRITE_RESPONSES = {
    409: {"description": "The reservation conflicts with current state."}
}


@router.get(
    "/activity-reservations",
    operation_id="listActivityReservations",
    openapi_extra=access(service.READ_PERMISSION),
)
def list_reservations(
    pagination: Pagination, engine: Database, context: Caller
) -> Page[ActivityReservation]:
    return service.search(
        engine,
        SearchActivityReservationsRequestPayload(**pagination.model_dump()),
        hotel_id=context.hotel_id,
        permissions=context.permissions,
    )


@router.get(
    "/activity-reservations/{id}",
    operation_id="getActivityReservation",
    responses={404: {"description": "Reservation not found in this hotel."}},
    openapi_extra=access(service.READ_PERMISSION),
)
def get_reservation(
    id: ActivityReservationId, engine: Database, context: Caller
) -> ActivityReservation:
    result = service.get(
        engine, id, hotel_id=context.hotel_id, permissions=context.permissions
    )
    if result is None:
        raise HTTPException(404, "Reservation not found.")
    return result


@router.api_route(
    "/activity-reservations",
    methods=["QUERY"],
    operation_id="searchActivityReservations",
    openapi_extra=query_body(
        SearchActivityReservationsRequest, service.READ_PERMISSION
    ),
)
def search_reservations(
    request: SearchActivityReservationsRequest, engine: Database, context: Caller
) -> Page[ActivityReservation]:
    return service.search(
        engine,
        request.payload,
        hotel_id=context.hotel_id,
        permissions=context.permissions,
    )


@router.post(
    "/activity-reservations",
    operation_id="reserveActivityPlaces",
    status_code=201,
    responses=WRITE_RESPONSES,
    openapi_extra=access(service.WRITE_PERMISSION),
)
def reserve_places(
    request: ReserveActivityRequest, engine: Database, context: Caller
) -> ActivityReservations:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return service.reserve(
            connection,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )


@router.post(
    "/activity-reservations/{id}:cancel",
    operation_id="cancelActivityReservation",
    responses=WRITE_RESPONSES,
    openapi_extra=access(service.WRITE_PERMISSION),
)
def cancel_reservation(
    id: ActivityReservationId,
    request: CancelActivityReservationRequest,
    engine: Database,
    context: Caller,
) -> ActivityReservation:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return service.cancel(
            connection,
            id,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )
