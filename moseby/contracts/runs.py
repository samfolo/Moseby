from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from moseby.identifiers import RunId, StaffMemberId, ThreadId

from .common import Contract


class RunStatus(StrEnum):
    QUEUED = "RUN_STATUS_QUEUED"
    RUNNING = "RUN_STATUS_RUNNING"
    WAITING = "RUN_STATUS_WAITING"
    COMPLETED = "RUN_STATUS_COMPLETED"
    FAILED = "RUN_STATUS_FAILED"
    CANCELLED = "RUN_STATUS_CANCELLED"


class Run(Contract):
    id: RunId
    thread_id: ThreadId
    status: RunStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    wake_at: AwareDatetime | None = Field(
        description="Scheduled continuation time for a waiting run."
    )
    cancel_requested_at: AwareDatetime | None
    cancel_requested_by_staff_member_id: StaffMemberId | None
    recovery_attempts: int = Field(
        ge=0,
        strict=True,
        description="Attempts to recover this run after interruption.",
    )
    finished_at: AwareDatetime | None

    @model_validator(mode="after")
    def check_state(self) -> Self:
        terminal = self.status in (
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        )
        if terminal != (self.finished_at is not None):
            raise ValueError("finished_at is required exactly when the run is terminal")
        if self.wake_at is not None and self.status != RunStatus.WAITING:
            raise ValueError("wake_at requires a waiting run")
        if (self.cancel_requested_at is None) != (
            self.cancel_requested_by_staff_member_id is None
        ):
            raise ValueError(
                "cancellation time and staff member must be supplied together"
            )
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be at or after created_at")
        for name in ("cancel_requested_at", "finished_at"):
            value = getattr(self, name)
            if value is not None and not self.created_at <= value <= self.updated_at:
                raise ValueError(f"{name} must be between created_at and updated_at")
        return self
