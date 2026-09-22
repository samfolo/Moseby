"""HTTP access to saved party notes and room-key commands."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from moseby.agents.models import AgentDomainContext
from moseby.contracts.common import Page, PageRequest
from moseby.contracts.party_details import PartyDetail, SearchPartyDetailsRequest
from moseby.contracts.room_keys import (
    DeactivateRoomKeyRequest,
    IssueRoomKeyRequest,
    RoomKey,
)
from moseby.contracts.route_metadata import access, query_body
from moseby.identifiers import PartyDetailId, RoomKeyId
from moseby.runtime.storage import now_microseconds
from moseby.services import party_details, room_keys

from .dependencies import get_domain_context, get_engine
from .errors import READ_RESPONSES
from .writes import write_command

router = APIRouter(responses=READ_RESPONSES)
Database = Annotated[Engine, Depends(get_engine)]
Caller = Annotated[AgentDomainContext, Depends(get_domain_context)]
Pagination = Annotated[PageRequest, Query()]


@router.get(
    "/party-details/{id}",
    operation_id="getPartyDetail",
    openapi_extra=access(party_details.READ_PERMISSION),
    responses={404: {"description": "Note not found in this hotel."}},
)
def get_detail(id: PartyDetailId, engine: Database, context: Caller) -> PartyDetail:
    note = party_details.get(
        engine, id, hotel_id=context.hotel_id, permissions=context.permissions
    )
    if note is None:
        raise HTTPException(404, "Note not found.")
    return note


@router.api_route(
    "/party-details",
    methods=["QUERY"],
    operation_id="searchPartyDetails",
    openapi_extra=query_body(SearchPartyDetailsRequest, party_details.READ_PERMISSION),
)
def search_details(
    request: SearchPartyDetailsRequest, engine: Database, context: Caller
) -> Page[PartyDetail]:
    return party_details.search(
        engine,
        request.payload,
        hotel_id=context.hotel_id,
        permissions=context.permissions,
    )


@router.get(
    "/room-keys",
    operation_id="listRoomKeys",
    openapi_extra=access(room_keys.READ_PERMISSION),
)
def list_keys(
    pagination: Pagination, engine: Database, context: Caller
) -> Page[RoomKey]:
    return room_keys.list_keys(
        engine,
        pagination,
        hotel_id=context.hotel_id,
        permissions=context.permissions,
        now=now_microseconds(),
    )


@router.get(
    "/room-keys/{id}",
    operation_id="getRoomKey",
    openapi_extra=access(room_keys.READ_PERMISSION),
    responses={404: {"description": "Key not found in this hotel."}},
)
def get_key(id: RoomKeyId, engine: Database, context: Caller) -> RoomKey:
    key = room_keys.get(
        engine,
        id,
        hotel_id=context.hotel_id,
        permissions=context.permissions,
        now=now_microseconds(),
    )
    if key is None:
        raise HTTPException(404, "Key not found.")
    return key


@router.post(
    "/room-keys",
    operation_id="issueRoomKey",
    status_code=201,
    openapi_extra=access(room_keys.WRITE_PERMISSION),
    responses={409: {"description": "The reservation cannot receive a key."}},
)
def issue_key(
    request: IssueRoomKeyRequest, engine: Database, context: Caller
) -> RoomKey:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return room_keys.issue(
            connection,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )


@router.post(
    "/room-keys/{id}:deactivate",
    operation_id="deactivateRoomKey",
    openapi_extra=access(room_keys.WRITE_PERMISSION),
    responses={
        409: {"description": "The deactivation conflicts with a previous change."}
    },
)
def deactivate_key(
    id: RoomKeyId, request: DeactivateRoomKeyRequest, engine: Database, context: Caller
) -> RoomKey:
    with write_command(engine, now=now_microseconds()) as (connection, now):
        return room_keys.deactivate(
            connection,
            id,
            request.payload,
            context=context,
            request_id=request.request_id,
            now=now,
        )
