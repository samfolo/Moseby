from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from moseby.identifiers import AgentId


class AgentReference(BaseModel):
    """The exact agent definition selected for a thread."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: AgentId = Field(description="Stable code-defined ID, such as concierge.")
    version: int = Field(
        gt=0, strict=True, description="Version of this agent's settings."
    )


class AgentAttribution(BaseModel):
    """Queryable agent identity; both fields are absent for unattributed history."""

    agent_id: AgentId | None = Field(
        default=None, description="Agent that owns this work."
    )
    agent_version: int | None = Field(
        default=None, gt=0, strict=True, description="Version selected for this work."
    )

    @model_validator(mode="after")
    def check_pair(self) -> Self:
        if (self.agent_id is None) != (self.agent_version is None):
            raise ValueError("agent_id and agent_version must be supplied together")
        return self
