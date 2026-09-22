"""Inputs and results for the concierge's complete stay journeys."""

from typing import Self

from pydantic import Field, model_validator

from moseby.common.types import NonemptyText
from moseby.identifiers import BookingId, GuestId, RoomId, RoomReservationId

from .bookings import Booking
from .common import Contract, Request
from .guests import Guest, GuestDetails
from .parties import Party
from .ranges import DateRange
from .room_keys import RoomKey
from .rooms import NightlyPrice


class Stay(Contract):
    booking: Booking
    party: Party
    guests: list[Guest]
    room_keys: list[RoomKey]


class GetStayRequestPayload(Contract):
    booking_id: BookingId | None = None
    guest_id: GuestId | None = None

    @model_validator(mode="after")
    def check_identity(self) -> Self:
        if (self.booking_id is None) == (self.guest_id is None):
            raise ValueError("Supply exactly one booking_id or guest_id")
        return self


class GetStayRequest(Request[GetStayRequestPayload]):
    pass


class StayRoom(Contract):
    room_id: RoomId
    date_range: DateRange
    quoted_price: NightlyPrice = Field(
        description="Copy the nightly price from room search; a changed rate requires a fresh choice."
    )


class CreateStayRequestPayload(Contract):
    name: NonemptyText
    guests: list[GuestDetails] = Field(min_length=1, max_length=100)
    rooms: list[StayRoom] = Field(min_length=1, max_length=100)


class CreateStayRequest(Request[CreateStayRequestPayload]):
    pass


class AddStayRoomRequest(Request[StayRoom]):
    pass


class AmendStayRequestPayload(StayRoom):
    room_reservation_id: RoomReservationId
    expected_revision: int = Field(
        ge=1, description="Current revision of this room reservation."
    )
    reason: NonemptyText = Field(
        description="Staff-reported reason for changing the allocation."
    )


class AmendStayRequest(Request[AmendStayRequestPayload]):
    pass


class CompleteStayRequestPayload(Contract):
    expected_revision: int = Field(ge=1, description="Current booking revision.")


class CompleteStayRequest(Request[CompleteStayRequestPayload]):
    pass


class CancelStayRequestPayload(CompleteStayRequestPayload):
    reason: NonemptyText


class CancelStayRequest(Request[CancelStayRequestPayload]):
    pass
