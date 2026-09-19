from typing import Annotated

from pydantic import Field

from .common import Contract

type Currency = Annotated[
    str,
    Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 currency code, such as GBP."),
]


class Amount(Contract):
    """A monetary value and its currency, kept together."""

    value: int = Field(description="Integer currency minor units; GBP 10.50 is 1050.")
    currency: Currency


class NonNegativeAmount(Amount):
    """A price that cannot be negative; zero permits complimentary items."""

    value: int = Field(ge=0, description="Nonnegative integer currency minor units.")
