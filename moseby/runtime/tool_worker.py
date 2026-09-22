"""Execute one queued tool and deliver its durable result to the conversation."""

import asyncio
from collections.abc import Sequence

from moseby.db.errors import ClaimLost, WriteConflict
from moseby.db.models.request_deduplication import RequestKey
from moseby.db.models.threads import ProjectionUpdate
from moseby.db.operations import job_completions
from moseby.db.operations.conversations import AcceptedTool
from moseby.db.repositories import (
    jobs,
    request_deduplication,
    task_claims,
    tasks,
    thread_records,
    threads,
)
from moseby.db.repositories._writes import require_found
from moseby.db.transaction import transaction
from moseby.identifiers import RunId, ThreadId, new_id
from moseby.runtime.models.common import ErrorDetails
from moseby.runtime.models.job_outcomes import JobOutcome
from moseby.runtime.models.messages import ToolCall, ToolResultStatus
from moseby.runtime.models.thread_records import ThreadRecordKind
from moseby.tools.definitions import ToolContext
from moseby.tools.execution import ToolErrorCode, execute_tool

from .enums import JobStatus
from .storage import ConversationStore, now_microseconds

TOOL_TIMEOUT_SECONDS = 45
CLAIM_LIFETIME_MICROSECONDS = 90_000_000


async def execute_tool_batch(
    store: ConversationStore,
    thread_id: ThreadId,
    run_id: RunId,
    work: Sequence[AcceptedTool],
) -> None:
    """Run calls in order and record unstarted calls when the batch is cancelled."""
    for index, item in enumerate(work):
        try:
            await execute_queued_tool(store, thread_id, run_id, item)
        except asyncio.CancelledError:
            # Save results for unstarted calls so the next turn has a complete exchange.
            skipped = ErrorDetails(
                code=ToolErrorCode.INTERRUPTED,
                message="This call was cancelled before execution.",
            )
            for remaining in work[index + 1 :]:
                await execute_queued_tool(
                    store, thread_id, run_id, remaining, skip_error=skipped
                )
            raise


async def execute_queued_tool(
    store: ConversationStore,
    thread_id: str,
    run_id: str,
    work: AcceptedTool,
    *,
    skip_error: ErrorDetails | None = None,
) -> None:
    """Claim one task, run its handler outside SQL, then commit its outcome and delivery."""
    actor = store.staff_member_id
    with transaction(store.engine, write=True) as connection:
        now = now_microseconds()
        claim = task_claims.claim(
            connection,
            work.task_id,
            actor_staff_member_id=actor,
            worker_id=f"local:{run_id}",
            now=now,
            expires_at=now + CLAIM_LIFETIME_MICROSECONDS,
        )
        if claim is None:
            raise ClaimLost("The tool task is unavailable or already owned")
        task = require_found(
            tasks.find_by_id(connection, work.task_id, actor_staff_member_id=actor)
        )
        job = require_found(
            jobs.find_by_id(connection, work.job_id, actor_staff_member_id=actor)
        )
        if (
            task.job_id != job.id
            or job.thread_id != thread_id
            or job.run_id != run_id
            or task.handler != "tool"
            or job.handler != "tool"
            or task.input != job.input
        ):
            raise WriteConflict("The claimed task does not match this run's tool job")
        call = ToolCall.model_validate(task.input)

    # A timeout ends this local attempt before its claim expires.
    interrupted = False
    try:
        if skip_error is not None:
            outcome = JobOutcome(status=JobStatus.FAILED, error=skip_error)
        else:
            agent = store.load_agent(thread_id)
            context = ToolContext(
                domain_context=agent.domain_context,
                thread_context=agent.thread_context,
                run_id=run_id,
                source_record_id=job.source_record_id,
                tool_call_id=call.id,
                request_id=job.request_id,
            )
            async with asyncio.timeout(TOOL_TIMEOUT_SECONDS):
                result = await execute_tool(
                    agent, call, context=context, tools=store.tools
                )
            if result.status == ToolResultStatus.SUCCEEDED:
                outcome = JobOutcome(status=JobStatus.SUCCEEDED, result=result.result)
            else:
                outcome = JobOutcome(status=JobStatus.FAILED, error=result.error)
    except asyncio.CancelledError:
        interrupted = True
        outcome = JobOutcome(
            status=JobStatus.FAILED,
            error=ErrorDetails(
                code=ToolErrorCode.INTERRUPTED,
                message="Tool execution was interrupted; verify its outcome before repeating it.",
            ),
        )
    except Exception:
        outcome = JobOutcome(
            status=JobStatus.FAILED,
            error=ErrorDetails(
                code=ToolErrorCode.EXECUTION_FAILED,
                message="The tool could not finish; its outcome must be checked before retrying.",
            ),
        )

    # An obsolete worker cannot save a task outcome or deliver it to history.
    with transaction(store.engine, write=True) as connection:
        now = now_microseconds()
        with task_claims.guard(
            connection, work.task_id, claim.token, actor_staff_member_id=actor, now=now
        ):
            if outcome.status == JobStatus.SUCCEEDED:
                tasks.succeed(
                    connection,
                    work.task_id,
                    claim.token,
                    outcome.result,
                    actor_staff_member_id=actor,
                    now=now,
                )
            else:
                tasks.fail(
                    connection,
                    work.task_id,
                    claim.token,
                    outcome.error.model_dump(mode="json"),
                    actor_staff_member_id=actor,
                    now=now,
                )
            completed = job_completions.finish(
                connection,
                work.job_id,
                outcome,
                expected_phase="execute",
                completion_id=new_id("completion"),
                actor_staff_member_id=actor,
                now=now,
            )
            thread = threads.find_by_id(
                connection, thread_id, creator_staff_member_id=actor
            )
            last = thread_records.find_last_by_thread_id(
                connection, thread_id, creator_staff_member_id=actor
            )
            job_completions.deliver(
                connection,
                completed.completion.id,
                record_id=new_id("thread_record"),
                projection=ProjectionUpdate(
                    expected_sequence=thread.projection_sequence,
                    expected_history_sequence=last.sequence,
                    value={"last_record_kind": ThreadRecordKind.TOOL_RESULT.value},
                ),
                actor_staff_member_id=actor,
                now=now,
            )
            request_deduplication.save_response(
                connection,
                RequestKey(
                    actor_staff_member_id=actor,
                    operation="tools.execute",
                    request_id=job.request_id,
                ),
                outcome.model_dump(mode="json"),
                now=now,
            )
    if interrupted:
        raise asyncio.CancelledError
