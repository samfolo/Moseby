import unittest
from unittest.mock import AsyncMock

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from moseby.agents.agent import create_agent
from moseby.agents.identity import AgentReference
from moseby.agents.models import AgentDefinition, AgentDomainContext, AgentThreadContext
from moseby.permissions import Permission
from moseby.runtime.models.common import ErrorDetails
from moseby.runtime.models.messages import ToolCall, ToolResultStatus
from moseby.tools.definitions import Tool, ToolContext, index_tools
from moseby.tools.execution import ToolErrorCode, ToolFailure, execute_tool


class FindGuestsArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)


class FindGuestsResult(BaseModel):
    names: list[str]


class ToolExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        read = (Permission("moseby.guests:read"),)
        self.handler = AsyncMock(return_value=FindGuestsResult(names=["Dan"]))
        self.tool = Tool(
            name="find_guests",
            description="Find guests by name.",
            arguments=FindGuestsArguments,
            result=FindGuestsResult,
            required_permissions=read,
            handler=self.handler,
        )
        self.tools = index_tools([self.tool])
        staff = AgentDomainContext(
            staff_member_id="staff_member_00000000000000000000000001",
            hotel_id="hotel_00000000000000000000000001",
            staff_member_display_name="Alex",
            permissions=read,
        )
        thread = AgentThreadContext(
            thread_id="thread_00000000000000000000000001",
            creator_staff_member_id=staff.staff_member_id,
            agent=AgentReference(id="concierge", version=1),
            permissions=read,
        )
        definition = AgentDefinition(
            id="concierge",
            version=1,
            display_name="Moseby",
            description="Help staff.",
            system_prompt="Help resort staff.",
            tools=("find_guests",),
            permissions=read,
            max_turns=8,
            token_budget=20000,
        )
        self.agent = create_agent(
            definition,
            domain_context=staff,
            thread_context=thread,
            tools={name: tool.specification for name, tool in self.tools.items()},
        )
        self.context = ToolContext(
            domain_context=staff,
            thread_context=thread,
            run_id="run_00000000000000000000000001",
            source_record_id="thread_record_00000000000000000000000001",
            tool_call_id="call-1",
            request_id="lookup-1",
        )
        self.call = ToolCall(id="call-1", name="find_guests", arguments={"name": "Dan"})

    async def execute(self, call=None, context=None):
        return await execute_tool(
            self.agent,
            call or self.call,
            context=context or self.context,
            tools=self.tools,
        )

    async def test_schema_and_handler_share_the_same_argument_model(self):
        """The model sees the schema used to validate arguments before calling the handler."""
        self.assertEqual(
            self.agent.tools[0].parameters, FindGuestsArguments.model_json_schema()
        )
        result = await self.execute()
        self.assertEqual(result.status, ToolResultStatus.SUCCEEDED)
        self.assertEqual(result.result, {"names": ["Dan"]})
        self.handler.assert_awaited_once_with(
            self.context, FindGuestsArguments(name="Dan")
        )

    async def test_invalid_arguments_report_fields_and_do_not_call_the_handler(self):
        """Bad arguments produce useful field errors while keeping submitted values out."""
        result = await self.execute(
            self.call.model_copy(
                update={"arguments": {"name": [], "secret": "guest detail"}}
            )
        )
        self.assertEqual(result.error.code, ToolErrorCode.INVALID_ARGUMENTS)
        self.assertIn("name", str(result.error.details))
        self.assertNotIn("guest detail", result.model_dump_json())
        self.handler.assert_not_awaited()

    async def test_revoked_permissions_block_a_previously_visible_tool(self):
        """Losing access after agent construction prevents its handler from running."""
        context = self.context.model_copy(
            update={
                "domain_context": self.context.domain_context.model_copy(
                    update={"permissions": ()}
                )
            }
        )
        result = await self.execute(context=context)
        self.assertEqual(result.error.code, ToolErrorCode.PERMISSION_DENIED)
        self.handler.assert_not_awaited()

    async def test_unoffered_tool_cannot_be_called_even_when_registered(self):
        """A model cannot invoke another registered tool by guessing its name."""
        other = Tool(
            name="hidden",
            description="Another operation.",
            arguments=FindGuestsArguments,
            result=FindGuestsResult,
            required_permissions=(),
            handler=self.handler,
        )
        self.tools["hidden"] = other
        result = await self.execute(self.call.model_copy(update={"name": "hidden"}))
        self.assertEqual(result.error.code, ToolErrorCode.NOT_AVAILABLE)
        self.handler.assert_not_awaited()

    async def test_expected_failure_keeps_the_details_needed_for_correction(self):
        """A handler can return a safe, specific conflict for the agent to resolve."""
        error = ErrorDetails(
            code="GUEST_AMBIGUOUS",
            message="Two guests match Dan.",
            details={"guest_ids": ["first", "second"]},
        )
        self.handler.side_effect = ToolFailure(error)
        result = await self.execute()
        self.assertEqual(result.error, error)

    async def test_wrong_context_and_broken_handlers_reach_worker_failure_handling(
        self,
    ):
        """Execution wiring and handler bugs remain distinguishable from bad model arguments."""
        with self.assertRaises(ValueError):
            await self.execute(
                context=self.context.model_copy(update={"tool_call_id": "other-call"})
            )
        self.handler.assert_not_awaited()
        self.handler.side_effect = RuntimeError("internal failure")
        with self.assertRaises(RuntimeError):
            await self.execute()
        self.handler.side_effect = None
        self.handler.return_value = {"names": 42}
        with self.assertRaises(ValidationError):
            await self.execute()

    async def test_a_mutated_result_is_validated_again_before_delivery(self):
        """A handler's result must still be valid if it was changed after construction."""
        result = FindGuestsResult(names=["Dan"])
        result.names.append(42)
        self.handler.return_value = result
        with self.assertRaises(ValidationError):
            await self.execute()

    def test_duplicate_tool_registration_fails_at_startup(self):
        """A name resolves to exactly one handler in the tool catalogue."""
        with self.assertRaises(ValueError):
            index_tools([self.tool, self.tool])
