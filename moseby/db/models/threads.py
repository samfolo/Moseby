from typing import Literal, Self

from pydantic import Field, model_validator

from moseby.identifiers import StaffMemberId, ThreadId
from moseby.permissions import Permission
from moseby.runtime.models.common import JsonObject

from .common import Row


class ThreadRow(Row):
    """The saved thread summary, including the permissions needed to check access."""

    id: ThreadId
    creator_staff_member_id: StaffMemberId
    title: str | None
    created_at: int
    updated_at: int
    archived_at: int | None
    permissions: list[Permission]
    projection_sequence: int
    projection_format_version: Literal[1]
    projection: JsonObject


class ProjectionUpdate(Row):
    """The runtime's summary after applying the next record to the history it read."""

    expected_sequence: int = Field(
        ge=0, description="Position of the saved summary when the runtime read it."
    )
    expected_history_sequence: int = Field(
        ge=1, description="Last history position used to prepare the new summary."
    )
    value: JsonObject = Field(
        description="Summary including that history and the record being appended."
    )
    format_version: Literal[1] = 1

    @model_validator(mode="after")
    def check_positions(self) -> Self:
        if self.expected_sequence > self.expected_history_sequence:
            raise ValueError("the projection cannot be ahead of its source history")
        return self
