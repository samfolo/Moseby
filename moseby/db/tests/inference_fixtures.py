"""Scripted model replies for database-backed runtime tests."""

import json

from moseby.inference.models.common import InferenceResult
from moseby.inference.models.generation import AssistantMessage, ToolMessage
from moseby.runtime.models.messages import ToolCall, ToolResultStatus


class ScriptedProvider:
    def __init__(self, *replies, total_tokens=20):
        self.replies = iter(replies)
        self.requests = []
        self.total_tokens = total_tokens

    async def generate(self, request):
        self.requests.append(request)
        reply = next(self.replies)
        if callable(reply):
            reply = reply(request)
        if isinstance(reply, Exception):
            raise reply
        return InferenceResult(
            output=reply,
            request=request.model_dump(mode="json"),
            response={"choices": []},
            total_tokens=self.total_tokens,
        )


def tool_result(request):
    """Read the latest successful tool result so the next reply can use its saved IDs."""
    message = next(
        message
        for message in reversed(request.messages)
        if isinstance(message, ToolMessage)
    )
    result = json.loads(message.content)
    if result["status"] != ToolResultStatus.SUCCEEDED:
        raise AssertionError(result)
    return result["result"]


def tool_call(tool_name, **arguments):
    """Build a model reply that asks the runtime to execute one tool."""
    return AssistantMessage(
        tool_calls=[ToolCall(id=tool_name, name=tool_name, arguments=arguments)]
    )
