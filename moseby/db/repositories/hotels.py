"""Read hotel information within the scope supplied by the service."""

from sqlalchemy import Connection, select

from moseby.identifiers import HotelId

from ..models.hotels import HotelRow
from ..pagination import Page, PageRequest, read_page
from ..tables import hotels


def find_by_id(
    connection: Connection, id: HotelId, *, hotel_id: HotelId
) -> HotelRow | None:
    """Fetch the hotel if it matches the caller's scope; otherwise return None."""
    row = (
        connection.execute(
            select(hotels).where(hotels.c.id == id, hotels.c.id == hotel_id)
        )
        .mappings()
        .one_or_none()
    )
    return HotelRow.model_validate(dict(row)) if row is not None else None


def find_all(
    connection: Connection, *, hotel_id: HotelId, page: PageRequest | None = None
) -> Page[HotelRow]:
    """Fetch the hotels in this scope as a page, ordered by creation time, then ID.

    A single-hotel scope produces at most one result; a missing hotel gives an
    empty page. The service supplies scope independently of request filters.
    """
    return read_page(
        connection,
        select(hotels).where(hotels.c.id == hotel_id),
        table=hotels,
        row_type=HotelRow,
        page=page or PageRequest(),
        query="hotels.find_all",
        criteria={"hotel_id": hotel_id},
    )
