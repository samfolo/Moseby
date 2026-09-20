"""Future actions and the accepted firings that link them to jobs."""

from typing import Annotated, Literal, Self, TypedDict

from pydantic import AwareDatetime, ConfigDict, Field, model_validator, with_config

from moseby.identifiers import (
    JobId,
    ScheduleId,
    ScheduleOccurrenceId,
    StaffMemberId,
    ThreadId,
)
from moseby.runtime.models.common import JsonObject

from .common import Contract, PageRequest, Request


class ScheduleTiming(Contract):
    due_at: AwareDatetime | None = Field(
        default=None, description="One-off firing time."
    )
    cron_expression: str | None = Field(
        default=None,
        min_length=1,
        description="Recurring expression evaluated in UTC by the named dialect.",
    )
    cron_dialect: str | None = Field(
        default=None,
        min_length=1,
        description="Registered parser dialect; the service validates the expression with that parser.",
    )

    @model_validator(mode="after")
    def check_timing(self) -> Self:
        one_off = (
            self.due_at is not None
            and self.cron_expression is None
            and self.cron_dialect is None
        )
        recurring = (
            self.due_at is None
            and self.cron_expression is not None
            and self.cron_dialect is not None
        )
        if not (one_off or recurring):
            raise ValueError("supply due_at or both cron_expression and cron_dialect")
        return self


class ScheduleDefinition(Contract):
    timing: ScheduleTiming
    thread_id: ThreadId | None = Field(
        default=None,
        description="Owned destination thread; required by handlers that deliver conversational input or results.",
    )
    handler: str = Field(
        min_length=1,
        description="Publicly registered schedule handler; the service checks its permissions.",
    )
    input: JsonObject = Field(
        description="Arguments validated by the registered handler."
    )


class Schedule(ScheduleDefinition):
    id: ScheduleId
    actor_staff_member_id: StaffMemberId
    revision: int = Field(
        ge=1, strict=True, description="Increases on each accepted edit."
    )
    enabled: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def check_times(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be at or after created_at")
        return self


class CreateScheduleRequestPayload(ScheduleDefinition):
    enabled: bool = True


class CreateScheduleRequest(Request[CreateScheduleRequestPayload]):
    pass


type UpdateScheduleFieldMask = Literal[
    "timing", "thread_id", "handler", "input", "enabled"
]


@with_config(ConfigDict(extra="forbid"))
class UpdateScheduleRequestPayload(TypedDict, total=False):
    """Masked values replace whole fields; timing and input are replaced as objects."""

    timing: ScheduleTiming
    thread_id: ThreadId | None
    handler: Annotated[str, Field(min_length=1)]
    input: JsonObject
    enabled: bool


class UpdateScheduleRequest(Request[UpdateScheduleRequestPayload]):
    expected_revision: int = Field(
        ge=1,
        strict=True,
        description="Reject the edit if another writer has changed this revision.",
    )
    update_mask: list[UpdateScheduleFieldMask] = Field(min_length=1)

    @model_validator(mode="after")
    def check_mask(self) -> Self:
        fields = set(self.update_mask)
        if len(fields) != len(self.update_mask) or fields != set(self.payload):
            raise ValueError("update_mask must name each supplied field exactly once")
        return self


class ListSchedulesRequest(PageRequest):
    thread_id: ThreadId | None = None


class ScheduleOccurrence(Contract):
    id: ScheduleOccurrenceId
    schedule_id: ScheduleId
    schedule_revision: int = Field(
        ge=1, strict=True, description="Revision used when the firing was accepted."
    )
    due_at: AwareDatetime
    created_at: AwareDatetime = Field(
        description="Time the scheduler accepted this firing."
    )
    job_id: JobId = Field(
        description="Read this job for progress, errors and the outcome."
    )

    @model_validator(mode="after")
    def check_times(self) -> Self:
        if self.created_at < self.due_at:
            raise ValueError("an occurrence cannot be accepted before it is due")
        return self


class ListScheduleOccurrencesRequest(PageRequest):
    schedule_id: ScheduleId
