from .common import Row


class AddressRow(Row):
    """Optional postal columns shared by hotels and venues."""

    address_line_1: str | None
    address_line_2: str | None
    city: str | None
    postcode: str | None
    country_code: str | None
