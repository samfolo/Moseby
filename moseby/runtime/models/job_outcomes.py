"""The final outcome shared by a job and its saved delivery."""

from typing import Literal, Self

from pydantic import model_validator

from moseby.identifiers import JobId
from moseby.runtime.enums import JobStatus

from .common import ErrorDetails, JsonObject, RuntimeModel
from .messages import (
    CancelledToolResultPayload,
    FailedToolResultPayload,
    SuccessfulToolResultPayload,
    ToolResultPayload,
    ToolResultStatus,
)
from .thread_records import ControlEventPayload


class JobOutcome(RuntimeModel):
    status: Literal[JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED]
    result: JsonObject | None = None
    error: ErrorDetails | None = None

    @model_validator(mode="after")
    def check_outcome(self) -> Self:
        if self.status == JobStatus.SUCCEEDED:
            if self.error is not None:
                raise ValueError("a successful job cannot have an error")
        elif self.error is None or self.result is not None:
            raise ValueError(
                "a failed or cancelled job requires an error and no result"
            )
        return self


def completion_payload(
    job_id: JobId, outcome: JobOutcome, *, tool_result: bool
) -> ToolResultPayload | ControlEventPayload:
    """Represent a tool's answer or an independent job's completion in thread history."""
    if not tool_result:
        return ControlEventPayload(
            name="job.finished",
            data={"job_id": job_id, **outcome.model_dump(mode="json")},
        )
    if outcome.status == JobStatus.SUCCEEDED:
        return SuccessfulToolResultPayload(
            job_id=job_id, status=ToolResultStatus.SUCCEEDED, result=outcome.result
        )
    if outcome.error is None:
        raise ValueError("a failed or cancelled job requires an error")
    if outcome.status == JobStatus.FAILED:
        return FailedToolResultPayload(
            job_id=job_id, status=ToolResultStatus.FAILED, error=outcome.error
        )
    return CancelledToolResultPayload(
        job_id=job_id, status=ToolResultStatus.CANCELLED, reason=outcome.error.message
    )
