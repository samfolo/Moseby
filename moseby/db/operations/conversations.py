"""Atomic changes to a conversation, its run and the work accepted from a reply."""

from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import Connection

from moseby.identifiers import (
    JobId,
    RunId,
    StaffMemberId,
    TaskId,
    ThreadId,
    ThreadRecordId,
    new_id,
)
from moseby.inference.models.generation import AssistantMessage
from moseby.runtime.enums import RunStatus
from moseby.runtime.models.messages import AssistantMessagePayload, UserMessagePayload
from moseby.runtime.models.thread_records import (
    ControlEventPayload,
    ThreadCreatedPayload,
    ThreadRecordKind,
    thread_record_adapter,
)

from ..errors import WriteConflict
from ..models.jobs import NewJob
from ..models.request_deduplication import RequestKey
from ..models.tasks import NewTask
from ..models.thread_records import ThreadRecordRow
from ..models.threads import NewThread, ProjectionUpdate
from ..repositories import (
    incoming_thread_records,
    jobs,
    request_deduplication,
    runs,
    tasks,
    thread_records,
    threads,
)
from ..repositories._writes import require_found, require_write_transaction
from ..timestamps import to_datetime


@dataclass(frozen=True)
class AcceptedTurn:
    run_id: RunId
    created: bool


@dataclass(frozen=True)
class AcceptedTool:
    job_id: JobId
    task_id: TaskId


def append(
    connection: Connection,
    thread_id: ThreadId,
    kind: ThreadRecordKind,
    payload: BaseModel,
    *,
    actor: StaffMemberId,
    now: int,
    run_id: RunId | None = None,
    source_record_id: ThreadRecordId | None = None,
) -> ThreadRecordRow:
    """Append the next record and advance its projection together."""
    require_write_transaction(connection)
    thread = require_found(
        threads.find_by_id(connection, thread_id, creator_staff_member_id=actor)
    )
    last = thread_records.find_last_by_thread_id(
        connection, thread_id, creator_staff_member_id=actor
    )
    sequence = last.sequence if last else 0
    if thread.projection_sequence != sequence:
        raise WriteConflict("The thread projection must be caught up before appending")
    record = thread_record_adapter.validate_python(
        dict(
            id=new_id("thread_record"),
            thread_id=thread_id,
            sequence=sequence + 1,
            kind=kind,
            format_version=1,
            created_at=to_datetime(now),
            run_id=run_id,
            actor_staff_member_id=actor,
            source_record_id=source_record_id,
            payload=payload.model_dump(mode="json"),
        )
    )
    with connection.begin_nested():
        saved = thread_records.append(connection, record, creator_staff_member_id=actor)
        threads.save_projection(
            connection,
            thread_id,
            ProjectionUpdate(
                expected_sequence=sequence,
                expected_history_sequence=sequence,
                value={"last_record_id": record.id, "last_record_kind": kind.value},
            ),
            creator_staff_member_id=actor,
            now=now,
        )
        return saved


def create_thread(connection: Connection, values: NewThread, *, now: int) -> ThreadId:
    """Save the thread identity and creation record as one unit."""
    require_write_transaction(connection)
    with connection.begin_nested():
        threads.create(connection, values, now=now)
        append(
            connection,
            values.id,
            ThreadRecordKind.THREAD_CREATED,
            ThreadCreatedPayload(
                agent=values.agent,
                creator_staff_member_id=values.creator_staff_member_id,
                permissions=values.permissions,
                title=values.title,
            ),
            actor=values.creator_staff_member_id,
            now=now,
        )
    return values.id


def begin_turn(
    connection: Connection,
    thread_id: ThreadId,
    text: str,
    *,
    request_id: str,
    actor: StaffMemberId,
    now: int,
) -> AcceptedTurn:
    """Accept input, start a run and append its user message in one transaction.

    The same request returns the original run. Another request while that run
    is active is rejected before any new input is saved.
    """
    require_write_transaction(connection)
    payload = UserMessagePayload(text=text)
    key = RequestKey(
        actor_staff_member_id=actor, operation="threads.submit", request_id=request_id
    )
    with connection.begin_nested():
        accepted = request_deduplication.accept(
            connection, key, {"thread_id": thread_id, "text": text}, now=now
        )
        if not accepted.created:
            if accepted.request.response is None:
                raise WriteConflict("The accepted input has no saved run receipt")
            return AcceptedTurn(accepted.request.response["run_id"], False)
        run = runs.create(
            connection, new_id("run"), thread_id, creator_staff_member_id=actor, now=now
        )
        incoming = incoming_thread_records.create(
            connection,
            new_id("incoming_thread_record"),
            thread_id,
            payload,
            request_id=request_id,
            creator_staff_member_id=actor,
            now=now,
        )
        record = append(
            connection,
            thread_id,
            ThreadRecordKind.USER_MESSAGE,
            payload,
            actor=actor,
            now=now,
            run_id=run.id,
        )
        incoming_thread_records.mark_appended(
            connection, incoming.id, record.id, creator_staff_member_id=actor, now=now
        )
        request_deduplication.save_response(
            connection, key, {"run_id": run.id}, now=now
        )
        return AcceptedTurn(run.id, True)


def accept_reply(
    connection: Connection,
    thread_id: ThreadId,
    run_id: RunId,
    reply: AssistantMessage,
    *,
    source_record_id: ThreadRecordId,
    actor: StaffMemberId,
    now: int,
) -> tuple[ThreadRecordRow, list[AcceptedTool]]:
    """Save the complete assistant reply and every requested tool's job together."""
    require_write_transaction(connection)
    run = runs.require_running(connection, run_id, creator_staff_member_id=actor)
    if run.thread_id != thread_id:
        raise WriteConflict("The run belongs to another thread")
    with connection.begin_nested():
        # The inference-only role field does not belong in the stored message payload.
        message = AssistantMessagePayload.model_validate(
            reply.model_dump(exclude={"role"})
        )
        record = append(
            connection,
            thread_id,
            ThreadRecordKind.ASSISTANT_MESSAGE,
            message,
            actor=actor,
            now=now,
            run_id=run_id,
            source_record_id=source_record_id,
        )
        work = []
        for call in reply.tool_calls:
            request_id = f"{record.id}:{call.id}"
            key = RequestKey(
                actor_staff_member_id=actor,
                operation="tools.execute",
                request_id=request_id,
            )
            request_deduplication.accept(
                connection, key, call.model_dump(mode="json"), now=now
            )
            job = jobs.create(
                connection,
                NewJob(
                    id=new_id("job"),
                    request_key=key,
                    handler="tool",
                    phase="execute",
                    input=call.model_dump(mode="json"),
                    thread_id=thread_id,
                    run_id=run_id,
                    source_record_id=record.id,
                    tool_call_id=call.id,
                ),
                now=now,
            )
            task = tasks.create(
                connection,
                NewTask(
                    id=new_id("task"),
                    job_id=job.id,
                    step_key="execute",
                    handler="tool",
                    input=call.model_dump(mode="json"),
                    available_at=now,
                ),
                actor_staff_member_id=actor,
                now=now,
            )
            work.append(AcceptedTool(job.id, task.id))
        return record, work


def finish_run(
    connection: Connection,
    run_id: RunId,
    status: RunStatus,
    *,
    reason: str,
    actor: StaffMemberId,
    now: int,
) -> None:
    """Record why the run stopped alongside its terminal status."""
    require_write_transaction(connection)
    with connection.begin_nested():
        run = require_found(
            runs.find_by_id(connection, run_id, creator_staff_member_id=actor)
        )
        if run.finished_at is not None:
            return
        runs.finish(connection, run_id, status, creator_staff_member_id=actor, now=now)
        append(
            connection,
            run.thread_id,
            ThreadRecordKind.CONTROL_EVENT,
            ControlEventPayload(
                name="run.finished", data={"status": status.value, "reason": reason}
            ),
            actor=actor,
            now=now,
            run_id=run_id,
        )
