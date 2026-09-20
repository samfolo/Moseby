from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from moseby.identifiers import (
    IncomingThreadRecordId,
    RunId,
    ScheduleOccurrenceId,
    StaffMemberId,
    ThreadId,
    ThreadRecordId,
)

from .common import RuntimeModel
from .messages import UserMessagePayload


class IncomingThreadRecordKind(StrEnum):
    USER_MESSAGE = "INCOMING_THREAD_RECORD_KIND_USER_MESSAGE"
    SCHEDULED_INPUT = "INCOMING_THREAD_RECORD_KIND_SCHEDULED_INPUT"


class IncomingThreadRecordDeliveryMode(StrEnum):
    """Polite input queues a follow-up; assertive input steers its target run."""

    POLITE = "INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE"
    ASSERTIVE = "INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE"


class ScheduledInputPayload(RuntimeModel):
    occurrence_id: ScheduleOccurrenceId
    text: str = Field(
        min_length=1, description="Instruction accepted from the scheduled action."
    )


class IncomingThreadRecordBase(RuntimeModel):
    id: IncomingThreadRecordId
    created_at: AwareDatetime
    updated_at: AwareDatetime
    thread_id: ThreadId
    sequence: int = Field(
        ge=1, strict=True, description="Arrival order within this thread."
    )
    actor_staff_member_id: StaffMemberId
    request_id: str | None = Field(
        default=None,
        min_length=1,
        description="Internal idempotency key supplied for HTTP input.",
    )
    format_version: Literal[1]
    record_id: ThreadRecordId | None = Field(
        default=None, description="History record created when this input is accepted."
    )
    appended_at: AwareDatetime | None = None
    cancelled_at: AwareDatetime | None = Field(
        default=None, description="Time a staff member withdrew this pending input."
    )
    cancelled_by_staff_member_id: StaffMemberId | None = None

    @model_validator(mode="after")
    def check_times(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be at or after created_at")
        if (self.record_id is None) != (self.appended_at is None):
            raise ValueError("record_id and appended_at must be supplied together")
        if (
            self.appended_at is not None
            and not self.created_at <= self.appended_at <= self.updated_at
        ):
            raise ValueError("appended_at must be between created_at and updated_at")
        if (self.cancelled_at is None) != (self.cancelled_by_staff_member_id is None):
            raise ValueError(
                "cancellation time and staff member must be supplied together"
            )
        if self.cancelled_at is not None:
            if self.record_id is not None:
                raise ValueError("appended input cannot be cancelled")
            if not self.created_at <= self.cancelled_at <= self.updated_at:
                raise ValueError(
                    "cancelled_at must be between created_at and updated_at"
                )
        return self


class IncomingUserMessageRecord(IncomingThreadRecordBase):
    kind: Literal[IncomingThreadRecordKind.USER_MESSAGE]
    delivery_mode: IncomingThreadRecordDeliveryMode
    target_run_id: RunId | None = Field(
        default=None,
        description="Run this input was intended to steer, retained after that run ends.",
    )
    payload: UserMessagePayload

    @model_validator(mode="after")
    def check_delivery(self) -> Self:
        assertive = self.delivery_mode == IncomingThreadRecordDeliveryMode.ASSERTIVE
        if assertive != (self.target_run_id is not None):
            raise ValueError(
                "assertive input requires a target run; polite input has none"
            )
        return self


class IncomingScheduledInputRecord(IncomingThreadRecordBase):
    kind: Literal[IncomingThreadRecordKind.SCHEDULED_INPUT]
    delivery_mode: Literal[IncomingThreadRecordDeliveryMode.POLITE]
    target_run_id: None = None
    cancelled_at: None = None
    cancelled_by_staff_member_id: None = None
    payload: ScheduledInputPayload


type IncomingThreadRecord = Annotated[
    IncomingUserMessageRecord | IncomingScheduledInputRecord,
    Field(discriminator="kind"),
]

incoming_thread_record_adapter = TypeAdapter(IncomingThreadRecord)
