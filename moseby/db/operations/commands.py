"""Save a synchronous command, its effects and its response in one transaction."""

from collections.abc import Callable

from sqlalchemy import Connection

from moseby.runtime.models.common import JsonObject

from ..errors import WriteConflict
from ..models.request_deduplication import RequestKey
from ..repositories import request_deduplication
from ..repositories._writes import require_write_transaction


def execute(
    connection: Connection,
    key: RequestKey,
    request: JsonObject,
    action: Callable[[], JsonObject],
    *,
    now: int,
) -> JsonObject:
    """Replay a saved response, or run the action once with a rollback boundary.

    Include resource IDs and hotel scope in request. The service checks current
    permissions before calling this, even for a replay. Actions perform local writes.
    """
    require_write_transaction(connection)
    with connection.begin_nested():
        accepted = request_deduplication.accept(connection, key, request, now=now)
        if accepted.request.response is not None:
            return accepted.request.response
        if not accepted.created:
            raise WriteConflict(
                "This command was accepted without a completed response"
            )
        response = action()
        request_deduplication.save_response(connection, key, response, now=now)
        return response
