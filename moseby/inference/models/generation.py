from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from moseby.runtime.models.messages import AssistantMessagePayload

from .common import InferenceModel, JsonObject, NonemptyText


class TextMessage(InferenceModel):
    role: Literal["system", "user"]
    content: NonemptyText


class AssistantMessage(AssistantMessagePayload):
    role: Literal["assistant"] = "assistant"
    provider_state: JsonObject = Field(
        default_factory=dict,
        description="Opaque provider fields needed to continue this assistant reply.",
    )


class ToolMessage(InferenceModel):
    role: Literal["tool"] = "tool"
    tool_call_id: NonemptyText
    content: str = Field(description="Serialized result for this specific tool call.")


type ChatMessage = Annotated[
    TextMessage | AssistantMessage | ToolMessage, Field(discriminator="role")
]


class ToolDefinition(InferenceModel):
    name: NonemptyText
    description: NonemptyText
    parameters: JsonObject = Field(description="JSON Schema for the tool's arguments.")


class GenerationRequest(InferenceModel):
    messages: list[ChatMessage] = Field(min_length=1)
    tools: list[ToolDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_tool_names(self) -> Self:
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique within the request")
        return self
