from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from moseby.identifiers import (
    ActivityId,
    ActivityReservationId,
    BookingId,
    GuestId,
    PartyId,
    VenueId,
)

from .activities import ActivityPrice
from .common import Contract, IdFilter, Request, SearchRequestPayload
from .ranges import DateRange


class ReservedActivity(Contract):
    """Current activity information needed to display a guest's itinerary."""

    id: ActivityId
    venue_id: VenueId
    title: str = Field(min_length=1)
    date_range: DateRange


class ActivityReservation(Contract):
    """One guest's latest reservation revision, attributed to their party."""

    id: ActivityReservationId
    revision: int = Field(ge=1)
    guest_id: GuestId
    party_id: PartyId
    activity: ReservedActivity
    cancelled: bool = Field(
        description="Explicit cancellation; an ended activity does not change this flag."
    )
    cancellation_reason: str | None = Field(min_length=1)
    agreed_price: ActivityPrice
    effective: bool = Field(
        description="True when not cancelled and the parent booking permits it; independent of whether the activity has ended."
    )
    created_at: AwareDatetime

    @model_validator(mode="after")
    def check_cancellation(self) -> Self:
        if self.cancelled != (self.cancellation_reason is not None):
            raise ValueError(
                "a cancellation reason is required only for cancelled reservations"
            )
        if self.cancelled and self.effective:
            raise ValueError("cancelled reservations cannot be effective")
        return self


class SearchActivityReservationsRequestPayload(SearchRequestPayload):
    guest_ids: IdFilter[GuestId] | None = None
    party_ids: IdFilter[PartyId] | None = None
    booking_ids: IdFilter[BookingId] | None = Field(
        default=None, description="Resolve through party membership."
    )
    activity_ids: IdFilter[ActivityId] | None = None
    date_range: DateRange | None = Field(
        default=None,
        description="Match current activity date ranges overlapping this interval.",
    )
    effective: bool | None = Field(
        default=True,
        description="Default to effective reservations; false selects ineffective ones, null includes both.",
    )
    cancelled: bool | None = Field(
        default=None,
        description="Filter explicit cancellation independently of parent booking eligibility.",
    )


class SearchActivityReservationsRequest(
    Request[SearchActivityReservationsRequestPayload]
):
    pass


class CancelActivityReservationRequestPayload(Contract):
    reason: str = Field(min_length=1)


class CancelActivityReservationRequest(
    Request[CancelActivityReservationRequestPayload]
):
    pass
