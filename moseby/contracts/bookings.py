from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from moseby.domain.enums import BookingStatus as BookingStatus
from moseby.identifiers import BookingId, HotelId, RoomId, RoomReservationId

from .common import Contract
from .ranges import DateRange
from .rooms import NightlyPrice


class RoomReservation(Contract):
    """Latest accepted allocation, embedded in its booking rather than exposed as CRUD."""

    id: RoomReservationId
    revision: int = Field(ge=1)
    room_id: RoomId
    date_range: DateRange
    cancelled: bool = Field(
        description="Explicit allocation cancellation; elapsed time does not change this flag."
    )
    nightly_price: NightlyPrice = Field(
        description="Agreed rate version, preserved after catalogue changes."
    )
    cancellation_reason: str | None = Field(min_length=1)

    @model_validator(mode="after")
    def check_cancellation(self) -> Self:
        if self.cancelled != (self.cancellation_reason is not None):
            raise ValueError(
                "a cancellation reason is required only for cancelled allocations"
            )
        return self


class Booking(Contract):
    """A confirmed stay; technical failures belong to operations, not booking status."""

    id: BookingId
    hotel_id: HotelId
    name: str = Field(min_length=1)
    revision: int = Field(
        ge=1, description="Revision supplying the current booking status."
    )
    status: BookingStatus
    cancellation_reason: str | None = Field(min_length=1)
    room_reservations: list[RoomReservation] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def check_cancellation(self) -> Self:
        if (self.status == BookingStatus.CANCELLED) != (
            self.cancellation_reason is not None
        ):
            raise ValueError(
                "a cancellation reason is required only for cancelled bookings"
            )
        reservation_ids = [reservation.id for reservation in self.room_reservations]
        if len(set(reservation_ids)) != len(reservation_ids):
            raise ValueError(
                "room_reservations must contain one current revision per allocation"
            )
        return self
