"""Inputs for domain changes that must either all succeed or all roll back."""

from typing import Self

from pydantic import Field, model_validator

from moseby.identifiers import PartyId

from .bookings import BookingRow, NewBooking
from .common import Row
from .guests import GuestRow, NewGuest
from .parties import PartyRow
from .room_reservations import NewRoomReservation, RoomReservationRow


class NewStay(Row):
    """Input rows for creating a booking, its party, guests and room reservations."""

    booking: NewBooking
    party_id: PartyId
    guests: list[NewGuest] = Field(min_length=1, max_length=100)
    rooms: list[NewRoomReservation] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def check_membership(self) -> Self:
        if any(guest.party_id != self.party_id for guest in self.guests):
            raise ValueError("all guests must belong to the new party")
        if any(room.booking_id != self.booking.id for room in self.rooms):
            raise ValueError("all rooms must belong to the new booking")
        if len({guest.id for guest in self.guests}) != len(self.guests):
            raise ValueError("guest IDs must be unique")
        if len({room.id for room in self.rooms}) != len(self.rooms):
            raise ValueError("reservation IDs must be unique")
        return self


class Stay(Row):
    """Rows returned by the composed creation operation, grouped for the caller."""

    booking: BookingRow
    party: PartyRow
    guests: list[GuestRow]
    rooms: list[RoomReservationRow]
