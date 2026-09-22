"""Manage individual demo keys for a guest's room reservation."""

import asyncio

from sqlalchemy import Engine

from moseby.contracts.room_keys import (
    DeactivateRoomKeyRequestPayload,
    IssueRoomKeyRequestPayload,
    RoomKey,
)
from moseby.identifiers import RoomKeyId
from moseby.runtime.tool_writes import claimed_write
from moseby.services import room_keys

from .definitions import Tool, ToolContext
from .errors import report_errors


class DeactivateRoomKeyArguments(DeactivateRoomKeyRequestPayload):
    key_id: RoomKeyId


def create_tools(engine: Engine) -> tuple[Tool, ...]:
    async def issue_room_key(
        context: ToolContext, arguments: IssueRoomKeyRequestPayload
    ) -> RoomKey:
        def write():
            with claimed_write(
                engine, context, permissions=(room_keys.WRITE_PERMISSION,)
            ) as (connection, now):
                return room_keys.issue(
                    connection,
                    arguments,
                    context=context.domain_context,
                    request_id=context.request_id,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    async def deactivate_room_key(
        context: ToolContext, arguments: DeactivateRoomKeyArguments
    ) -> RoomKey:
        def write():
            with claimed_write(
                engine, context, permissions=(room_keys.WRITE_PERMISSION,)
            ) as (connection, now):
                return room_keys.deactivate(
                    connection,
                    arguments.key_id,
                    DeactivateRoomKeyRequestPayload(reason=arguments.reason),
                    context=context.domain_context,
                    request_id=context.request_id,
                    now=now,
                )

        with report_errors():
            return await asyncio.to_thread(write)

    return (
        Tool(
            name="issue_room_key",
            description="Issue one demo key for an existing room reservation. Keys belong to the reservation; the system does not track who holds them. Read the stay first and use its allocation ID. A future stay's key becomes effective at arrival. The optional code is a staff label, not a physical door credential; report the recorded key rather than claiming a real lock was programmed.",
            arguments=IssueRoomKeyRequestPayload,
            result=RoomKey,
            required_permissions=(room_keys.WRITE_PERMISSION,),
            handler=issue_room_key,
        ),
        Tool(
            name="deactivate_room_key",
            description="Permanently deactivate one demo key with a reason. Read the stay's room_keys to find its ID; clarify which key if several could match. Other keys remain usable. This records revocation in Moseby, not a command to a physical lock.",
            arguments=DeactivateRoomKeyArguments,
            result=RoomKey,
            required_permissions=(room_keys.WRITE_PERMISSION,),
            handler=deactivate_room_key,
        ),
    )
