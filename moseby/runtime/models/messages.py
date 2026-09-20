from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_validator

from moseby.identifiers import JobId

from .common import ErrorDetails, JsonObject, RuntimeModel, ToolCallId


class UserMessagePayload(RuntimeModel):
    text: str = Field(min_length=1, description="Original message text.")


class ToolCall(RuntimeModel):
    id: ToolCallId = Field(description="Identifies this call within its source record.")
    name: str = Field(min_length=1, description="Registered tool to execute.")
    arguments: JsonObject = Field(
        description="Arguments validated by the selected tool."
    )


class AssistantMessagePayload(RuntimeModel):
    text: str | None = Field(default=None, min_length=1)
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_content(self) -> Self:
        if self.text is None and not self.tool_calls:
            raise ValueError("an assistant message requires text or tool calls")
        call_ids = [call.id for call in self.tool_calls]
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("tool call IDs must be unique within the message")
        return self


class ToolResultStatus(StrEnum):
    SUCCEEDED = "TOOL_RESULT_STATUS_SUCCEEDED"
    FAILED = "TOOL_RESULT_STATUS_FAILED"
    CANCELLED = "TOOL_RESULT_STATUS_CANCELLED"


class ToolResultPayloadBase(RuntimeModel):
    job_id: JobId | None = Field(
        default=None, description="Job producing the result when execution was queued."
    )


class SuccessfulToolResultPayload(ToolResultPayloadBase):
    status: Literal[ToolResultStatus.SUCCEEDED]
    result: JsonValue = Field(description="Tool output, including a valid JSON null.")


class FailedToolResultPayload(ToolResultPayloadBase):
    status: Literal[ToolResultStatus.FAILED]
    error: ErrorDetails


class CancelledToolResultPayload(ToolResultPayloadBase):
    status: Literal[ToolResultStatus.CANCELLED]
    reason: str = Field(min_length=1)


type ToolResultPayload = Annotated[
    SuccessfulToolResultPayload | FailedToolResultPayload | CancelledToolResultPayload,
    Field(discriminator="status"),
]
