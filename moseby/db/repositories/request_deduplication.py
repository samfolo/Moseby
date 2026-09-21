"""Accept commands once and retain their input and response for replay."""

from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from moseby.identifiers import StaffMemberId
from moseby.runtime.models.common import JsonObject

from ..errors import IdempotencyConflict, RepositoryInvariantError, WriteConflict
from ..models.request_deduplication import (
    RequestAcceptance,
    RequestDeduplicationRow,
    RequestKey,
)
from ..tables import request_deduplication
from ._writes import encode_canonical_json, require_write_transaction

# Reads


def find_by_operation_and_request_id(
    connection: Connection,
    operation: str,
    request_id: str,
    *,
    actor_staff_member_id: StaffMemberId,
) -> RequestDeduplicationRow | None:
    """Return the accepted request and any saved response for this exact command key.

    None means no command was accepted under that key. A row with response=None
    was accepted but has no saved response. Services compare the request input
    and check current resource access before replaying a response.
    """
    row = (
        connection.execute(
            select(
                request_deduplication.c.actor_staff_member_id,
                request_deduplication.c.operation,
                request_deduplication.c.request_id,
                request_deduplication.c.created_at,
                request_deduplication.c.updated_at,
                request_deduplication.c.request_json.label("request"),
                request_deduplication.c.response_json.label("response"),
            ).where(
                request_deduplication.c.actor_staff_member_id == actor_staff_member_id,
                request_deduplication.c.operation == operation,
                request_deduplication.c.request_id == request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    return (
        RequestDeduplicationRow.model_validate(dict(row)) if row is not None else None
    )


# Writes


def accept(
    connection: Connection,
    key: RequestKey,
    request: JsonObject,
    *,
    now: int,
) -> RequestAcceptance:
    """Save this command once, or return the matching command already accepted.

    Reusing its key with different input raises IdempotencyConflict. Save any
    resulting job and tasks on this same transaction before committing it.
    """
    require_write_transaction(connection)
    encoded = encode_canonical_json(request)
    values = key.model_dump()
    # The full command key lets one caller create the entry; retries reuse it.
    inserted = connection.execute(
        sqlite_insert(request_deduplication)
        .values(**values, created_at=now, updated_at=now, request_json=request)
        .on_conflict_do_nothing(index_elements=list(values))
        .returning(request_deduplication.c.request_id)
    ).scalar_one_or_none()
    # Both paths read the accepted input before deciding whether this is a replay.
    saved = find_by_operation_and_request_id(
        connection,
        key.operation,
        key.request_id,
        actor_staff_member_id=key.actor_staff_member_id,
    )
    if saved is None:
        raise RepositoryInvariantError("The accepted command could not be read back")
    if encode_canonical_json(saved.request) != encoded:
        raise IdempotencyConflict(
            "This request key has already been used with different input"
        )
    return RequestAcceptance(created=inserted is not None, request=saved)


def save_response(
    connection: Connection,
    key: RequestKey,
    response: JsonObject,
    *,
    now: int,
) -> RequestDeduplicationRow:
    """Save the accepted command's response once; repeating that response is harmless.

    A different saved response raises IdempotencyConflict. An unknown command
    or a timestamp before its last change raises WriteConflict.
    """
    require_write_transaction(connection)
    encoded = encode_canonical_json(response)
    saved = find_by_operation_and_request_id(
        connection,
        key.operation,
        key.request_id,
        actor_staff_member_id=key.actor_staff_member_id,
    )
    if saved is None:
        raise WriteConflict("Accept the command before saving its response")
    if saved.response is not None:
        if encode_canonical_json(saved.response) != encoded:
            raise IdempotencyConflict("This command already has a different response")
        return saved
    changed = connection.execute(
        update(request_deduplication)
        .where(
            *(
                request_deduplication.c[name] == value
                for name, value in key.model_dump().items()
            ),
            request_deduplication.c.response_json.is_(None),
            request_deduplication.c.updated_at <= now,
        )
        .values(response_json=response, updated_at=now)
    ).rowcount
    if changed != 1:
        raise WriteConflict("The command cannot accept a response at this time")
    return saved.model_copy(update={"response": response, "updated_at": now})
