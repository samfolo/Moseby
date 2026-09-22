"""Help guests choose activities, reserve places and manage their itinerary."""

import asyncio

from sqlalchemy import Engine

from moseby.contracts.activities import Activity, SearchActivitiesRequestPayload
from moseby.contracts.activity_reservations import (
    ActivityReservation,
    ActivityReservations,
    CancelActivityReservationRequestPayload,
    ReserveActivityRequestPayload,
    SearchActivityReservationsRequestPayload,
)
from moseby.contracts.common import Page
from moseby.identifiers import ActivityReservationId
from moseby.runtime.tool_writes import claimed_write
from moseby.services import activities, activity_reservations

from .definitions import Tool, ToolContext
from .errors import report_errors


class CancelActivityReservationArguments(CancelActivityReservationRequestPayload):
    reservation_id: ActivityReservationId


def create_tools(engine: Engine) -> tuple[Tool, ...]:
    async def search_activities(
        context: ToolContext, arguments: SearchActivitiesRequestPayload
    ) -> Page[Activity]:
        with report_errors():
            return await asyncio.to_thread(
                activities.search,
                engine,
                arguments,
                permissions=context.domain_context.permissions,
            )

    async def search_activity_reservations(
        context: ToolContext, arguments: SearchActivityReservationsRequestPayload
    ) -> Page[ActivityReservation]:
        with report_errors():
            return await asyncio.to_thread(
                activity_reservations.search,
                engine,
                arguments,
                hotel_id=context.domain_context.hotel_id,
                permissions=context.domain_context.permissions,
            )

    async def reserve_activity_places(
        context: ToolContext, arguments: ReserveActivityRequestPayload
    ) -> ActivityReservations:
        def write():
            with claimed_write(
                engine, context, permissions=(activity_reservations.WRITE_PERMISSION,)
            ) as (connection, now):
                return activity_reservations.reserve(
                    connection,
                    arguments,
                    context=context.domain_context,
                    request_id=context.request_id,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    async def cancel_activity_reservation(
        context: ToolContext, arguments: CancelActivityReservationArguments
    ) -> ActivityReservation:
        def write():
            with claimed_write(
                engine, context, permissions=(activity_reservations.WRITE_PERMISSION,)
            ) as (connection, now):
                return activity_reservations.cancel(
                    connection,
                    arguments.reservation_id,
                    CancelActivityReservationRequestPayload(
                        **arguments.model_dump(exclude={"reservation_id"})
                    ),
                    context=context.domain_context,
                    request_id=context.request_id,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    return (
        Tool(
            name="search_activities",
            description="Browse scheduled activities by time, type and free places. Use this when a guest wants suggestions. Date filters match overlapping events; check that the whole event fits the guest's requested window before offering it. Results include price, age and group-size limits.",
            arguments=SearchActivitiesRequestPayload,
            result=Page[Activity],
            required_permissions=(activities.READ_PERMISSION,),
            handler=search_activities,
        ),
        Tool(
            name="search_activity_reservations",
            description="Read a guest's or party's itinerary, including reservation IDs and revisions for cancellation. By default includes effective reservations; supply a date range for the relevant day or stay.",
            arguments=SearchActivityReservationsRequestPayload,
            result=Page[ActivityReservation],
            required_permissions=(activity_reservations.READ_PERMISSION,),
            handler=search_activity_reservations,
        ),
        Tool(
            name="reserve_activity_places",
            description="Reserve one place for each selected guest in an existing activity, all together or none. For a group, send all guest IDs in one call so the activity booking-size rule is checked against the whole group. Use IDs returned by guest and activity searches. The staff member must choose or authorize the activity and its displayed price. Check the itinerary for clashes and discuss them; overlaps are allowed when intended.",
            arguments=ReserveActivityRequestPayload,
            result=ActivityReservations,
            required_permissions=(activity_reservations.WRITE_PERMISSION,),
            handler=reserve_activity_places,
        ),
        Tool(
            name="cancel_activity_reservation",
            description="Cancel one guest's activity reservation with a reason. Use the reservation ID and revision returned by itinerary lookup. Other guests' reservations remain unchanged.",
            arguments=CancelActivityReservationArguments,
            result=ActivityReservation,
            required_permissions=(activity_reservations.WRITE_PERMISSION,),
            handler=cancel_activity_reservation,
        ),
    )
