from moseby.identifiers import PriceId

from .common import Row


class PriceRow(Row):
    """A shared price with its latest amount and revision."""

    id: PriceId
    created_at: int
    revision: int
    amount_minor: int
    currency: str
    revised_at: int


class PriceVersionRow(Row):
    """The amount agreed at one exact (price_id, revision) pair."""

    price_id: PriceId
    revision: int
    amount_minor: int
    currency: str
    created_at: int
