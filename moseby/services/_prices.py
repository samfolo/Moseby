"""Present nightly rates consistently in room searches and saved stays."""

from moseby.contracts.amounts import NonNegativeAmount
from moseby.contracts.rooms import NightlyPrice
from moseby.identifiers import PriceId


def nightly_price(
    price_id: PriceId, revision: int, amount_minor: int, currency: str
) -> NightlyPrice:
    return NightlyPrice(
        price_id=price_id,
        revision=revision,
        amount=NonNegativeAmount(value=amount_minor, currency=currency),
    )
