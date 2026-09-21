"""Read party evidence and saved guest references within one hotel."""

from sqlalchemy import Connection, Select, func, select

from moseby.identifiers import HotelId, PartyDetailId, PartyId

from ..full_text import match_keywords
from ..models.party_details import PartyDetailFilters, PartyDetailRow
from ..pagination import Page, PageRequest, read_page
from ..tables import bookings, parties, party_details, party_details_fts


def _select(hotel_id: HotelId) -> Select:
    """Follow party membership to the hotel and decode the stored guest-ID list.

    Each detail remains one result, regardless of how many guests it references.
    Reading the saved classification neither invokes the classifier nor updates facts.
    """
    return (
        select(
            party_details.c.id,
            party_details.c.party_id,
            party_details.c.text,
            party_details.c.referenced_guest_ids_json.label("referenced_guest_ids"),
            party_details.c.reference_format_version,
            party_details.c.reference_status,
            party_details.c.created_at,
            party_details.c.updated_at,
        )
        .join(parties, party_details.c.party_id == parties.c.id)
        .join(bookings, parties.c.booking_id == bookings.c.id)
        .where(bookings.c.hotel_id == hotel_id)
    )


def find_by_id(
    connection: Connection, id: PartyDetailId, *, hotel_id: HotelId
) -> PartyDetailRow | None:
    """Fetch evidence with its saved classification, including unresolved references.

    Return None for a missing ID or a party belonging to another hotel.
    """
    row = (
        connection.execute(_select(hotel_id).where(party_details.c.id == id))
        .mappings()
        .one_or_none()
    )
    return PartyDetailRow.model_validate(dict(row)) if row is not None else None


def find_all_by_party_id(
    connection: Connection,
    party_id: PartyId,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[PartyDetailRow]:
    """Fetch a party's evidence in creation-time and ID order, including unresolved notes.

    A missing or other hotel's party gives an empty page. Notes remain visible
    after a booking ends or is cancelled; pass next_cursor to continue.
    """
    return search(
        connection,
        PartyDetailFilters(party_ids=[party_id]),
        hotel_id=hotel_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: PartyDetailFilters,
    *,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[PartyDetailRow]:
    """Fetch a page of party evidence matching all filters, in creation-time and ID order.

    Match any listed party and referenced guest, using shared full-text matching.
    Each note appears once; unresolved references cannot match a guest filter.
    """
    statement = _select(hotel_id).where(party_details.c.party_id.in_(filters.party_ids))
    if filters.guest_ids is not None:
        references = func.json_each(
            party_details.c.referenced_guest_ids_json
        ).table_valued("value")
        statement = statement.where(
            select(1)
            .select_from(references)
            .where(references.c.value.in_(filters.guest_ids))
            .correlate(party_details)
            .exists()
        )
    if filters.text is not None:
        matches = select(party_details_fts.c.detail_id).where(
            match_keywords(party_details_fts.c.text, filters.text)
        )
        statement = statement.where(party_details.c.id.in_(matches))
    return read_page(
        connection,
        statement,
        table=party_details,
        row_type=PartyDetailRow,
        page=page or PageRequest(),
        query="party_details.search.keywords_v1",
        criteria={"hotel_id": hotel_id, "filters": filters.model_dump_json()},
    )
