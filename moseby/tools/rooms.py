import asyncio

from sqlalchemy import Engine

from moseby.contracts.common import Page
from moseby.contracts.rooms import Room, SearchRoomsRequestPayload
from moseby.db.pagination import InvalidCursor
from moseby.runtime.models.common import ErrorDetails
from moseby.services import rooms

from .definitions import Tool, ToolContext
from .execution import ToolErrorCode, ToolFailure


def create_tools(engine: Engine) -> tuple[Tool, ...]:
    """Bind room tools to the application's database engine."""

    async def search_rooms(
        context: ToolContext, arguments: SearchRoomsRequestPayload
    ) -> Page[Room]:
        """Use trusted hotel scope and keep database work off the async event loop."""
        try:
            return await asyncio.to_thread(
                rooms.search,
                engine,
                arguments,
                hotel_id=context.domain_context.hotel_id,
                permissions=context.domain_context.permissions,
            )
        except InvalidCursor as error:
            raise ToolFailure(
                ErrorDetails(
                    code=ToolErrorCode.INVALID_ARGUMENTS,
                    message="Use the next cursor from the same room search, or omit the cursor to start again.",
                    details={"field": "cursor"},
                )
            ) from error

    return (
        Tool(
            name="search_rooms",
            description="Find rooms by dates, tier, beds and price within the staff member's hotel.",
            arguments=SearchRoomsRequestPayload,
            result=Page[Room],
            required_permissions=(rooms.READ_PERMISSION,),
            handler=search_rooms,
        ),
    )
