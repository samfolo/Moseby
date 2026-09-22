"""Exercise the real loop and SQLite boundaries with a scripted inference provider."""

import asyncio

from moseby.agents.agent import index_agent_definitions
from moseby.agents.models import AgentDefinition
from moseby.agents.prompts import concierge_prompt
from moseby.db.errors import WriteConflict
from moseby.db.models.jobs import JobFilters
from moseby.db.models.tasks import TaskFilters
from moseby.db.repositories import jobs, runs, tasks
from moseby.db.tests.fixtures import identifier
from moseby.db.tests.gateway_fixtures import GatewayDatabaseTestCase
from moseby.db.transaction import transaction
from moseby.inference.errors import InferenceError, InferenceErrorCode
from moseby.inference.models.common import InferenceResult
from moseby.inference.models.generation import AssistantMessage, ToolMessage
from moseby.permissions import Permission
from moseby.runtime.enums import JobStatus, RunStatus, TaskStatus
from moseby.runtime.loop import run_turn
from moseby.runtime.models.messages import ToolCall
from moseby.runtime.models.thread_records import ThreadRecordKind
from moseby.runtime.storage import ConversationStore
from moseby.tools.definitions import index_tools
from moseby.tools.rooms import create_tools


class ScriptedProvider:
    def __init__(self, *replies, total_tokens=20):
        self.replies = iter(replies)
        self.requests = []
        self.total_tokens = total_tokens

    async def generate(self, request):
        self.requests.append(request)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return InferenceResult(
            output=reply,
            request=request.model_dump(mode="json"),
            response={"choices": []},
            total_tokens=self.total_tokens,
        )


class TurnLoopTests(GatewayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.definition = AgentDefinition(
            id="concierge",
            version=1,
            display_name="Moseby",
            description="Help resort staff.",
            system_prompt=concierge_prompt(),
            tools=("search_rooms",),
            permissions=(Permission("moseby.rooms:read"),),
            max_turns=4,
            token_budget=2000,
        )
        self.store = self.make_store()
        self.thread_id = self.store.create(self.definition)

    def make_store(self):
        return ConversationStore(
            self.engine,
            identifier("staff_member"),
            identifier("hotel"),
            index_agent_definitions([self.definition]),
            index_tools(create_tools(self.engine)),
        )

    def turn(self, provider, *, text="Hello", request_id="message-1"):
        return asyncio.run(
            run_turn(
                self.store,
                provider,
                thread_id=self.thread_id,
                text=text,
                request_id=request_id,
                provider_name="test",
                model="test-model",
            )
        )

    def test_reopen_restores_history_and_duplicate_request_does_not_run_again(self):
        """A second process-style store sees the first exchange; retries reuse the original run."""
        first = self.turn(ScriptedProvider(AssistantMessage(text="Hello Alex")))
        self.assertEqual(first.status, RunStatus.COMPLETED)
        self.store = self.make_store()
        replay = ScriptedProvider()
        same = self.turn(replay)
        self.assertEqual(same.run_id, first.run_id)
        self.assertEqual(replay.requests, [])
        provider = ScriptedProvider(AssistantMessage(text="You said hello"))
        self.turn(provider, text="What did I say?", request_id="message-2")
        self.assertEqual(
            [m.role for m in provider.requests[0].messages],
            ["system", "system", "user", "assistant", "user"],
        )
        self.assertEqual(provider.requests[0].messages[2].content, "Hello")
        with transaction(self.engine) as connection:
            self.assertIsNone(
                runs.find_active_by_thread_id(
                    connection,
                    self.thread_id,
                    creator_staff_member_id=self.store.staff_member_id,
                )
            )
        history = self.store.history(self.thread_id)
        self.assertEqual(
            [r.sequence for r in history], list(range(1, len(history) + 1))
        )

    def test_tool_jobs_claims_and_delivery_feed_the_next_request(self):
        """A room search is queued, claimed and delivered before the model receives its result."""
        provider = ScriptedProvider(
            AssistantMessage(
                tool_calls=[ToolCall(id="call-1", name="search_rooms", arguments={})],
                provider_state={"reasoning": "opaque"},
            ),
            AssistantMessage(text="The Rose room is available to inspect."),
        )
        result = self.turn(provider, text="Show me the rooms")
        self.assertEqual(result.status, RunStatus.COMPLETED)
        second = provider.requests[1]
        tool = next(m for m in second.messages if isinstance(m, ToolMessage))
        self.assertEqual(tool.tool_call_id, "call-1")
        self.assertIn(identifier("room"), tool.content)
        assistant = next(m for m in second.messages if isinstance(m, AssistantMessage))
        self.assertEqual(assistant.provider_state, {"reasoning": "opaque"})
        with transaction(self.engine) as connection:
            job = jobs.search(
                connection,
                JobFilters(run_ids=[result.run_id]),
                actor_staff_member_id=self.store.staff_member_id,
            ).items[0]
            task = tasks.search(
                connection,
                TaskFilters(job_id=job.id),
                actor_staff_member_id=self.store.staff_member_id,
            ).items[0]
            self.assertEqual(
                (job.status, task.status, task.attempt_count),
                (JobStatus.SUCCEEDED, TaskStatus.SUCCEEDED, 1),
            )
        results = [
            r
            for r in self.store.history(self.thread_id)
            if r.kind == ThreadRecordKind.TOOL_RESULT
        ]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].payload["job_id"], job.id)

    def test_provider_failure_finishes_the_run_and_allows_a_new_message(self):
        """A failed request leaves durable failure state without keeping the thread busy."""
        with self.assertRaises(InferenceError):
            self.turn(
                ScriptedProvider(
                    InferenceError(InferenceErrorCode.TIMEOUT, "Timed out")
                )
            )
        with transaction(self.engine) as connection:
            failed = runs.find_all_by_thread_id(
                connection,
                self.thread_id,
                creator_staff_member_id=self.store.staff_member_id,
            ).items[0]
            self.assertEqual(failed.status, RunStatus.FAILED)
        result = self.turn(
            ScriptedProvider(AssistantMessage(text="Hello")), request_id="message-2"
        )
        self.assertEqual(result.status, RunStatus.COMPLETED)

    def test_inference_wait_does_not_hold_a_write_transaction_or_allow_a_second_run(
        self,
    ):
        """While inference waits, other transactions work but another run on this thread is rejected."""
        store, thread = self.store, self.thread_id

        class Provider(ScriptedProvider):
            async def generate(self, request):
                with self_test.assertRaises(WriteConflict):
                    store.begin(thread, "another message", "message-2")
                return await super().generate(request)

        self_test = self
        self.assertEqual(
            self.turn(Provider(AssistantMessage(text="Done"))).status,
            RunStatus.COMPLETED,
        )

    def test_turn_limit_stops_after_saving_the_tool_result(self):
        """A tool-calling model reaches the generation limit with a complete saved tool exchange."""
        self.definition = self.definition.model_copy(update={"max_turns": 1})
        self.store = self.make_store()
        provider = ScriptedProvider(
            AssistantMessage(
                tool_calls=[ToolCall(id="call-1", name="search_rooms", arguments={})]
            )
        )
        result = self.turn(provider)
        self.assertEqual(result.status, RunStatus.FAILED)
        self.assertEqual(len(provider.requests), 1)
        self.assertTrue(
            any(
                r.kind == ThreadRecordKind.TOOL_RESULT
                for r in self.store.history(self.thread_id)
            )
        )

    def test_cancellation_records_all_accepted_calls_without_executing_the_rest(self):
        """Cancelling a multi-call reply saves a result for every call, allowing another turn."""
        from dataclasses import replace

        tool = self.store.tools["search_rooms"]
        called = []

        async def interrupted(context, arguments):
            called.append(context.tool_call_id)
            raise asyncio.CancelledError

        self.store = replace(
            self.store, tools={"search_rooms": replace(tool, handler=interrupted)}
        )
        provider = ScriptedProvider(
            AssistantMessage(
                tool_calls=[
                    ToolCall(id=f"call-{number}", name="search_rooms", arguments={})
                    for number in (1, 2)
                ]
            )
        )
        with self.assertRaises(asyncio.CancelledError):
            self.turn(provider)
        self.assertEqual(called, ["call-1"])
        results = [
            r
            for r in self.store.history(self.thread_id)
            if r.kind == ThreadRecordKind.TOOL_RESULT
        ]
        self.assertEqual(len(results), 2)
        self.store = self.make_store()
        self.assertEqual(
            self.turn(
                ScriptedProvider(AssistantMessage(text="Hello again")),
                request_id="message-2",
            ).status,
            RunStatus.COMPLETED,
        )

    def test_missing_usage_and_exhausted_budget_prevent_a_second_inference(self):
        """Tool results are saved, but missing or exhausted usage prevents another provider call."""
        for usage in (None, 2000):
            with self.subTest(usage=usage):
                self.thread_id = self.store.create(self.definition)

                provider = ScriptedProvider(
                    AssistantMessage(
                        tool_calls=[
                            ToolCall(id="call-1", name="search_rooms", arguments={})
                        ]
                    ),
                    total_tokens=usage,
                )
                result = self.turn(provider, request_id=f"usage-{usage}")
                self.assertEqual(result.status, RunStatus.FAILED)
                self.assertEqual(len(provider.requests), 1)

    def test_revoked_authority_prevents_accepting_or_executing_a_reply(self):
        """Revoking access while inference is in flight prevents its reply from driving tools."""
        from moseby.domain.enums import StaffRole

        test = self

        class Provider(ScriptedProvider):
            async def generate(self, request):
                with transaction(test.engine, write=True) as connection:
                    connection.execute(
                        test.metadata.tables["staff_members"]
                        .update()
                        .values(role=StaffRole.UNKNOWN)
                    )
                return await super().generate(request)

        with self.assertRaises(PermissionError):
            self.turn(
                Provider(
                    AssistantMessage(
                        tool_calls=[
                            ToolCall(id="call-1", name="search_rooms", arguments={})
                        ]
                    )
                )
            )
        history = self.store.history(self.thread_id)
        self.assertFalse(
            any(r.kind == ThreadRecordKind.ASSISTANT_MESSAGE for r in history)
        )

    def test_inference_keeps_input_links_and_an_outcome_after_failure(self):
        """A failed attempt still identifies the exact saved user input it tried to use."""
        from moseby.db.repositories import inference_requests
        from moseby.runtime.enums import InferenceStatus

        with self.assertRaises(InferenceError):
            self.turn(
                ScriptedProvider(
                    InferenceError(InferenceErrorCode.TIMEOUT, "Timed out")
                )
            )
        history = self.store.history(self.thread_id)
        marker = next(
            r for r in history if r.kind == ThreadRecordKind.INFERENCE_REQUEST
        )
        with transaction(self.engine) as connection:
            attempt = inference_requests.find_by_id(
                connection,
                marker.payload["inference_request_id"],
                creator_staff_member_id=self.store.staff_member_id,
            )
            self.assertEqual(attempt.status, InferenceStatus.FAILED)
            self.assertEqual(attempt.request["messages"][-1]["content"], "Hello")
            self.assertEqual(attempt.error["code"], InferenceErrorCode.TIMEOUT)
            links = (
                connection.execute(
                    self.metadata.tables["inference_request_records"].select()
                )
                .mappings()
                .all()
            )
            self.assertEqual(
                [row["record_id"] for row in links],
                [
                    next(
                        r.id for r in history if r.kind == ThreadRecordKind.USER_MESSAGE
                    )
                ],
            )

    def test_reply_and_jobs_roll_back_together_if_a_task_cannot_be_saved(self):
        """Failure while queueing a reply leaves neither its assistant record nor a partial job."""
        from unittest.mock import patch

        original = tasks.create
        count = 0

        def fail_second(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError("Cannot save second task")
            return original(*args, **kwargs)

        provider = ScriptedProvider(
            AssistantMessage(
                tool_calls=[
                    ToolCall(id=f"call-{number}", name="search_rooms", arguments={})
                    for number in (1, 2)
                ]
            )
        )
        with patch(
            "moseby.db.operations.conversations.tasks.create", side_effect=fail_second
        ):
            with self.assertRaises(RuntimeError):
                self.turn(provider)
        history = self.store.history(self.thread_id)
        self.assertFalse(
            any(r.kind == ThreadRecordKind.ASSISTANT_MESSAGE for r in history)
        )
        with transaction(self.engine) as connection:
            self.assertEqual(
                jobs.find_all(
                    connection, actor_staff_member_id=self.store.staff_member_id
                ).items,
                [],
            )
