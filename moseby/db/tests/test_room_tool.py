import asyncio

from moseby.agents.agent import create_agent
from moseby.agents.identity import AgentReference
from moseby.agents.models import AgentDefinition, AgentDomainContext, AgentThreadContext
from moseby.contracts.rooms import SearchRoomsRequestPayload
from moseby.db.tests.fixtures import NOW, StayDatabaseTestCase, identifier
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.domain.enums import BedType
from moseby.permissions import Permission
from moseby.runtime.models.messages import ToolCall, ToolResultStatus
from moseby.services import rooms
from moseby.tools.definitions import ToolContext, index_tools
from moseby.tools.execution import ToolErrorCode, execute_tool
from moseby.tools.rooms import create_tools


class RoomToolTests(StayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "beds",
                id=identifier("bed"),
                room_id=identifier("room"),
                type=BedType.KING.value,
            )
        self.tools = index_tools(create_tools(self.engine))
        staff = AgentDomainContext(
            staff_member_id=identifier("staff_member"),
            hotel_id=identifier("hotel"),
            staff_member_display_name="Alex",
            permissions=(Permission("moseby.rooms:read"),),
        )
        thread = AgentThreadContext(
            thread_id=identifier("thread"),
            creator_staff_member_id=staff.staff_member_id,
            agent=AgentReference(id="concierge", version=1),
            permissions=staff.permissions,
        )
        self.agent = create_agent(
            AgentDefinition(
                id="concierge",
                version=1,
                display_name="Moseby",
                description="Help staff.",
                system_prompt="Help resort staff.",
                tools=("search_rooms",),
                permissions=staff.permissions,
                max_turns=8,
                token_budget=20000,
            ),
            domain_context=staff,
            thread_context=thread,
            tools={name: tool.specification for name, tool in self.tools.items()},
        )
        self.context = ToolContext(
            domain_context=staff,
            thread_context=thread,
            run_id=identifier("run"),
            source_record_id=identifier("thread_record"),
            tool_call_id="call-1",
            request_id="search-1",
        )

    def execute(self, **arguments):
        return asyncio.run(
            execute_tool(
                self.agent,
                ToolCall(id="call-1", name="search_rooms", arguments=arguments),
                context=self.context,
                tools=self.tools,
            )
        )

    def test_search_returns_room_contracts_and_cannot_expand_hotel_scope(self):
        """The real tool returns this hotel's room, beds and price without exposing another hotel."""
        result = self.execute()
        self.assertEqual(result.status, ToolResultStatus.SUCCEEDED)
        self.assertEqual(
            [room["id"] for room in result.result["items"]], [identifier("room")]
        )
        room = result.result["items"][0]
        self.assertEqual(room["price"]["amount"], {"value": 20000, "currency": "GBP"})
        self.assertEqual(
            room["beds"], [{"id": identifier("bed"), "type": BedType.KING.value}]
        )
        self.assertNotIn("created_at", room)
        self.assertEqual(
            self.execute(hotel_ids=[identifier("hotel", 2)]).result["items"], []
        )
        self.assertEqual(
            self.execute(nightly_amount={"currency": "GBP", "max_value": 10000}).result[
                "items"
            ],
            [],
        )

    def test_availability_dates_reach_the_overlap_query(self):
        """An overlapping stay excludes the room after API dates become database timestamps."""
        result = self.execute(
            availability_date_range={
                "min_date": to_datetime(NOW + 1).isoformat(),
                "max_date": to_datetime(NOW + 2).isoformat(),
            }
        )
        self.assertEqual(result.result["items"], [])

    def test_bad_cursor_returns_a_correction_the_agent_can_act_on(self):
        """A malformed cursor produces a failed tool result with instructions to restart the search."""
        result = self.execute(cursor="broken")
        self.assertEqual(result.status, ToolResultStatus.FAILED)
        self.assertEqual(result.error.code, ToolErrorCode.INVALID_ARGUMENTS)
        self.assertEqual(result.error.details, {"field": "cursor"})

    def test_service_checks_permissions_when_called_without_the_tool_executor(self):
        """Direct application callers must also have room read access."""
        with self.assertRaises(PermissionError):
            rooms.search(
                self.engine,
                SearchRoomsRequestPayload(),
                hotel_id=identifier("hotel"),
                permissions=(),
            )
