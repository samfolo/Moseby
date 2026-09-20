"""Accepted operations and their progress; task execution stays inside the runtime."""

from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from moseby.identifiers import JobId, RunId, StaffMemberId, ThreadId, ThreadRecordId
from moseby.runtime.models.common import ErrorDetails, JsonObject, ToolCallId

from .common import Contract, PageRequest, Request


class JobStatus(StrEnum):
    QUEUED = "JOB_STATUS_QUEUED"
    RUNNING = "JOB_STATUS_RUNNING"
    WAITING = "JOB_STATUS_WAITING"
    SUCCEEDED = "JOB_STATUS_SUCCEEDED"
    FAILED = "JOB_STATUS_FAILED"
    CANCELLED = "JOB_STATUS_CANCELLED"


class Job(Contract):
    id: JobId
    actor_staff_member_id: StaffMemberId
    operation: str = Field(
        min_length=1, description="Registered action requested by the caller."
    )
    thread_id: ThreadId | None
    run_id: RunId | None
    source_record_id: ThreadRecordId | None
    tool_call_id: ToolCallId | None
    phase: str = Field(
        min_length=1, description="Current step of the registered workflow."
    )
    status: JobStatus
    input: JsonObject = Field(
        description="Accepted arguments in the operation's schema."
    )
    result: JsonObject | None = Field(
        description="Saved outcome in the operation's result schema."
    )
    error: ErrorDetails | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    finished_at: AwareDatetime | None

    @model_validator(mode="after")
    def check_state(self) -> Self:
        terminal = self.status in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )
        if terminal != (self.finished_at is not None):
            raise ValueError("finished_at is required exactly when the job is terminal")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be at or after created_at")
        if (
            self.finished_at is not None
            and not self.created_at <= self.finished_at <= self.updated_at
        ):
            raise ValueError("finished_at must be between created_at and updated_at")
        if self.run_id is not None and self.thread_id is None:
            raise ValueError("a run requires a thread")
        if (self.source_record_id is None) != (self.tool_call_id is None):
            raise ValueError(
                "source_record_id and tool_call_id must be supplied together"
            )
        if self.source_record_id is not None and self.run_id is None:
            raise ValueError("a tool job requires a run")
        return self


class CreateJobRequestPayload(Contract):
    operation: str = Field(
        min_length=1,
        description="Publicly registered operation; its permissions and input schema are checked at admission.",
    )
    input: JsonObject
    thread_id: ThreadId | None = Field(
        default=None, description="Optional owned thread receiving the job's outcome."
    )


class CreateJobRequest(Request[CreateJobRequestPayload]):
    pass


class ListJobsRequest(PageRequest):
    thread_id: ThreadId | None = None
    run_id: RunId | None = None
