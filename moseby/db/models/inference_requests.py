from typing import Literal

from moseby.common.types import JsonObject, NonemptyText
from moseby.identifiers import InferenceRequestId, RunId, ThreadId
from moseby.runtime.enums import InferencePurpose, InferenceStatus

from .common import Row, StoredEnum


class InferenceRequestRow(Row):
    id: InferenceRequestId
    thread_id: ThreadId | None
    run_id: RunId | None
    purpose: StoredEnum[InferencePurpose]
    provider: str
    model: str
    format_version: Literal[1]
    request: JsonObject
    response: JsonObject | None
    error: JsonObject | None
    status: StoredEnum[InferenceStatus]
    created_at: int
    updated_at: int
    started_at: int | None
    finished_at: int | None


class NewInferenceRequest(Row):
    id: InferenceRequestId
    thread_id: ThreadId
    run_id: RunId
    provider: NonemptyText
    model: NonemptyText
    request: JsonObject
