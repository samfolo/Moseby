from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .amounts import Currency
from .common import Contract


class NumberRange(Contract):
    """Inclusive integer bounds; omit either bound for an open-ended range."""

    min_value: int | None = None
    max_value: int | None = None

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
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
    """Inclusive minor-unit bounds, compared only within the given currency."""

    currency: Currency


class DateRange(Contract):
    """An interval of instants, including its lower bound and excluding its upper bound."""

    min_date: AwareDatetime | None = Field(default=None, description="Inclusive lower bound.")
    max_date: AwareDatetime | None = Field(default=None, description="Exclusive upper bound.")

    @model_validator(mode="after")
    def check_bounds(self) -> Self:
        if self.min_date is None and self.max_date is None:
            raise ValueError("supply at least one range bound")
        if self.min_date is not None and self.max_date is not None and self.min_date >= self.max_date:
            raise ValueError("min_date must precede max_date")
        return self


class AvailabilityWindow(DateRange):
    """Both bounds are required to find rooms free for the entire interval."""

    min_date: AwareDatetime = Field(description="Inclusive start of required availability.")
    max_date: AwareDatetime = Field(description="Exclusive end of required availability.")

