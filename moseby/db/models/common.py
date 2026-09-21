"""Database timestamps remain integer UTC microseconds until service mapping."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Parse stored strings as enum members while keeping other row fields strict.
type StoredEnum[T: StrEnum] = Annotated[T, Field(strict=False)]


class Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
