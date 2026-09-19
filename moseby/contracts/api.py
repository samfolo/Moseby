"""Review-only routes used to generate the contract; handlers are not implemented."""

from fastapi import FastAPI, HTTPException

from .common import Page
from .domain_api import router as domain_router
from .guests import Guest, UpdateGuestRequest
from .identifiers import GuestId, RoomId
from .rooms import Room, SearchRoomsRequest
from .route_metadata import access, query_body

app = FastAPI(
    title="Moseby contract draft",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    description="Domain contract review. Permission annotations are proposals, not enforcement. Operations return 501.",
    responses={501: {"description": "Contract draft; operation is not implemented."}},
)
app.openapi_version = "3.2.1"
app.include_router(domain_router)


@app.api_route(
    "/rooms",
    methods=["QUERY"],
    operation_id="searchRooms",
    summary="Search rooms",
    response_model=Page[Room],
    description="Combine filters and return current prices. An availability window restricts results to free rooms; no capacity is held.",
    openapi_extra=query_body(SearchRoomsRequest, "moseby.rooms:read"),
)
def search_rooms(request: SearchRoomsRequest) -> Page[Room]:
    raise HTTPException(501, "Contract draft; operation is not implemented.")


@app.get(
    "/rooms/{id}",
    operation_id="getRoom",
    summary="Read a room",
    openapi_extra=access("moseby.rooms:read"),
)
def get_room(id: RoomId) -> Room:
    raise HTTPException(501, "Contract draft; operation is not implemented.")


@app.get(
    "/guests/{id}",
    operation_id="getGuest",
    summary="Read a guest",
    openapi_extra=access("moseby.guests:read"),
)
def get_guest(id: GuestId) -> Guest:
    raise HTTPException(501, "Contract draft; operation is not implemented.")


@app.patch(
    "/guests/{id}",
    operation_id="updateGuest",
    summary="Update a guest",
    description="Apply the masked fields to the existing guest and validate the resulting guest before saving.",
    openapi_extra=access("moseby.guests:write"),
)
def update_guest(id: GuestId, request: UpdateGuestRequest) -> Guest:
    raise HTTPException(501, "Contract draft; operation is not implemented.")
