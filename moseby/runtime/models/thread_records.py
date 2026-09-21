from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator

from moseby.agents.identity import AgentReference
from moseby.identifiers import (
    InferenceRequestId,
    RunId,
    StaffMemberId,
    ThreadId,
    ThreadRecordId,
)
from moseby.permissions import Permission

from .common import ErrorDetails, JsonObject, RuntimeModel, ToolCallId
from .messages import (
    AssistantMessagePayload,
    ToolCall,
    ToolResultPayload,
    UserMessagePayload,
)


class ThreadRecordKind(StrEnum):
    THREAD_CREATED = "THREAD_RECORD_KIND_THREAD_CREATED"
    USER_MESSAGE = "THREAD_RECORD_KIND_USER_MESSAGE"
    ASSISTANT_MESSAGE = "THREAD_RECORD_KIND_ASSISTANT_MESSAGE"
    TOOL_RESULT = "THREAD_RECORD_KIND_TOOL_RESULT"
    CLASSIFIER_DECISION = "THREAD_RECORD_KIND_CLASSIFIER_DECISION"
    INFERENCE_REQUEST = "THREAD_RECORD_KIND_INFERENCE_REQUEST"
    CONTROL_EVENT = "THREAD_RECORD_KIND_CONTROL_EVENT"


class ThreadCreatedPayload(RuntimeModel):
    # Preserve the payload when replaying a record without an agent selection.
    agent: AgentReference | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Agent ID and version selected for this thread.",
    )
    creator_staff_member_id: StaffMemberId
    permissions: list[Permission] = Field(
        description="Permission codes captured at thread creation."
    )
    title: str | None = None

    @model_validator(mode="after")
    def check_permissions(self) -> Self:
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("permissions must contain unique codes")
        return self


class ClassifierDecisionStatus(StrEnum):
    RESOLVED = "CLASSIFIER_DECISION_STATUS_RESOLVED"
    AMBIGUOUS = "CLASSIFIER_DECISION_STATUS_AMBIGUOUS"
    FAILED = "CLASSIFIER_DECISION_STATUS_FAILED"


class ClassifierDecisionPayload(RuntimeModel):
    inference_request_id: InferenceRequestId
    input_record_ids: list[ThreadRecordId] = Field(default_factory=list)
    status: ClassifierDecisionStatus
    decision: JsonObject | None = Field(
        default=None, description="Output in the selected classifier's schema."
    )
    error: ErrorDetails | None = None
    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="Accepted calls selected by a resolved classifier decision.",
    )

    @model_validator(mode="after")
    def check_decision(self) -> Self:
        if len(set(self.input_record_ids)) != len(self.input_record_ids):
            raise ValueError("input_record_ids must be unique")
        ids = [call.id for call in self.tool_calls]
        if len(set(ids)) != len(ids):
            raise ValueError("tool call IDs must be unique within the decision")
        if self.status == ClassifierDecisionStatus.FAILED:
            if self.error is None or self.decision is not None:
                raise ValueError(
                    "a failed classification requires an error and no decision"
                )
        elif self.error is not None or self.decision is None:
            raise ValueError(
                "a resolved or ambiguous classification requires a decision and no error"
            )
        if self.tool_calls and self.status != ClassifierDecisionStatus.RESOLVED:
            raise ValueError("only a resolved classification can select tool calls")
        return self


class InferenceRequestPayload(RuntimeModel):
    inference_request_id: InferenceRequestId = Field(
        description="Links to the saved provider request and its outcome."
    )


class ControlEventPayload(RuntimeModel):
    name: str = Field(
        min_length=1,
        description="Registered runtime event, such as a run waiting or resuming.",
    )
    data: JsonObject = Field(
        description="Event-specific data validated by its handler."
    )


class ThreadRecordBase(RuntimeModel):
    id: ThreadRecordId
    thread_id: ThreadId
    sequence: int = Field(
        ge=1, strict=True, description="Position in this thread's permanent history."
    )
    created_at: AwareDatetime
    format_version: Literal[1] = Field(
        description="Version of the payload format for this record kind."
    )
    run_id: RunId | None = None
    actor_staff_member_id: StaffMemberId | None = None
    source_record_id: ThreadRecordId | None = Field(
        default=None,
        description="Earlier record in the same thread that caused this event.",
    )
    tool_call_id: None = None

    @model_validator(mode="after")
    def check_source(self) -> Self:
        if self.source_record_id == self.id:
            raise ValueError("a record cannot reference itself as its source")
        return self


class ThreadCreatedRecord(ThreadRecordBase):
    kind: Literal[ThreadRecordKind.THREAD_CREATED]
    sequence: Literal[1]
    run_id: None = None
    source_record_id: None = None
    payload: ThreadCreatedPayload

    @model_validator(mode="after")
    def check_creator(self) -> Self:
        if (
            self.actor_staff_member_id is not None
            and self.actor_staff_member_id != self.payload.creator_staff_member_id
        ):
            raise ValueError("the actor must match the thread creator")
        return self


class SubsequentThreadRecord(ThreadRecordBase):
    sequence: int = Field(ge=2, strict=True)


class UserMessageRecord(SubsequentThreadRecord):
    kind: Literal[ThreadRecordKind.USER_MESSAGE]
    payload: UserMessagePayload


class AssistantMessageRecord(SubsequentThreadRecord):
    kind: Literal[ThreadRecordKind.ASSISTANT_MESSAGE]
    run_id: RunId
    payload: AssistantMessagePayload


class ToolResultRecord(SubsequentThreadRecord):
    kind: Literal[ThreadRecordKind.TOOL_RESULT]
    run_id: RunId
    source_record_id: ThreadRecordId
    tool_call_id: ToolCallId
    payload: ToolResultPayload


class ClassifierDecisionRecord(SubsequentThreadRecord):
    kind: Literal[ThreadRecordKind.CLASSIFIER_DECISION]
    payload: ClassifierDecisionPayload

    @model_validator(mode="after")
    def check_tool_run(self) -> Self:
        if self.payload.tool_calls and self.run_id is None:
            raise ValueError("classifier-selected tool calls require a run")
        return self


class InferenceRequestRecord(SubsequentThreadRecord):
    kind: Literal[ThreadRecordKind.INFERENCE_REQUEST]
    payload: InferenceRequestPayload


class ControlEventRecord(SubsequentThreadRecord):
    kind: Literal[ThreadRecordKind.CONTROL_EVENT]
    payload: ControlEventPayload


type ThreadRecord = Annotated[
    ThreadCreatedRecord
    | UserMessageRecord
    | AssistantMessageRecord
    | ToolResultRecord
    | ClassifierDecisionRecord
    | InferenceRequestRecord
    | ControlEventRecord,
    Field(discriminator="kind"),
]

# Select the record model by its kind, then validate its fields and payload.
thread_record_adapter = TypeAdapter(ThreadRecord)


def validate_tool_result_source(result: ToolResultRecord, source: ThreadRecord) -> None:
    """Check a result against the source record loaded by the repository."""
    if not isinstance(source, (AssistantMessageRecord, ClassifierDecisionRecord)):
        raise ValueError("a tool result requires an assistant or classifier source")
    if result.source_record_id != source.id or result.thread_id != source.thread_id:
        raise ValueError("the result must reference its source in the same thread")
    if source.run_id is None or result.run_id != source.run_id:
        raise ValueError("the result and source must belong to the same run")
    if source.sequence >= result.sequence:
        raise ValueError("the source must precede the result")
    if result.tool_call_id not in {call.id for call in source.payload.tool_calls}:
        raise ValueError("the source record does not contain the referenced tool call")
