"""Short database transactions used at the boundaries of the turn loop."""

from collections.abc import Mapping
from dataclasses import dataclass
from time import time_ns

from sqlalchemy import Engine

from moseby.agents.agent import Agent, create_agent
from moseby.agents.identity import AgentReference
from moseby.agents.models import AgentDefinition, AgentThreadContext
from moseby.db.models.inference_requests import NewInferenceRequest
from moseby.db.models.runs import RunRow
from moseby.db.models.thread_records import ThreadRecordRow
from moseby.db.models.threads import NewThread
from moseby.db.operations import conversations
from moseby.db.pagination import PageRequest
from moseby.db.repositories import inference_requests, runs, thread_records
from moseby.db.repositories._writes import require_found
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.identifiers import (
    HotelId,
    InferenceRequestId,
    RunId,
    StaffMemberId,
    ThreadId,
    ThreadRecordId,
    new_id,
)
from moseby.inference.models.common import InferenceResult
from moseby.inference.models.generation import AssistantMessage
from moseby.runtime.models.common import ErrorDetails
from moseby.runtime.models.thread_records import (
    InferenceRequestPayload,
    ThreadRecordKind,
    thread_record_adapter,
)
from moseby.services import authority
from moseby.tools.definitions import Tool

from .context import ConversationInput
from .enums import RunStatus


def now_microseconds() -> int:
    return time_ns() // 1_000


@dataclass(frozen=True)
class ConversationStore:
    engine: Engine
    staff_member_id: StaffMemberId
    hotel_id: HotelId
    definitions: Mapping[AgentReference, AgentDefinition]
    tools: Mapping[str, Tool]

    def create(self, definition: AgentDefinition) -> ThreadId:
        """Capture the creator, agent and current permission ceiling once."""
        context = authority.resolve(
            self.engine, staff_member_id=self.staff_member_id, hotel_id=self.hotel_id
        )
        id = new_id("thread")
        with transaction(self.engine, write=True) as connection:
            conversations.create_thread(
                connection,
                NewThread(
                    id=id,
                    creator_staff_member_id=self.staff_member_id,
                    agent=AgentReference(id=definition.id, version=definition.version),
                    permissions=list(context.permissions),
                ),
                now=now_microseconds(),
            )
        return id

    def history(self, thread_id: ThreadId) -> list[ThreadRecordRow]:
        """Read history in sequence order within one consistent database snapshot."""
        records = []
        with transaction(self.engine) as connection:
            cursor = None
            while True:
                page = thread_records.find_all_by_thread_id(
                    connection,
                    thread_id,
                    creator_staff_member_id=self.staff_member_id,
                    page=PageRequest(limit=100, cursor=cursor),
                )
                records.extend(page.items)
                cursor = page.next_cursor
                if cursor is None:
                    return records

    def load_agent(self, thread_id: ThreadId) -> Agent:
        """Resolve current staff authority against the agent and thread saved at creation."""
        context = authority.resolve(
            self.engine, staff_member_id=self.staff_member_id, hotel_id=self.hotel_id
        )
        with transaction(self.engine) as connection:
            record = thread_records.find_first_by_thread_id(
                connection,
                thread_id,
                creator_staff_member_id=self.staff_member_id,
            )
        if record is None:
            raise PermissionError("The thread is missing or inaccessible")
        first = thread_record_adapter.validate_python(
            record.model_dump() | {"created_at": to_datetime(record.created_at)}
        )
        thread_context = AgentThreadContext.from_creation_record(first)
        definition = self.definitions.get(thread_context.agent)
        if definition is None:
            raise ValueError("The saved agent version is not installed")
        return create_agent(
            definition,
            domain_context=context,
            thread_context=thread_context,
            tools={name: tool.specification for name, tool in self.tools.items()},
        )

    def begin(
        self, thread_id: ThreadId, text: str, request_id: str
    ) -> conversations.AcceptedTurn:
        self.load_agent(thread_id)
        with transaction(self.engine, write=True) as connection:
            return conversations.begin_turn(
                connection,
                thread_id,
                text,
                request_id=request_id,
                actor=self.staff_member_id,
                now=now_microseconds(),
            )

    def get_run(self, run_id: RunId) -> RunRow:
        with transaction(self.engine) as connection:
            return require_found(
                runs.find_by_id(
                    connection, run_id, creator_staff_member_id=self.staff_member_id
                )
            )

    def token_usage(self, run_id: RunId) -> int | None:
        """Include generation and classification in the run's reported token usage."""
        with transaction(self.engine) as connection:
            return inference_requests.token_usage(
                connection, run_id, creator_staff_member_id=self.staff_member_id
            )

    def prepare(
        self,
        thread_id: ThreadId,
        run_id: RunId,
        context: ConversationInput,
        *,
        provider: str,
        model: str,
    ) -> tuple[InferenceRequestId, ThreadRecordId]:
        """Save selected input, its history marker and dispatch before contacting the provider."""
        id = new_id("inference_request")
        with transaction(self.engine, write=True) as connection:
            now = now_microseconds()
            inference_requests.prepare(
                connection,
                NewInferenceRequest(
                    id=id,
                    thread_id=thread_id,
                    run_id=run_id,
                    provider=provider,
                    model=model,
                    request=context.request.model_dump(mode="json"),
                ),
                context.record_ids,
                creator_staff_member_id=self.staff_member_id,
                now=now,
            )
            record = conversations.append(
                connection,
                thread_id,
                ThreadRecordKind.INFERENCE_REQUEST,
                InferenceRequestPayload(inference_request_id=id),
                actor=self.staff_member_id,
                now=now,
                run_id=run_id,
            )
            inference_requests.start(
                connection, id, creator_staff_member_id=self.staff_member_id, now=now
            )
        return id, record.id

    def accept(
        self,
        thread_id: ThreadId,
        run_id: RunId,
        inference_id: InferenceRequestId,
        source_record_id: ThreadRecordId,
        result: InferenceResult[AssistantMessage],
    ) -> tuple[ThreadRecordRow, list[conversations.AcceptedTool]]:
        """Save the inference result, accepted reply and queued tools atomically."""
        with transaction(self.engine, write=True) as connection:
            now = now_microseconds()
            inference_requests.finish(
                connection,
                inference_id,
                creator_staff_member_id=self.staff_member_id,
                now=now,
                response=result.model_dump(mode="json"),
            )
            return conversations.accept_reply(
                connection,
                thread_id,
                run_id,
                result.output,
                source_record_id=source_record_id,
                actor=self.staff_member_id,
                now=now,
            )

    def fail_inference(
        self, inference_id: InferenceRequestId, error: ErrorDetails
    ) -> None:
        with transaction(self.engine, write=True) as connection:
            inference_requests.finish(
                connection,
                inference_id,
                creator_staff_member_id=self.staff_member_id,
                now=now_microseconds(),
                error=error,
            )

    def finish(self, run_id: RunId, status: RunStatus, reason: str) -> None:
        with transaction(self.engine, write=True) as connection:
            conversations.finish_run(
                connection,
                run_id,
                status,
                reason=reason,
                actor=self.staff_member_id,
                now=now_microseconds(),
            )
