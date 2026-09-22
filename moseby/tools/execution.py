import json
from collections.abc import Mapping
from enum import StrEnum

from pydantic import ValidationError

from moseby.agents.agent import Agent, create_agent
from moseby.runtime.models.common import ErrorDetails
from moseby.runtime.models.messages import (
    FailedToolResultPayload,
    SuccessfulToolResultPayload,
    ToolCall,
    ToolResultPayload,
    ToolResultStatus,
)

from .definitions import Tool, ToolContext


class ToolErrorCode(StrEnum):
    INTERRUPTED = "TOOL_ERROR_INTERRUPTED"
    EXECUTION_FAILED = "TOOL_ERROR_EXECUTION_FAILED"
    NOT_AVAILABLE = "TOOL_ERROR_NOT_AVAILABLE"
    PERMISSION_DENIED = "TOOL_ERROR_PERMISSION_DENIED"
    INVALID_ARGUMENTS = "TOOL_ERROR_INVALID_ARGUMENTS"


class ToolFailure(Exception):
    """An expected failure with details that are safe to return to the model."""

    def __init__(self, error: ErrorDetails):
        super().__init__(error.message)
        self.error = error


async def execute_tool(
    agent: Agent,
    call: ToolCall,
    *,
    context: ToolContext,
    tools: Mapping[str, Tool],
) -> ToolResultPayload:
    """Check access and arguments, then run the handler and validate its result.

    The runtime supplies current staff authority and context from the claimed job.
    Unexpected handler errors propagate to the worker's failure handling.
    """
    if (
        context.thread_context != agent.thread_context
        or context.tool_call_id != call.id
    ):
        raise ValueError("Tool execution context does not match the thread and call")

    # Refresh access so a saved loadout cannot retain revoked permissions.
    try:
        current = create_agent(
            agent.definition,
            domain_context=context.domain_context,
            thread_context=context.thread_context,
            tools={name: tool.specification for name, tool in tools.items()},
        )
    except PermissionError:
        return _failure(
            ToolErrorCode.PERMISSION_DENIED,
            "The staff member no longer has access to this thread.",
        )
    if call.name not in {tool.name for tool in current.tools}:
        return _failure(
            ToolErrorCode.NOT_AVAILABLE, "This tool is not available to the agent."
        )
    tool = tools[call.name]

    # Return field paths and messages while omitting raw argument values.
    try:
        arguments = tool.arguments.model_validate(call.arguments)
    except ValidationError as error:
        return FailedToolResultPayload(
            status=ToolResultStatus.FAILED,
            error=ErrorDetails(
                code=ToolErrorCode.INVALID_ARGUMENTS,
                message="Correct the tool arguments and try again.",
                details={
                    "issues": json.loads(
                        error.json(
                            include_input=False,
                            include_context=False,
                            include_url=False,
                        )
                    )
                },
            ),
        )

    try:
        value = await tool.handler(context, arguments)
    except ToolFailure as error:
        return FailedToolResultPayload(
            status=ToolResultStatus.FAILED, error=error.error
        )

    # An invalid handler response is an application error for the worker to report.
    result = tool.result.model_validate(
        value.model_dump(warnings=False) if isinstance(value, tool.result) else value
    )
    return SuccessfulToolResultPayload(
        status=ToolResultStatus.SUCCEEDED, result=result.model_dump(mode="json")
    )


def _failure(code: ToolErrorCode, message: str) -> FailedToolResultPayload:
    return FailedToolResultPayload(
        status=ToolResultStatus.FAILED, error=ErrorDetails(code=code, message=message)
    )
