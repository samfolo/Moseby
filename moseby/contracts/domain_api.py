"""Additional domain routes for review; every handler remains unimplemented."""

from typing import Annotated, Never

from fastapi import APIRouter, HTTPException, Query

from .activities import Activity, SearchActivitiesRequest
from .activity_reservations import (
    ActivityReservation,
    CancelActivityReservationRequest,
    SearchActivityReservationsRequest,
)
from .bookings import Booking
from .common import Page, PageRequest
from .guests import Guest, SearchGuestsRequest
from .hotels import Hotel
from .identifiers import (
    ActivityId,
    ActivityReservationId,
    BookingId,
    HotelId,
    PartyDetailId,
    PartyId,
    RoomKeyId,
    StaffMemberId,
    VenueId,
)
from .parties import Party, SearchPartiesRequest
from .party_details import (
    CreatePartyDetailRequest,
    PartyDetail,
    SearchPartyDetailsRequest,
)
from .room_keys import DeactivateRoomKeyRequest, IssueRoomKeyRequest, RoomKey
from .route_metadata import access, query_body
from .staff_members import StaffMember
from .venues import Venue

router = APIRouter()
Pagination = Annotated[PageRequest, Query()]


def not_implemented() -> Never:
    raise HTTPException(501, "Contract draft; operation is not implemented.")


@router.get(
    "/hotels", operation_id="listHotels", openapi_extra=access("Moseby.hotels:read")
)
def list_hotels(pagination: Pagination) -> Page[Hotel]:
    not_implemented()


@router.get(
    "/hotels/{id}", operation_id="getHotel", openapi_extra=access("Moseby.hotels:read")
)
def get_hotel(id: HotelId) -> Hotel:
    not_implemented()


@router.get(
    "/staff-members",
    operation_id="listStaffMembers",
    openapi_extra=access("Moseby.staff-members:read"),
)
def list_staff_members(pagination: Pagination) -> Page[StaffMember]:
    not_implemented()


@router.get(
    "/staff-members/{id}",
    operation_id="getStaffMember",
    openapi_extra=access("Moseby.staff-members:read"),
)
def get_staff_member(id: StaffMemberId) -> StaffMember:
    not_implemented()


@router.get(
    "/venues",
    operation_id="listVenues",
    openapi_extra=access("Moseby.venues:read", hotel_scoped=False),
)
def list_venues(pagination: Pagination) -> Page[Venue]:
    not_implemented()


@router.get(
    "/venues/{id}",
    operation_id="getVenue",
    openapi_extra=access("Moseby.venues:read", hotel_scoped=False),
)
def get_venue(id: VenueId) -> Venue:
    not_implemented()


@router.get(
    "/bookings",
    operation_id="listBookings",
    openapi_extra=access("Moseby.bookings:read"),
)
def list_bookings(pagination: Pagination) -> Page[Booking]:
    not_implemented()


@router.get(
    "/bookings/{id}",
    operation_id="getBooking",
    openapi_extra=access("Moseby.bookings:read"),
)
def get_booking(id: BookingId) -> Booking:
    not_implemented()


@router.get(
    "/parties/{id}", operation_id="getParty", openapi_extra=access("Moseby.guests:read")
)
def get_party(id: PartyId) -> Party:
    not_implemented()


@router.api_route(
    "/parties",
    methods=["QUERY"],
    operation_id="searchParties",
    openapi_extra=query_body(SearchPartiesRequest, "Moseby.guests:read"),
)
def search_parties(request: SearchPartiesRequest) -> Page[Party]:
    not_implemented()


@router.get(
    "/guests", operation_id="listGuests", openapi_extra=access("Moseby.guests:read")
)
def list_guests(pagination: Pagination) -> Page[Guest]:
    not_implemented()


@router.api_route(
    "/guests",
    methods=["QUERY"],
    operation_id="searchGuests",
    openapi_extra=query_body(SearchGuestsRequest, "Moseby.guests:read"),
)
def search_guests(request: SearchGuestsRequest) -> Page[Guest]:
    not_implemented()


@router.get(
    "/party-details/{id}",
    operation_id="getPartyDetail",
    openapi_extra=access("Moseby.guests:read"),
)
def get_party_detail(id: PartyDetailId) -> PartyDetail:
    not_implemented()


@router.api_route(
    "/party-details",
    methods=["QUERY"],
    operation_id="searchPartyDetails",
    openapi_extra=query_body(SearchPartyDetailsRequest, "Moseby.guests:read"),
)
def search_party_details(request: SearchPartyDetailsRequest) -> Page[PartyDetail]:
    not_implemented()


@router.post(
    "/party-details",
    operation_id="createPartyDetail",
    status_code=201,
    description="Record a note about a party and identify any guests mentioned.",
    openapi_extra=access("Moseby.guests:write"),
)
def create_party_detail(request: CreatePartyDetailRequest) -> PartyDetail:
    not_implemented()


@router.get(
    "/room-keys",
    operation_id="listRoomKeys",
    openapi_extra=access("Moseby.bookings:read"),
)
def list_room_keys(pagination: Pagination) -> Page[RoomKey]:
    not_implemented()


@router.get(
    "/room-keys/{id}",
    operation_id="getRoomKey",
    openapi_extra=access("Moseby.bookings:read"),
)
def get_room_key(id: RoomKeyId) -> RoomKey:
    not_implemented()


@router.post(
    "/room-keys",
    operation_id="issueRoomKey",
    status_code=201,
    openapi_extra=access("Moseby.bookings:write"),
)
def issue_room_key(request: IssueRoomKeyRequest) -> RoomKey:
    not_implemented()


@router.post(
    "/room-keys/{id}:deactivate",
    operation_id="deactivateRoomKey",
    openapi_extra=access("Moseby.bookings:write"),
)
def deactivate_room_key(id: RoomKeyId, request: DeactivateRoomKeyRequest) -> RoomKey:
    not_implemented()


@router.get(
    "/activities",
    operation_id="listActivities",
    openapi_extra=access("Moseby.activities:read", hotel_scoped=False),
)
def list_activities(pagination: Pagination) -> Page[Activity]:
    not_implemented()


@router.get(
    "/activities/{id}",
    operation_id="getActivity",
    openapi_extra=access("Moseby.activities:read", hotel_scoped=False),
)
def get_activity(id: ActivityId) -> Activity:
    not_implemented()


@router.api_route(
    "/activities",
    methods=["QUERY"],
    operation_id="searchActivities",
    openapi_extra=query_body(
        SearchActivitiesRequest, "Moseby.activities:read", hotel_scoped=False
    ),
)
def search_activities(request: SearchActivitiesRequest) -> Page[Activity]:
    not_implemented()


@router.get(
    "/activity-reservations",
    operation_id="listActivityReservations",
    openapi_extra=access("Moseby.activities:read"),
)
def list_activity_reservations(pagination: Pagination) -> Page[ActivityReservation]:
    not_implemented()


@router.get(
    "/activity-reservations/{id}",
    operation_id="getActivityReservation",
    openapi_extra=access("Moseby.activities:read"),
)
def get_activity_reservation(id: ActivityReservationId) -> ActivityReservation:
    not_implemented()


@router.api_route(
    "/activity-reservations",
    methods=["QUERY"],
    operation_id="searchActivityReservations",
    openapi_extra=query_body(
        SearchActivityReservationsRequest, "Moseby.activities:read"
    ),
)
def search_activity_reservations(
    request: SearchActivityReservationsRequest,
) -> Page[ActivityReservation]:
    not_implemented()


@router.post(
    "/activity-reservations/{id}:cancel",
    operation_id="cancelActivityReservation",
    openapi_extra=access("Moseby.activities:write"),
)
def cancel_activity_reservation(
    id: ActivityReservationId, request: CancelActivityReservationRequest
) -> ActivityReservation:
    not_implemented()
