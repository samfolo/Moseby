"""Concierge actions for reading and changing a complete stay."""

import asyncio

from sqlalchemy import Engine

from moseby.contracts.stays import (
    AmendStayRequestPayload,
    CancelStayRequestPayload,
    CompleteStayRequestPayload,
    CreateStayRequestPayload,
    GetStayRequestPayload,
    Stay,
)
from moseby.identifiers import BookingId
from moseby.runtime.tool_writes import claimed_write
from moseby.services import stays

from .definitions import Tool, ToolContext
from .errors import report_errors


class AmendStayArguments(AmendStayRequestPayload):
    """Tool input includes the booking ID that HTTP carries in the URL."""

    booking_id: BookingId


class CancelStayArguments(CancelStayRequestPayload):
    booking_id: BookingId


class CompleteStayArguments(CompleteStayRequestPayload):
    booking_id: BookingId


def create_tools(engine: Engine) -> tuple[Tool, ...]:
    async def get_stay(context: ToolContext, arguments: GetStayRequestPayload) -> Stay:
        with report_errors():
            return await asyncio.to_thread(
                stays.get, engine, arguments, context=context.domain_context
            )

    async def create_stay(
        context: ToolContext, arguments: CreateStayRequestPayload
    ) -> Stay:
        def write():
            with claimed_write(
                engine, context, permissions=stays.CREATE_PERMISSIONS
            ) as (connection, now):
                return stays.create(
                    connection,
                    arguments,
                    context=context.domain_context,
                    request_id=context.request_id,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    async def amend_stay(context: ToolContext, arguments: AmendStayArguments) -> Stay:
        def write():
            with claimed_write(
                engine, context, permissions=stays.WRITE_PERMISSIONS
            ) as (connection, now):
                return stays.amend(
                    connection,
                    arguments.booking_id,
                    AmendStayRequestPayload(
                        **arguments.model_dump(exclude={"booking_id"})
                    ),
                    context=context.domain_context,
                    request_id=context.request_id,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    async def cancel_stay(context: ToolContext, arguments: CancelStayArguments) -> Stay:
        def write():
            with claimed_write(
                engine, context, permissions=stays.WRITE_PERMISSIONS
            ) as (connection, now):
                return stays.cancel(
                    connection,
                    arguments.booking_id,
                    CancelStayRequestPayload(
                        **arguments.model_dump(exclude={"booking_id"})
                    ),
                    context=context.domain_context,
                    request_id=context.request_id,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    async def complete_stay(
        context: ToolContext, arguments: CompleteStayArguments
    ) -> Stay:
        def write():
            with claimed_write(
                engine, context, permissions=stays.WRITE_PERMISSIONS
            ) as (connection, now):
                return stays.complete(
                    connection,
                    arguments.booking_id,
                    CompleteStayRequestPayload(
                        **arguments.model_dump(exclude={"booking_id"})
                    ),
                    context=context.domain_context,
                    request_id=context.request_id,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    return (
        Tool(
            name="get_stay",
            description="Read a stay's booking, party, guests and room allocations by booking ID or guest ID. Returns current revisions and agreed nightly prices for changes.",
            arguments=GetStayRequestPayload,
            result=Stay,
            required_permissions=stays.READ_PERMISSIONS,
            handler=get_stay,
        ),
        Tool(
            name="create_stay",
            description="Confirm a booking with a new party, guests and rooms in one operation. Collect each guest's name and age and the exact stay dates. Copy quoted_price from room search and obtain authorization for that rate. This demo records the agreed price but takes no payment; never claim a charge or receipt.",
            arguments=CreateStayRequestPayload,
            result=Stay,
            required_permissions=stays.CREATE_PERMISSIONS,
            handler=create_stay,
        ),
        Tool(
            name="amend_stay",
            description="Change the dates of one room allocation or move it to another room. Read the stay first and use its allocation ID and revision. For the same room copy its agreed nightly_price into quoted_price; for a different room copy the price from room search. Get authorization for changed dates and rates. Failure preserves the original allocation.",
            arguments=AmendStayArguments,
            result=Stay,
            required_permissions=stays.WRITE_PERMISSIONS,
            handler=amend_stay,
        ),
        Tool(
            name="cancel_stay",
            description="Permanently cancel a booking with its current booking revision and a reason. This releases its room and activity places and disables key access. Use only when the staff member asks to cancel the entire stay.",
            arguments=CancelStayArguments,
            result=Stay,
            required_permissions=stays.WRITE_PERMISSIONS,
            handler=cancel_stay,
        ),
        Tool(
            name="complete_stay",
            description="Mark a stay completed after its reserved checkout time. Read the stay first and use the booking revision. Disables room access; does not take payment or settle a bill.",
            arguments=CompleteStayArguments,
            result=Stay,
            required_permissions=stays.WRITE_PERMISSIONS,
            handler=complete_stay,
        ),
    )
