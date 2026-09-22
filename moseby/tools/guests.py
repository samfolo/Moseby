"""Guest discovery and note-taking tools for the concierge."""

import asyncio

from pydantic import AwareDatetime
from sqlalchemy import Engine

from moseby.contracts.common import Contract, Page
from moseby.contracts.guests import (
    Guest,
    SearchGuestsRequestPayload,
    UpdateGuestRequest,
    UpdateGuestRequestPayload,
)
from moseby.contracts.party_details import CreatePartyDetailRequestPayload, PartyDetail
from moseby.identifiers import GuestId, PartyDetailId
from moseby.runtime.guest_references import GuestReferenceRecorder
from moseby.runtime.tool_writes import claimed_write
from moseby.services import guests

from .definitions import Tool, ToolContext
from .errors import report_errors


class UpdateGuestArguments(Contract):
    guest_id: GuestId
    expected_updated_at: AwareDatetime
    changes: UpdateGuestRequestPayload
    evidence_detail_id: PartyDetailId | None = None


def create_tools(engine: Engine, recorder: GuestReferenceRecorder) -> tuple[Tool, ...]:
    async def search_guests(
        context: ToolContext, arguments: SearchGuestsRequestPayload
    ) -> Page[Guest]:
        with report_errors():
            return await asyncio.to_thread(
                guests.search,
                engine,
                arguments,
                hotel_id=context.domain_context.hotel_id,
                permissions=context.domain_context.permissions,
            )

    async def record_party_detail(
        context: ToolContext, arguments: CreatePartyDetailRequestPayload
    ) -> PartyDetail:
        with report_errors():
            return await recorder.record(context, arguments)

    async def update_guest(
        context: ToolContext, arguments: UpdateGuestArguments
    ) -> Guest:
        def write():
            request = UpdateGuestRequest(
                request_id=context.request_id,
                payload=arguments.changes,
                update_mask=list(arguments.changes),
                expected_updated_at=arguments.expected_updated_at,
                evidence_detail_id=arguments.evidence_detail_id,
            )
            with claimed_write(
                engine,
                context,
                permissions=(guests.READ_PERMISSION, guests.WRITE_PERMISSION),
            ) as (connection, now):
                return guests.update(
                    connection,
                    arguments.guest_id,
                    request,
                    context=context.domain_context,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    return (
        Tool(
            name="update_guest",
            description="Update selected guest fields using updated_at from guest search or stay lookup. Omitted fields stay unchanged; null clears nullable fields. For a dietary change, first save the staff-reported evidence with record_party_detail and supply its ID as evidence_detail_id. A saved note alone does not update dietary requirements.",
            arguments=UpdateGuestArguments,
            result=Guest,
            required_permissions=(guests.READ_PERMISSION, guests.WRITE_PERMISSION),
            handler=update_guest,
        ),
        Tool(
            name="search_guests",
            description="Find guests by name, party or booking in this hotel. Use their party ID to record a note.",
            arguments=SearchGuestsRequestPayload,
            result=Page[Guest],
            required_permissions=(guests.READ_PERMISSION,),
            handler=search_guests,
        ),
        Tool(
            name="record_party_detail",
            description="Save a staff-reported note about a party. Guest references are identified automatically. Clear matches are retained even when other references are ambiguous; failed classification leaves the list empty. This records evidence and leaves guest facts unchanged.",
            arguments=CreatePartyDetailRequestPayload,
            result=PartyDetail,
            required_permissions=(guests.READ_PERMISSION, guests.WRITE_PERMISSION),
            handler=record_party_detail,
        ),
    )
