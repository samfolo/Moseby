"""Read the shared activity venue catalogue."""

from collections.abc import Sequence

from sqlalchemy import Connection, select

from moseby.identifiers import VenueId

from ..models.venues import VenueRow
from ..pagination import Page, PageRequest, read_page
from ..tables import venues
from ._queries import unique_ids


def find_by_id(connection: Connection, id: VenueId) -> VenueRow | None:
    """Fetch a shared venue and its address, or None if the ID is missing."""
    row = (
        connection.execute(select(venues).where(venues.c.id == id))
        .mappings()
        .one_or_none()
    )
    return VenueRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection, ids: Sequence[VenueId]
) -> dict[VenueId, VenueRow]:
    """Fetch up to 100 supplied IDs as a dictionary, omitting missing venues.

    Repeated IDs appear once and empty input returns an empty dictionary. More
    than 100 input IDs raises ValueError, including repeats in that limit.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(select(venues).where(venues.c.id.in_(ids))).mappings()
    return {row["id"]: VenueRow.model_validate(dict(row)) for row in rows}


def find_all(
    connection: Connection, *, page: PageRequest | None = None
) -> Page[VenueRow]:
    """Fetch shared venues, ordered by creation time, then ID.

    Include venues with zero administrative capacity. Pass next_cursor to
    continue; the catalogue does not depend on which hotel is querying it.
    """
    return read_page(
        connection,
        select(venues),
        table=venues,
        row_type=VenueRow,
        page=page or PageRequest(),
        query="venues.find_all",
        criteria={},
    )
