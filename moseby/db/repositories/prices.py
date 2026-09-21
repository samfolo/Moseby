"""Resolve current catalogue prices or the exact version saved on a reservation."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, and_, select

from moseby.identifiers import PriceId

from ..models.prices import PriceRow, PriceVersionRow
from ..tables import price_versions, prices
from ._queries import latest_revision, unique_ids


def _select() -> Select:
    """Attach the highest saved revision to each shared price identity."""
    return select(
        prices,
        price_versions.c.revision,
        price_versions.c.amount_minor,
        price_versions.c.currency,
        price_versions.c.created_at.label("revised_at"),
    ).join(
        price_versions,
        and_(
            price_versions.c.price_id == prices.c.id,
            price_versions.c.revision
            == latest_revision(price_versions, price_versions.c.price_id, prices.c.id),
        ),
    )


def find_by_id(connection: Connection, id: PriceId) -> PriceRow | None:
    """Fetch a price's latest amount, or None if the ID or its first version is missing."""
    row = (
        connection.execute(_select().where(prices.c.id == id)).mappings().one_or_none()
    )
    return PriceRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection, ids: Sequence[PriceId]
) -> dict[PriceId, PriceRow]:
    """Fetch up to 100 price IDs with their latest amounts, keyed by ID.

    Omit missing prices and prices without a version. Repeats appear once; empty
    input returns an empty dictionary. More than 100 supplied IDs raises ValueError.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(_select().where(prices.c.id.in_(ids))).mappings()
    return {row["id"]: PriceRow.model_validate(dict(row)) for row in rows}


def find_by_id_and_revision(
    connection: Connection, id: PriceId, revision: int
) -> PriceVersionRow | None:
    """Fetch exactly the requested price version, or None if that pair is missing.

    Use the reservation's saved revision to preserve the amount agreed at booking.
    A missing version never falls back to the current catalogue rate.
    """
    row = (
        connection.execute(
            select(price_versions).where(
                price_versions.c.price_id == id, price_versions.c.revision == revision
            )
        )
        .mappings()
        .one_or_none()
    )
    return PriceVersionRow.model_validate(dict(row)) if row is not None else None
