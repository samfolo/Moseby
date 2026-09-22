"""Reported token counts and the work counted toward one autonomous run."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)
    cache_read_tokens: int = Field(default=0, ge=0, strict=True)
    cache_write_tokens: int = Field(default=0, ge=0, strict=True)
    reasoning_tokens: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description="Reported reasoning subtotal; null when unavailable or inconsistent with output.",
    )

    @model_validator(mode="after")
    def check_subtotals(self) -> Self:
        if self.cache_read_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError("Cache counts cannot exceed input tokens")
        if (
            self.reasoning_tokens is not None
            and self.reasoning_tokens > self.output_tokens
        ):
            raise ValueError("Reasoning tokens cannot exceed output tokens")
        return self

    @property
    def budget_tokens(self) -> int:
        """Count fresh input and all output; cache writes are already part of input."""
        return self.input_tokens - self.cache_read_tokens + self.output_tokens
