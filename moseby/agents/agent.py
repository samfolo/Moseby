from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from moseby.inference.models.generation import ToolDefinition
from moseby.permissions import Permission, PermissionResolver

from .identity import AgentReference
from .models import (
    AgentDefinition,
    AgentDomainContext,
    AgentThreadContext,
    ToolSpecification,
)


@dataclass(frozen=True)
class Agent:
    """A definition resolved for one staff member and one thread."""

    definition: AgentDefinition
    domain_context: AgentDomainContext
    thread_context: AgentThreadContext
    permissions: tuple[Permission, ...]
    tools: tuple[ToolDefinition, ...]


def create_agent(
    definition: AgentDefinition,
    *,
    domain_context: AgentDomainContext,
    thread_context: AgentThreadContext,
    tools: Mapping[str, ToolSpecification],
) -> Agent:
    """Check thread access, then expose only the agent's permitted tools.

    The caller supplies current authority and saved thread context. Resolve these
    again when a run resumes; tool handlers also check authority when executing.
    """
    if domain_context.staff_member_id != thread_context.creator_staff_member_id:
        raise PermissionError("Only the thread creator may use this thread")
    if any(
        not PermissionResolver.allows(domain_context.permissions, scope)
        for scope in thread_context.permissions
    ):
        raise PermissionError("Current staff permissions no longer cover this thread")
    if (definition.id, definition.version) != (
        thread_context.agent.id,
        thread_context.agent.version,
    ):
        raise ValueError("The definition does not match the thread's selected agent")

    # The original thread limits still apply if the staff member gains new access.
    permissions = PermissionResolver.intersection(
        definition.permissions, thread_context.permissions
    )
    selected = []
    for name in definition.tools:
        specification = tools.get(name)
        if specification is None or specification.definition.name != name:
            raise ValueError(f"Tool {name!r} is missing or incorrectly registered")
        if all(
            PermissionResolver.allows(permissions, scope)
            for scope in specification.required_permissions
        ):
            selected.append(specification.definition.model_copy(deep=True))

    return Agent(
        definition=definition,
        domain_context=domain_context,
        thread_context=thread_context,
        permissions=permissions,
        tools=tuple(selected),
    )


def index_agent_definitions(
    definitions: Iterable[AgentDefinition],
) -> dict[AgentReference, AgentDefinition]:
    """Index code-defined agents, rejecting duplicate IDs at the same version."""
    indexed = {}
    for definition in definitions:
        reference = AgentReference(id=definition.id, version=definition.version)
        if reference in indexed:
            raise ValueError(
                f"Agent {reference.id!r} version {reference.version} is registered twice"
            )
        indexed[reference] = definition
    return indexed
