from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from moseby.identifiers import NotificationId
from moseby.runtime.models.common import JsonObject

from .common import Row


class PublishedEventRow(Row):
    """One durable publication; the recipient tracks whether it has been handled."""

    sequence: int
    notification_id: NotificationId
    created_at: int
    format_version: Literal[1]
    payload: JsonObject


class EventPosition(BaseModel):
    """Read up to 100 visible events after a saved sequence, with gaps allowed."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    after_sequence: int = Field(default=0, ge=0, le=2**63 - 1)
    limit: int = Field(default=50, ge=1, le=100)


class EventPage(BaseModel):
    items: list[PublishedEventRow]
    next_sequence: int
