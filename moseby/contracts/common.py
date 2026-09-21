from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1)]

type IdFilter[T] = Annotated[
    list[T],
    Field(
        min_length=1,
        max_length=100,
        description="Match any listed ID; duplicates do not multiply results.",
    ),
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


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
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=2048,
        description="Continue the same query.",
    )
    limit: int = Field(default=50, ge=1, le=100)


class SearchRequestPayload(PageRequest):
    """OR within each ID list, AND across filters; paginate one flat result list."""
