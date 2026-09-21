"""HTTP reads for rooms, guests and the shared activity schedule."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from moseby.agents.models import AgentDomainContext
from moseby.contracts.activities import (
    Activity,
    SearchActivitiesRequest,
    SearchActivitiesRequestPayload,
)
from moseby.contracts.common import Page, PageRequest
from moseby.contracts.guests import (
    Guest,
    SearchGuestsRequest,
    SearchGuestsRequestPayload,
)
from moseby.contracts.rooms import Room, SearchRoomsRequest
from moseby.contracts.route_metadata import access, query_body
from moseby.identifiers import ActivityId, GuestId, RoomId
from moseby.services import activities, guests, rooms

from .dependencies import get_domain_context, get_engine
from .errors import READ_RESPONSES

router = APIRouter(responses=READ_RESPONSES)
Database = Annotated[Engine, Depends(get_engine)]
Caller = Annotated[AgentDomainContext, Depends(get_domain_context)]
Pagination = Annotated[PageRequest, Query()]


@router.get(
    "/guests", operation_id="listGuests", openapi_extra=access(guests.READ_PERMISSION)
)
def list_guests(
    pagination: Pagination, engine: Database, context: Caller
) -> Page[Guest]:
    return guests.search(
        engine,
        SearchGuestsRequestPayload(**pagination.model_dump()),
        hotel_id=context.hotel_id,
        permissions=context.permissions,
    )


@router.get(
    "/guests/{id}",
    operation_id="getGuest",
    responses={404: {"description": "The guest was not found in this hotel."}},
    openapi_extra=access(guests.READ_PERMISSION),
)
def get_guest(id: GuestId, engine: Database, context: Caller) -> Guest:
    guest = guests.get(
        engine, id, hotel_id=context.hotel_id, permissions=context.permissions
    )
    if guest is None:
        raise HTTPException(404, "Guest not found.")
    return guest


@router.api_route(
    "/guests",
    methods=["QUERY"],
    operation_id="searchGuests",
    openapi_extra=query_body(SearchGuestsRequest, guests.READ_PERMISSION),
)
def search_guests(
    request: SearchGuestsRequest, engine: Database, context: Caller
) -> Page[Guest]:
    return guests.search(
        engine,
        request.payload,
        hotel_id=context.hotel_id,
        permissions=context.permissions,
    )


@router.get(
    "/activities",
    operation_id="listActivities",
    openapi_extra=access(activities.READ_PERMISSION, hotel_scoped=False),
)
def list_activities(
    pagination: Pagination, engine: Database, context: Caller
) -> Page[Activity]:
    return activities.search(
        engine,
        SearchActivitiesRequestPayload(**pagination.model_dump()),
        permissions=context.permissions,
    )


@router.get(
    "/activities/{id}",
    operation_id="getActivity",
    responses={404: {"description": "The activity was not found."}},
    openapi_extra=access(activities.READ_PERMISSION, hotel_scoped=False),
)
def get_activity(id: ActivityId, engine: Database, context: Caller) -> Activity:
    activity = activities.get(engine, id, permissions=context.permissions)
    if activity is None:
        raise HTTPException(404, "Activity not found.")
    return activity


@router.api_route(
    "/activities",
    methods=["QUERY"],
    operation_id="searchActivities",
    openapi_extra=query_body(
        SearchActivitiesRequest, activities.READ_PERMISSION, hotel_scoped=False
    ),
)
def search_activities(
    request: SearchActivitiesRequest, engine: Database, context: Caller
) -> Page[Activity]:
    return activities.search(engine, request.payload, permissions=context.permissions)


@router.api_route(
    "/rooms",
    methods=["QUERY"],
    operation_id="searchRooms",
    summary="Search rooms",
    response_model=Page[Room],
    description="Combine filters and return current prices. An availability window restricts results to free rooms; no capacity is held.",
    openapi_extra=query_body(SearchRoomsRequest, rooms.READ_PERMISSION),
)
def search_rooms(
    request: SearchRoomsRequest,
    engine: Database,
    context: Caller,
) -> Page[Room]:
    return rooms.search(
        engine,
        request.payload,
        hotel_id=context.hotel_id,
        permissions=context.permissions,
    )


@router.get(
    "/rooms/{id}",
    operation_id="getRoom",
    responses={404: {"description": "The room was not found in this hotel."}},
    summary="Read a room",
    openapi_extra=access(rooms.READ_PERMISSION),
)
def get_room(
    id: RoomId,
    engine: Database,
    context: Caller,
) -> Room:
    room = rooms.get(
        engine, id, hotel_id=context.hotel_id, permissions=context.permissions
    )
    if room is None:
        raise HTTPException(404, "Room not found.")
    return room
