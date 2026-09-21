"""Translate our messages and questions to and from OpenRouter's JSON shapes."""

import json
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter

from moseby.runtime.models.messages import ToolCall

from .._json import parse_object
from ..errors import InferenceError, InferenceErrorCode
from ..models.classification import (
    ClassificationKind,
    ClassificationOutput,
    ClassificationRequest,
)
from ..models.common import JsonObject, NonemptyText
from ..models.generation import AssistantMessage, GenerationRequest


class _FunctionCall(BaseModel):
    name: NonemptyText
    arguments: str


class _ToolCall(BaseModel):
    id: NonemptyText
    type: Literal["function"] = "function"
    function: _FunctionCall


class _AssistantMessage(BaseModel):
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    tool_calls: list[_ToolCall] | None = None


class _ChatChoice(BaseModel):
    finish_reason: str
    message: _AssistantMessage


class _ChatResponse(BaseModel):
    choices: list[_ChatChoice] = Field(min_length=1, max_length=1)


_ANSWERS = TypeAdapter(dict[str, JsonObject])
_QUESTION_TYPES = {
    ClassificationKind.BOOLEAN: "noul",
    ClassificationKind.CHOICE: "choice",
}


def chat_body(request: GenerationRequest, model: str) -> JsonObject:
    """Encode tool arguments once, preserving continuation fields from earlier replies."""
    messages = []
    for message in request.messages:
        if isinstance(message, AssistantMessage):
            encoded = {
                key: value
                for key, value in message.provider_state.items()
                if key not in {"role", "content", "tool_calls"}
            } | {
                "role": "assistant",
                "content": message.text,
            }
            if message.tool_calls:
                encoded["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, allow_nan=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            messages.append(encoded)
        else:
            messages.append(message.model_dump(mode="json"))
    body = {"model": model, "messages": messages, "stream": False}
    if request.tools:
        body["tools"] = [
            {"type": "function", "function": tool.model_dump(mode="json")}
            for tool in request.tools
        ]
    return body


def read_chat_response(response: JsonObject) -> AssistantMessage:
    """Accept a finished reply and keep opaque fields needed for its next request."""
    choice = _ChatResponse.model_validate(response).choices[0]
    if choice.finish_reason not in {"stop", "tool_calls"}:
        raise InferenceError(
            InferenceErrorCode.INCOMPLETE_RESPONSE,
            "The model did not finish its reply.",
        )
    output = AssistantMessage(
        text=choice.message.content or None,
        tool_calls=[
            ToolCall(
                id=call.id,
                name=call.function.name,
                arguments=parse_object(call.function.arguments),
            )
            for call in choice.message.tool_calls or []
        ],
        provider_state={
            name: value
            for name, value in response["choices"][0]["message"].items()
            if name not in {"role", "content", "tool_calls"}
        },
    )
    if (choice.finish_reason == "tool_calls") != bool(output.tool_calls):
        raise ValueError("finish reason and tool calls disagree")
    return output


def decisions_body(request: ClassificationRequest, model: str) -> JsonObject:
    """Send all questions together against the same evidence and candidate list."""
    return {
        "model": model,
        "state": request.model_dump(mode="json")["state"],
        "questions": {
            name: question.model_dump(mode="json", exclude={"kind"})
            | {"type": _QUESTION_TYPES[question.kind]}
            for name, question in request.questions.items()
        },
    }


def read_decisions_response(response: JsonObject) -> ClassificationOutput:
    """Translate the provider's answer types into application classification results."""
    answers = {}
    for name, answer in _ANSWERS.validate_python(response.get("answers")).items():
        if answer.get("type") == "noul":
            answers[name] = {
                "kind": ClassificationKind.BOOLEAN,
                "probability": answer.get("noul"),
            }
        elif answer.get("type") == "choice":
            answers[name] = {
                key: value for key, value in answer.items() if key != "type"
            } | {"kind": ClassificationKind.CHOICE}
        else:
            raise ValueError("unsupported classification answer type")
    return ClassificationOutput.model_validate({"answers": answers})
