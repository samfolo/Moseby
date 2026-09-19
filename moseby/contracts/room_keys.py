from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .common import Contract, Request
from .identifiers import RoomKeyId, RoomReservationId


class RoomKey(Contract):
    """Anonymous access tied to one reservation; a later stay cannot revive this key."""

    id: RoomKeyId
    room_reservation_id: RoomReservationId
    effective: bool = Field(
        description="Access now: not deactivated, with a confirmed booking and an uncancelled reservation whose current date range includes now."
    )
    code: str | None = Field(
        description="Optional demo key label; not a live door credential."
    )
    deactivated_at: AwareDatetime | None = Field(
        description="Explicit key revocation time; parent cancellation does not set this."
    )
    deactivation_reason: str | None = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def check_deactivation(self) -> Self:
        if (self.deactivated_at is None) != (self.deactivation_reason is None):
            raise ValueError(
                "deactivated_at and deactivation_reason must be supplied together"
            )
        if self.deactivated_at is not None and self.deactivated_at < self.created_at:
            raise ValueError("deactivation cannot precede creation")
        if self.deactivated_at is not None and self.effective:
            raise ValueError("a deactivated key cannot be effective")
        return self


class IssueRoomKeyRequestPayload(Contract):
    room_reservation_id: RoomReservationId
    code: str | None = None


class IssueRoomKeyRequest(Request[IssueRoomKeyRequestPayload]):
    pass


class DeactivateRoomKeyRequestPayload(Contract):
    reason: str = Field(min_length=1)


class DeactivateRoomKeyRequest(Request[DeactivateRoomKeyRequestPayload]):
    pass
