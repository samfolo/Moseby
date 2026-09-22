"""Save party notes and check their guest references."""

from sqlalchemy import Connection, Select, func, insert, select
from sqlalchemy import update as sql_update

from moseby.domain.enums import GuestReferenceStatus
from moseby.identifiers import HotelId, PartyDetailId, PartyId

from ..errors import WriteConflict
from ..full_text import match_keywords
from ..models.party_details import (
    GuestReferences,
    NewPartyDetail,
    PartyDetailFilters,
    PartyDetailRow,
)
from ..pagination import Page, PageRequest, read_page
from ..tables import bookings, parties, party_details, party_details_fts
from . import guests as guests_repository
from . import parties as parties_repository
from ._writes import check_updated_at, require_found, require_write_transaction


def _select(hotel_id: HotelId) -> Select:
    """Follow party membership to the hotel and decode the stored guest-ID list.

    Each detail remains one result, regardless of how many guests it references.
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
    """Fetch a note with its saved guest references and resolution status.

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
    Each note appears once; guest filters match saved IDs even when other references are unclear.
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


# Writes


def create(
    connection: Connection, values: NewPartyDetail, *, hotel_id: HotelId, now: int
) -> PartyDetailRow:
    """Save the original note with empty guest references and a pending status."""
    require_write_transaction(connection)
    party = require_found(
        parties_repository.find_by_id(connection, values.party_id, hotel_id=hotel_id)
    )
    if now < party.created_at:
        raise WriteConflict("Evidence cannot precede its party")
    connection.execute(
        insert(party_details).values(
            **values.model_dump(),
            created_at=now,
            updated_at=now,
            referenced_guest_ids_json=[],
            reference_format_version=1,
            reference_status=GuestReferenceStatus.PENDING,
        )
    )
    return require_found(find_by_id(connection, values.id, hotel_id=hotel_id))


def save_references(
    connection: Connection,
    id: PartyDetailId,
    references: GuestReferences,
    *,
    expected_updated_at: int,
    hotel_id: HotelId,
    now: int,
) -> PartyDetailRow:
    """Settle pending references after checking that each guest belongs to the party."""
    require_write_transaction(connection)
    saved = require_found(find_by_id(connection, id, hotel_id=hotel_id))
    check_updated_at(saved.updated_at, expected_updated_at, now)
    if (
        saved.reference_status != GuestReferenceStatus.PENDING
        or references.status == GuestReferenceStatus.PENDING
    ):
        raise WriteConflict(
            "Guest references must move from pending to a settled status"
        )
    candidates = guests_repository.find_by_ids(
        connection, references.guest_ids, hotel_id=hotel_id
    )
    if len(candidates) != len(references.guest_ids) or any(
        guest.party_id != saved.party_id for guest in candidates.values()
    ):
        raise WriteConflict("Every referenced guest must belong to the note's party")
    connection.execute(
        sql_update(party_details)
        .where(party_details.c.id == id)
        .values(
            referenced_guest_ids_json=references.guest_ids,
            reference_status=references.status,
            updated_at=now,
        )
    )
    return require_found(find_by_id(connection, id, hotel_id=hotel_id))
