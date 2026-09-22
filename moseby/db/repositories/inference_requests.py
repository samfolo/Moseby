"""Keep each inference attempt and the exact conversation records it used."""

from collections.abc import Sequence

from sqlalchemy import Connection, insert, null, select, update

from moseby.common.types import JsonObject
from moseby.identifiers import InferenceRequestId, RunId, StaffMemberId, ThreadRecordId
from moseby.runtime.enums import InferenceStatus
from moseby.runtime.models.common import ErrorDetails

from ..errors import WriteConflict
from ..models.inference_requests import InferenceRequestRow, NewInferenceRequest
from ..tables import inference_request_records, inference_requests
from . import runs, thread_records
from ._thread_queries import owned_thread_ids
from ._writes import require_found, require_write_transaction


def find_by_id(
    connection: Connection,
    id: InferenceRequestId,
    *,
    creator_staff_member_id: StaffMemberId,
) -> InferenceRequestRow | None:
    """Read a conversation's inference attempt only for its thread creator."""
    row = (
        connection.execute(
            select(inference_requests).where(
                inference_requests.c.id == id,
                inference_requests.c.thread_id.in_(
                    owned_thread_ids(creator_staff_member_id)
                ),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    values = dict(row)
    for name in ("request", "response", "error"):
        values[name] = values.pop(f"{name}_json")
    return InferenceRequestRow.model_validate(values)


def prepare(
    connection: Connection,
    values: NewInferenceRequest,
    record_ids: Sequence[ThreadRecordId],
    *,
    creator_staff_member_id: StaffMemberId,
    now: int,
) -> InferenceRequestRow:
    """Save a request snapshot and its ordered input links before dispatch."""
    require_write_transaction(connection)
    run = runs.require_running(
        connection, values.run_id, creator_staff_member_id=creator_staff_member_id
    )
    if run.thread_id != values.thread_id or len(set(record_ids)) != len(record_ids):
        raise WriteConflict(
            "The input must contain unique records from this run's thread"
        )
    with connection.begin_nested():
        connection.execute(
            insert(inference_requests).values(
                **values.model_dump(exclude={"request"}),
                request_json=values.request,
                format_version=1,
                status=InferenceStatus.PREPARED,
                created_at=now,
                updated_at=now,
            )
        )
        previous_sequence = 0
        for position, record_id in enumerate(record_ids, 1):
            record = require_found(
                thread_records.find_by_id(
                    connection,
                    record_id,
                    creator_staff_member_id=creator_staff_member_id,
                )
            )
            if (
                record.thread_id != values.thread_id
                or record.sequence <= previous_sequence
            ):
                raise WriteConflict("Inference input must follow thread history order")
            previous_sequence = record.sequence
            connection.execute(
                insert(inference_request_records).values(
                    inference_request_id=values.id,
                    record_id=record_id,
                    thread_id=values.thread_id,
                    sequence=position,
                )
            )
        return require_found(
            find_by_id(
                connection, values.id, creator_staff_member_id=creator_staff_member_id
            )
        )


def start(
    connection: Connection,
    id: InferenceRequestId,
    *,
    creator_staff_member_id: StaffMemberId,
    now: int,
) -> None:
    """Mark dispatch once, freezing the request's selected input records."""
    require_write_transaction(connection)
    saved = require_found(
        find_by_id(connection, id, creator_staff_member_id=creator_staff_member_id)
    )
    runs.require_running(
        connection, saved.run_id, creator_staff_member_id=creator_staff_member_id
    )
    if saved.status != InferenceStatus.PREPARED or now < saved.created_at:
        raise WriteConflict(
            "The request is already dispatched or the clock moved backwards"
        )
    connection.execute(
        update(inference_requests)
        .where(inference_requests.c.id == id)
        .values(
            status=InferenceStatus.IN_FLIGHT,
            started_at=now,
            updated_at=now,
        )
    )


def finish(
    connection: Connection,
    id: InferenceRequestId,
    *,
    creator_staff_member_id: StaffMemberId,
    now: int,
    response: JsonObject | None = None,
    error: ErrorDetails | None = None,
) -> None:
    """Keep the complete response or a safe failure after an in-flight attempt."""
    require_write_transaction(connection)
    if (response is None) == (error is None):
        raise ValueError("Supply exactly one response or error")
    saved = require_found(
        find_by_id(connection, id, creator_staff_member_id=creator_staff_member_id)
    )
    if saved.status != InferenceStatus.IN_FLIGHT or now < saved.started_at:
        raise WriteConflict("Only an in-flight request can receive an outcome")
    connection.execute(
        update(inference_requests)
        .where(inference_requests.c.id == id)
        .values(
            status=InferenceStatus.SUCCEEDED
            if response is not None
            else InferenceStatus.FAILED,
            response_json=response if response is not None else null(),
            error_json=error.model_dump(mode="json") if error is not None else null(),
            updated_at=now,
            finished_at=now,
        )
    )


def token_usage(
    connection: Connection, run_id: RunId, *, creator_staff_member_id: StaffMemberId
) -> int | None:
    """Total reported tokens for this run; any unreported attempt makes usage unknown."""
    responses = connection.scalars(
        select(inference_requests.c.response_json).where(
            inference_requests.c.run_id == run_id,
            inference_requests.c.thread_id.in_(
                owned_thread_ids(creator_staff_member_id)
            ),
        )
    )
    total = 0
    for response in responses:
        used = response.get("total_tokens") if isinstance(response, dict) else None
        if type(used) is not int or used < 0:
            return None
        total += used
    return total
