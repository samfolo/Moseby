"""Database timestamps remain integer UTC microseconds until service mapping."""

from pydantic import BaseModel, ConfigDict


class Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
