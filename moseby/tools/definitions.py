from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass

from pydantic import BaseModel, Field

from moseby.agents.models import (
    AgentDomainContext,
    AgentModel,
    AgentThreadContext,
    ToolSpecification,
)
from moseby.common.types import NonemptyText
from moseby.identifiers import RunId, ThreadRecordId
from moseby.inference.models.generation import ToolDefinition
from moseby.permissions import Permission
from moseby.runtime.models.common import ToolCallId


class ToolContext(AgentModel):
    """Trusted staff and job details supplied by the runtime to a tool handler."""

    domain_context: AgentDomainContext
    thread_context: AgentThreadContext
    run_id: RunId
    source_record_id: ThreadRecordId
    tool_call_id: ToolCallId
    request_id: NonemptyText = Field(
        description="Accepted request ID, reused across retries of this tool call."
    )


@dataclass(frozen=True)
class Tool[Arguments: BaseModel, Result: BaseModel]:
    """Keep the tool's schema, permissions and executable handler together."""

    name: str
    description: str
    arguments: type[Arguments]
    result: type[Result]
    required_permissions: tuple[Permission, ...]
    handler: Callable[[ToolContext, Arguments], Awaitable[Result]]

    @property
    def specification(self) -> ToolSpecification:
        """Describe arguments using the same model that validates execution."""
        return ToolSpecification(
            definition=ToolDefinition(
                name=self.name,
                description=self.description,
                parameters=self.arguments.model_json_schema(),
            ),
            required_permissions=self.required_permissions,
        )


def index_tools(tools: Iterable[Tool]) -> dict[str, Tool]:
    """Validate tool descriptions and reject duplicate names at registration."""
    indexed = {}
    for tool in tools:
        name = tool.specification.definition.name
        if name in indexed:
            raise ValueError(f"Tool {name!r} is registered twice")
        indexed[name] = tool
    return indexed
