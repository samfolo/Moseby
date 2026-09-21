"""Database search values, separate from HTTP envelopes and pagination."""

from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _sorted_values[T: str](values: list[T]) -> list[T]:
    """Give equivalent lists the same cursor identity, ignoring order and repeats."""
    return sorted(set(values))


type IdFilter[T] = Annotated[
    list[T], Field(min_length=1, max_length=100), AfterValidator(_sorted_values)
]


class Filters(BaseModel):
    """Match any value within each list and require all supplied filters to match."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class DateRange(Filters):
    """UTC microsecond interval; include min_date and exclude max_date."""

    min_date: int
    max_date: int

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        """Reject empty or reversed intervals before building a query."""
        if self.min_date >= self.max_date:
            raise ValueError("min_date must precede max_date")
        return self


class NumberRange(Filters):
    """Inclusive integer bounds; supply either or both ends of the range."""

    min_value: int | None = None
    max_value: int | None = None

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        """Require a bound and reject a minimum greater than the maximum."""
        if self.min_value is None and self.max_value is None:
            raise ValueError("supply at least one range bound")
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("min_value must not exceed max_value")
        return self


class AmountRange(NumberRange):
    """Inclusive minor-unit bounds within one currency; no currency conversion."""

    currency: str = Field(pattern=r"^[A-Z]{3}$")
