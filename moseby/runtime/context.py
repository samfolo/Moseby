"""Select model-facing conversation messages from the durable event history."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from moseby.agents.agent import Agent
from moseby.db.models.thread_records import ThreadRecordRow
from moseby.db.timestamps import to_datetime
from moseby.inference.models.generation import (
    AssistantMessage,
    ChatMessage,
    GenerationRequest,
    TextMessage,
    ToolMessage,
)
from moseby.runtime.models.thread_records import (
    AssistantMessageRecord,
    ToolResultRecord,
    UserMessageRecord,
    thread_record_adapter,
)


@dataclass(frozen=True)
class ConversationInput:
    request: GenerationRequest
    record_ids: list[str]


def prepare_context(agent: Agent, records: list[ThreadRecordRow]) -> ConversationInput:
    """Keep user, assistant and tool messages in order; exclude runtime bookkeeping.

    Preserve provider continuation fields and tool IDs exactly as returned.
    """
    context = agent.domain_context
    messages: list[ChatMessage] = [
        TextMessage(role="system", content=agent.definition.system_prompt),
        TextMessage(
            role="system",
            content="Current staff and hotel context: "
            + json.dumps(
                {
                    "staff_member_id": context.staff_member_id,
                    "staff_member_name": context.staff_member_display_name,
                    "hotel_id": context.hotel_id,
                }
            ),
        ),
    ]
    selected = []
    pending: set[tuple[str, str]] = set()
    for row in records:
        record = thread_record_adapter.validate_python(
            row.model_dump() | {"created_at": to_datetime(row.created_at)}
        )
        if isinstance(record, UserMessageRecord):
            # Keep relative dates tied to the original message when a thread resumes.
            messages.append(
                TextMessage(
                    role="system",
                    content=f"The following user message was recorded at {record.created_at.isoformat()}.",
                )
            )
            messages.append(TextMessage(role="user", content=record.payload.text))
        elif isinstance(record, AssistantMessageRecord):
            for call in record.payload.tool_calls:
                pending.add((record.id, call.id))
            messages.append(
                AssistantMessage(
                    **record.payload.model_dump(),
                )
            )
        elif isinstance(record, ToolResultRecord):
            source = (record.source_record_id, record.tool_call_id)
            if source not in pending:
                raise ValueError("A tool result has no preceding unresolved call")
            pending.remove(source)
            messages.append(
                ToolMessage(
                    tool_call_id=record.tool_call_id,
                    content=record.payload.model_dump_json(),
                )
            )
        else:
            continue
        selected.append(record.id)
    if pending:
        raise ValueError(
            "This thread has unfinished tool calls; resolve its interrupted run before continuing"
        )
    # Put the changing clock after history so the earlier prompt stays reusable.
    messages.append(
        TextMessage(
            role="system",
            content="Runtime notice: "
            + json.dumps({"current_time_utc": datetime.now(UTC).isoformat()}),
        )
    )
    return ConversationInput(
        GenerationRequest(messages=messages, tools=list(agent.tools)), selected
    )
