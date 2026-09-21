"""Look up accepted commands by their actor, operation and request ID."""

from sqlalchemy import Connection, select

from moseby.identifiers import StaffMemberId

from ..models.request_deduplication import RequestDeduplicationRow
from ..tables import request_deduplication


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
