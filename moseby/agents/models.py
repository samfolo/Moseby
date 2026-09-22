from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from moseby.common.types import NonemptyText
from moseby.identifiers import HotelId, StaffMemberId, ThreadId
from moseby.inference.models.generation import ToolDefinition
from moseby.permissions import Permission
from moseby.runtime.models.thread_records import ThreadCreatedRecord

from .identity import AgentReference


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentDefinition(AgentReference):
    """Serializable settings shared by every instance of this agent."""

    display_name: NonemptyText
    description: NonemptyText
    system_prompt: NonemptyText = Field(
        description="Complete instructions for the agent."
    )
    tools: tuple[NonemptyText, ...] = Field(
        description="Names to resolve from the tool catalogue."
    )
    permissions: tuple[Permission, ...] = Field(
        description="Upper limit on what this agent may do."
    )
    max_turns: int = Field(
        gt=0, strict=True, description="Maximum generation requests in one run."
    )
    token_budget: int = Field(
        gt=0,
        strict=True,
        description="Uncached input plus all output across generation and classification in one run; missing cache details count fully.",
    )

    @field_validator("display_name", "description", "system_prompt")
    @classmethod
    def check_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must contain more than whitespace")
        return value

    @model_validator(mode="after")
    def check_selections(self) -> Self:
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("tool names must be unique")
        if any(not name.strip() for name in self.tools):
            raise ValueError("tool names must contain more than whitespace")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("permissions must contain unique codes")
        return self


class AgentDomainContext(AgentModel):
    """Current staff identity and authority supplied by trusted application code."""

    staff_member_id: StaffMemberId
    hotel_id: HotelId
    staff_member_display_name: NonemptyText = Field(
        description="The staff member’s name for conversation and attribution."
    )
    permissions: tuple[Permission, ...]


class AgentThreadContext(AgentModel):
    """The chosen agent and access limits captured when the thread was created."""

    thread_id: ThreadId
    agent: AgentReference
    creator_staff_member_id: StaffMemberId
    permissions: tuple[Permission, ...]

    @classmethod
    def from_creation_record(cls, record: ThreadCreatedRecord) -> Self:
        """Restore the agent selection and permission limits from saved history."""
        if record.payload.agent is None:
            raise ValueError(
                "The thread's creation record has no saved agent selection"
            )
        return cls(
            thread_id=record.thread_id,
            agent=record.payload.agent,
            creator_staff_member_id=record.payload.creator_staff_member_id,
            permissions=tuple(record.payload.permissions),
        )


class ToolSpecification(AgentModel):
    """A model-facing tool definition and the permissions its handler requires."""

    definition: ToolDefinition
    required_permissions: tuple[Permission, ...] = Field(
        description="Every listed permission must be allowed before offering the tool."
    )
