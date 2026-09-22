"""Drive one user turn through inference, queued tools and a final reply."""

import asyncio
from dataclasses import dataclass
from enum import StrEnum

from moseby.identifiers import RunId, ThreadId
from moseby.inference.errors import InferenceError
from moseby.inference.provider import InferenceProvider
from moseby.runtime.models.common import ErrorDetails
from moseby.runtime.models.thread_records import ThreadRecordKind

from .context import prepare_context
from .enums import RunStatus
from .storage import ConversationStore
from .tool_worker import execute_tool_batch


class RunErrorCode(StrEnum):
    INTERRUPTED = "RUN_ERROR_INTERRUPTED"
    FAILED = "RUN_ERROR_FAILED"


@dataclass(frozen=True)
class TurnResult:
    thread_id: ThreadId
    run_id: RunId
    status: RunStatus
    text: str | None
    reason: str | None = None


async def run_turn(
    store: ConversationStore,
    provider: InferenceProvider,
    *,
    thread_id: ThreadId,
    text: str,
    request_id: str,
    provider_name: str,
    model: str,
) -> TurnResult:
    """Run until the model answers, a limit is reached or execution fails.

    Every awaited operation happens after its preparation transaction commits.
    A repeated request reads its saved outcome and never drives that run again.
    """
    agent = store.load_agent(thread_id)
    # Reject an incomplete previous tool exchange before accepting another user message.
    prepare_context(agent, store.history(thread_id))
    accepted = store.begin(thread_id, text, request_id)
    run_id = accepted.run_id
    if not accepted.created:
        return _saved_result(store, thread_id, run_id)

    turns = 0
    tokens = 0
    usage_known = True
    inference_id = None
    try:
        while turns < agent.definition.max_turns:
            if not usage_known or tokens >= agent.definition.token_budget:
                reason = (
                    "Token usage is unavailable"
                    if not usage_known
                    else "Token budget reached"
                )
                store.finish(run_id, RunStatus.FAILED, reason)
                return TurnResult(thread_id, run_id, RunStatus.FAILED, None, reason)

            # Recheck authority and build context from the accepted history each time.
            agent = store.load_agent(thread_id)
            context = prepare_context(agent, store.history(thread_id))
            # Save the input before awaiting the provider, with the transaction closed.
            inference_id, source_record_id = store.prepare(
                thread_id, run_id, context, provider=provider_name, model=model
            )
            result = await provider.generate(context.request)
            # Access may have changed while we waited for the model.
            store.load_agent(thread_id)
            turns += 1
            usage_known = result.total_tokens is not None
            tokens += result.total_tokens or 0
            # The reply and all of its tool jobs become durable together.
            _, work = store.accept(
                thread_id, run_id, inference_id, source_record_id, result
            )
            inference_id = None

            if not result.output.tool_calls:
                # A reply without tool calls finishes this run.
                store.finish(run_id, RunStatus.COMPLETED, "Assistant answered")
                return TurnResult(
                    thread_id, run_id, RunStatus.COMPLETED, result.output.text
                )

            # Each accepted call already has a job and task before execution begins.
            await execute_tool_batch(store, thread_id, run_id, work)

        reason = "Generation turn limit reached"
        store.finish(run_id, RunStatus.FAILED, reason)
        return TurnResult(thread_id, run_id, RunStatus.FAILED, None, reason)
    except BaseException as error:
        # Save the failure so this run stops holding the thread open.
        status, detail = _failure_details(error)
        if inference_id is not None:
            store.fail_inference(inference_id, detail)
        store.finish(run_id, status, detail.message)
        raise


def _saved_result(
    store: ConversationStore, thread_id: ThreadId, run_id: RunId
) -> TurnResult:
    """Return a finished run's last assistant reply when its request is repeated."""
    run = store.get_run(run_id)
    if run.finished_at is None:
        raise ValueError("This request already has an active run")
    replies = [
        record
        for record in store.history(thread_id)
        if record.run_id == run_id and record.kind == ThreadRecordKind.ASSISTANT_MESSAGE
    ]
    return TurnResult(
        thread_id,
        run_id,
        run.status,
        replies[-1].payload.get("text") if replies else None,
    )


def _failure_details(error: BaseException) -> tuple[RunStatus, ErrorDetails]:
    """Choose a terminal status and safe explanation for a failed run."""
    if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt)):
        return RunStatus.CANCELLED, ErrorDetails(
            code=RunErrorCode.INTERRUPTED, message="The run was interrupted."
        )
    if isinstance(error, InferenceError):
        return RunStatus.FAILED, ErrorDetails(code=error.code, message=str(error))
    return RunStatus.FAILED, ErrorDetails(
        code=RunErrorCode.FAILED, message="The run could not finish."
    )
