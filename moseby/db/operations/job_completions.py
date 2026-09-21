"""Keep each job outcome and its delivery receipts together across retries."""

from sqlalchemy import Connection

from moseby.identifiers import CompletionId, JobId, StaffMemberId, ThreadRecordId
from moseby.runtime.models.job_outcomes import JobOutcome, completion_payload
from moseby.runtime.models.thread_records import ThreadRecordKind, thread_record_adapter

from ..errors import RepositoryInvariantError, WriteConflict
from ..models.completion_outbox import CompletedJob
from ..models.thread_records import ThreadRecordRow
from ..models.threads import ProjectionUpdate
from ..repositories import completion_outbox, jobs, thread_records, threads
from ..repositories._writes import require_write_transaction
from ..timestamps import to_datetime


def finish(
    connection: Connection,
    job_id: JobId,
    outcome: JobOutcome,
    *,
    expected_phase: str,
    completion_id: CompletionId | None = None,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> CompletedJob:
    """Finish a settled job and save its delivery together, including on retries.

    A thread-linked job requires a completion ID; a standalone job keeps its
    outcome on the job itself. The caller commits after this operation succeeds.
    """
    require_write_transaction(connection)
    with connection.begin_nested():
        job = jobs.finish(
            connection,
            job_id,
            outcome,
            expected_phase=expected_phase,
            actor_staff_member_id=actor_staff_member_id,
            now=now,
        )
        completion = None
        if job.thread_id is not None:
            if completion_id is None:
                raise ValueError("A thread-linked job requires a completion ID")
            completion = completion_outbox.create(
                connection,
                completion_id,
                job.id,
                actor_staff_member_id=actor_staff_member_id,
                now=now,
            )
        elif completion_id is not None:
            raise ValueError("A standalone job has no thread delivery")
        return CompletedJob(job=job, completion=completion)


def deliver(
    connection: Connection,
    completion_id: CompletionId,
    *,
    record_id: ThreadRecordId,
    projection: ProjectionUpdate,
    actor_staff_member_id: StaffMemberId,
    now: int,
) -> ThreadRecordRow:
    """Append one result, advance its summary and save the receipt in a single group.

    A retry returns the original record without applying another summary. The
    runtime supplies a summary based on the expected history and this result.
    Delivery records evidence without resuming or changing a run.
    """
    require_write_transaction(connection)
    with connection.begin_nested():
        completion = completion_outbox.find_by_id(
            connection, completion_id, actor_staff_member_id=actor_staff_member_id
        )
        if completion is None:
            raise WriteConflict("The completion is missing or inaccessible")
        if completion.record_id is not None:
            # This delivery already succeeded; return its record without appending again.
            saved = thread_records.find_by_id(
                connection,
                completion.record_id,
                creator_staff_member_id=actor_staff_member_id,
            )
            if saved is None:
                raise RepositoryInvariantError(
                    "The delivered completion's record is missing"
                )
            return saved

        # Use the saved destination and outcome, including for a stopped run.
        job = jobs.find_by_id(
            connection, completion.job_id, actor_staff_member_id=actor_staff_member_id
        )
        if job is None:
            raise WriteConflict("The completion's job is missing or inaccessible")
        last = thread_records.find_last_by_thread_id(
            connection,
            completion.thread_id,
            creator_staff_member_id=actor_staff_member_id,
        )
        # A new message can make the prepared summary stale. Rebuild it before retrying.
        if last is None or last.sequence != projection.expected_history_sequence:
            raise WriteConflict("The thread history changed before delivery")
        if now < completion.created_at:
            raise WriteConflict("Delivery cannot precede its completion entry")
        payload = completion_payload(
            job.id,
            JobOutcome.model_validate(completion.payload),
            tool_result=job.tool_call_id is not None,
        )
        record = thread_record_adapter.validate_python(
            dict(
                id=record_id,
                thread_id=completion.thread_id,
                sequence=last.sequence + 1,
                kind=ThreadRecordKind.TOOL_RESULT
                if job.tool_call_id
                else ThreadRecordKind.CONTROL_EVENT,
                format_version=1,
                created_at=to_datetime(now),
                run_id=job.run_id,
                actor_staff_member_id=actor_staff_member_id,
                source_record_id=job.source_record_id,
                tool_call_id=job.tool_call_id,
                payload=payload,
            )
        )

        # Any failed summary or receipt update rolls back the new record as well.
        saved = thread_records.append(
            connection, record, creator_staff_member_id=actor_staff_member_id
        )
        threads.save_projection(
            connection,
            completion.thread_id,
            projection,
            creator_staff_member_id=actor_staff_member_id,
            now=now,
        )
        completion_outbox.mark_delivered(
            connection,
            completion.id,
            saved.id,
            actor_staff_member_id=actor_staff_member_id,
            now=now,
        )
        return saved
