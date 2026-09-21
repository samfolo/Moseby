"""Lifecycle values shared by runtime storage and public contracts."""

from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "RUN_STATUS_QUEUED"
    RUNNING = "RUN_STATUS_RUNNING"
    WAITING = "RUN_STATUS_WAITING"
    COMPLETED = "RUN_STATUS_COMPLETED"
    FAILED = "RUN_STATUS_FAILED"
    CANCELLED = "RUN_STATUS_CANCELLED"
