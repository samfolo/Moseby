from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from moseby.identifiers import (
    IncomingThreadRecordId,
    RunId,
    StaffMemberId,
    ThreadId,
    ThreadRecordId,
)
from moseby.runtime.models.incoming_thread_records import (
    IncomingThreadRecordDeliveryMode,
)
from moseby.runtime.models.messages import (
    AssistantMessagePayload,
    ToolResultPayload,
    UserMessagePayload,
)
from moseby.runtime.models.thread_records import ThreadRecordKind

from .common import Contract, Request


class Thread(Contract):
    id: ThreadId
    creator_staff_member_id: StaffMemberId
    title: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    archived_at: AwareDatetime | None
    projection_sequence: int = Field(
        ge=0,
        strict=True,
        description="Last history record reflected in this thread summary.",
    )

    @model_validator(mode="after")
    def check_times(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be at or after created_at")
        if (
            self.archived_at is not None
            and not self.created_at <= self.archived_at <= self.updated_at
        ):
            raise ValueError("archived_at must be between created_at and updated_at")
        return self


class CreateThreadRequestPayload(Contract):
    title: str | None = Field(default=None, min_length=1)


class CreateThreadRequest(Request[CreateThreadRequestPayload]):
    pass


class CreateIncomingThreadRecordRequestPayload(Contract):
    text: str = Field(min_length=1)
    delivery_mode: IncomingThreadRecordDeliveryMode = (
        IncomingThreadRecordDeliveryMode.POLITE
    )
    target_run_id: RunId | None = Field(
        default=None,
        description="Run observed by the sender when requesting assertive delivery.",
    )

    @model_validator(mode="after")
    def check_delivery(self) -> Self:
        assertive = self.delivery_mode == IncomingThreadRecordDeliveryMode.ASSERTIVE
        if assertive != (self.target_run_id is not None):
            raise ValueError(
                "assertive input requires a target run; polite input has none"
            )
        return self


class CreateIncomingThreadRecordRequest(
    Request[CreateIncomingThreadRecordRequestPayload]
):
    pass


class IncomingThreadRecordReceipt(Contract):
    """Shows whether saved input is waiting, appended or cancelled."""

    id: IncomingThreadRecordId
    thread_id: ThreadId
    sequence: int = Field(ge=1, strict=True)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    record_id: ThreadRecordId | None
    appended_at: AwareDatetime | None
    cancelled_at: AwareDatetime | None
    cancelled_by_staff_member_id: StaffMemberId | None

    @model_validator(mode="after")
    def check_acceptance(self) -> Self:
        if (self.record_id is None) != (self.appended_at is None):
            raise ValueError("record_id and appended_at must be supplied together")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be at or after created_at")
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


class CancelIncomingThreadRecordRequestPayload(Contract):
    """Withdraw pending user input; the authenticated staff member is recorded."""


class CancelIncomingThreadRecordRequest(
    Request[CancelIncomingThreadRecordRequestPayload]
):
    """UI operation for polite or assertive input before acceptance into history."""


class ConversationRecordBase(Contract):
    id: ThreadRecordId
    thread_id: ThreadId
    sequence: int = Field(ge=2, strict=True)
    created_at: AwareDatetime
    run_id: RunId | None
    actor_staff_member_id: StaffMemberId | None


class UserConversationRecord(ConversationRecordBase):
    kind: Literal[ThreadRecordKind.USER_MESSAGE]
    payload: UserMessagePayload


class AssistantConversationRecord(ConversationRecordBase):
    kind: Literal[ThreadRecordKind.ASSISTANT_MESSAGE]
    run_id: RunId
    payload: AssistantMessagePayload


class ToolResultConversationRecord(ConversationRecordBase):
    kind: Literal[ThreadRecordKind.TOOL_RESULT]
    run_id: RunId
    source_record_id: ThreadRecordId
    tool_call_id: str = Field(min_length=1)
    payload: ToolResultPayload


type ConversationRecord = Annotated[
    UserConversationRecord | AssistantConversationRecord | ToolResultConversationRecord,
    Field(discriminator="kind"),
]
