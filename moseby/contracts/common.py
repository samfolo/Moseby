from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


Identifier = Annotated[str, Field(min_length=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Request[T](Contract):
    request_id: Identifier = Field(
        description="Identifies this logical request; reuse it when retrying."
    )
    payload: T


class Page[T](Contract):
    items: list[T]
    next_cursor: str | None = Field(
        description="Opaque continuation token; null means there are no more results."
    )


class PageRequest(Contract):
    cursor: str | None = Field(default=None, description="Continue the same query.")
    limit: int = Field(default=50, ge=1, le=100)
