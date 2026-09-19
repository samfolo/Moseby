from pydantic import Field

from .common import Contract


class Address(Contract):
    """Postal location; fields may be absent where they do not apply."""

    line_1: str | None = None
    line_2: str | None = None
    city: str | None = None
    postcode: str | None = None
    country_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{2}$",
        description="Two-letter ISO 3166-1 country code.",
    )
