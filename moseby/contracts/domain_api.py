"""Additional domain routes for review; every handler remains unimplemented."""

from typing import Annotated, Never

from fastapi import APIRouter, HTTPException, Query

from moseby.identifiers import (
    HotelId,
    PartyId,
    StaffMemberId,
    VenueId,
)

from .common import Page, PageRequest
from .hotels import Hotel
from .parties import Party, SearchPartiesRequest
from .party_details import (
    CreatePartyDetailRequest,
    PartyDetail,
)
from .route_metadata import access, query_body
from .staff_members import StaffMember
from .venues import Venue

router = APIRouter()
Pagination = Annotated[PageRequest, Query()]


def not_implemented() -> Never:
    raise HTTPException(501, "Contract draft; operation is not implemented.")


@router.get(
    "/hotels", operation_id="listHotels", openapi_extra=access("moseby.hotels:read")
)
def list_hotels(pagination: Pagination) -> Page[Hotel]:
    not_implemented()


@router.get(
    "/hotels/{id}", operation_id="getHotel", openapi_extra=access("moseby.hotels:read")
)
def get_hotel(id: HotelId) -> Hotel:
    not_implemented()


@router.get(
    "/staff-members",
    operation_id="listStaffMembers",
    openapi_extra=access("moseby.staff-members:read"),
)
def list_staff_members(pagination: Pagination) -> Page[StaffMember]:
    not_implemented()


@router.get(
    "/staff-members/{id}",
    operation_id="getStaffMember",
    openapi_extra=access("moseby.staff-members:read"),
)
def get_staff_member(id: StaffMemberId) -> StaffMember:
    not_implemented()


@router.get(
    "/venues",
    operation_id="listVenues",
    openapi_extra=access("moseby.venues:read", hotel_scoped=False),
)
def list_venues(pagination: Pagination) -> Page[Venue]:
    not_implemented()


@router.get(
    "/venues/{id}",
    operation_id="getVenue",
    openapi_extra=access("moseby.venues:read", hotel_scoped=False),
)
def get_venue(id: VenueId) -> Venue:
    not_implemented()


@router.get(
    "/parties/{id}", operation_id="getParty", openapi_extra=access("moseby.guests:read")
)
def get_party(id: PartyId) -> Party:
    not_implemented()


@router.api_route(
    "/parties",
    methods=["QUERY"],
    operation_id="searchParties",
    openapi_extra=query_body(SearchPartiesRequest, "moseby.guests:read"),
)
def search_parties(request: SearchPartiesRequest) -> Page[Party]:
    not_implemented()


@router.post(
    "/party-details",
    operation_id="createPartyDetail",
    status_code=201,
    description="Record a note about a party and identify any guests mentioned.",
    openapi_extra=access("moseby.guests:write"),
)
def create_party_detail(request: CreatePartyDetailRequest) -> PartyDetail:
    not_implemented()
