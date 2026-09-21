import unittest

from pydantic import ValidationError

from moseby.agents.agent import create_agent, index_agent_definitions
from moseby.agents.identity import AgentReference
from moseby.agents.models import (
    AgentDefinition,
    AgentDomainContext,
    AgentThreadContext,
    ToolSpecification,
)
from moseby.agents.prompts import concierge_prompt
from moseby.inference.models.generation import ToolDefinition
from moseby.permissions import Permission, PermissionResolver


def scopes(*values):
    return tuple(Permission(value) for value in values)


def definition(**changes):
    return AgentDefinition.model_validate(
        {
            "id": "concierge",
            "version": 1,
            "display_name": "Moseby",
            "description": "Help resort staff look after their guests.",
            "system_prompt": concierge_prompt(),
            "tools": ("find_guests", "update_guest"),
            "permissions": scopes("moseby.guests:read", "moseby.guests:write"),
            "max_turns": 8,
            "token_budget": 20000,
        }
        | changes
    )


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.staff = AgentDomainContext(
            staff_member_id="staff_member_00000000000000000000000001",
            hotel_id="hotel_00000000000000000000000001",
            staff_member_display_name="Alex Morgan",
            permissions=scopes("moseby:read", "moseby:write"),
        )
        self.thread = AgentThreadContext(
            thread_id="thread_00000000000000000000000001",
            agent=AgentReference(id="concierge", version=1),
            creator_staff_member_id=self.staff.staff_member_id,
            permissions=scopes("moseby.guests:read"),
        )
        self.tools = {
            name: ToolSpecification(
                definition=ToolDefinition(
                    name=name,
                    description=description,
                    parameters={"type": "object", "properties": {}},
                ),
                required_permissions=scopes(permission),
            )
            for name, description, permission in (
                ("find_guests", "Find guests.", "moseby.guests:read"),
                ("update_guest", "Update a guest.", "moseby.guests:write"),
            )
        }

    def test_definition_survives_a_json_round_trip_with_its_prompt(self):
        """The complete agent settings can be saved as JSON and validated again."""
        original = definition()
        restored = AgentDefinition.model_validate_json(original.model_dump_json())
        self.assertEqual(restored, original)
        self.assertEqual(restored.system_prompt, concierge_prompt())
        self.assertNotIn(self.staff.staff_member_id, restored.system_prompt)
        self.assertEqual(restored.max_turns, 8)

    def test_bad_code_defined_settings_fail_validation(self):
        """Blank instructions, duplicate selections and invalid limits fail at construction."""
        for changes in (
            {"system_prompt": " \n"},
            {"id": "Has Spaces"},
            {"tools": ("find_guests", "find_guests")},
            {"tools": (" ",)},
            {"permissions": scopes("moseby:read", "moseby:read")},
            {"id": "a" * 65},
            {"version": 0},
            {"version": True},
            {"max_turns": 0},
            {"max_turns": True},
            {"token_budget": -1},
            {"token_budget": 1.5},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                definition(**changes)

    def test_thread_snapshot_prevents_new_staff_grants_from_exposing_more_tools(self):
        """A staff member with write access still gets only this thread's read tools."""
        agent = create_agent(
            definition(),
            domain_context=self.staff,
            thread_context=self.thread,
            tools=self.tools,
        )
        self.assertEqual(agent.permissions, scopes("moseby.guests:read"))
        self.assertEqual([tool.name for tool in agent.tools], ["find_guests"])
        self.assertEqual(
            agent.domain_context.staff_member_id, self.staff.staff_member_id
        )
        self.assertEqual(agent.thread_context.thread_id, self.thread.thread_id)

    def test_agent_definition_caps_a_more_privileged_thread(self):
        """A read-only agent stays read-only even when the thread allows writes."""
        thread = self.thread.model_copy(
            update={"permissions": scopes("moseby:read", "moseby:write")}
        )
        agent = create_agent(
            definition(permissions=scopes("moseby.guests:read")),
            domain_context=self.staff,
            thread_context=thread,
            tools=self.tools,
        )
        self.assertEqual(agent.permissions, scopes("moseby.guests:read"))
        self.assertEqual([tool.name for tool in agent.tools], ["find_guests"])

    def test_revoked_authority_blocks_the_whole_thread(self):
        """Losing a saved permission denies the thread, including its earlier history."""
        staff = self.staff.model_copy(
            update={"permissions": scopes("moseby.rooms:read")}
        )
        with self.assertRaises(PermissionError):
            create_agent(
                definition(),
                domain_context=staff,
                thread_context=self.thread,
                tools=self.tools,
            )

    def test_another_staff_member_cannot_construct_an_agent_for_the_thread(self):
        """Broad permissions do not let another staff member use the creator's thread."""
        staff = self.staff.model_copy(
            update={"staff_member_id": "staff_member_00000000000000000000000002"}
        )
        with self.assertRaises(PermissionError):
            create_agent(
                definition(),
                domain_context=staff,
                thread_context=self.thread,
                tools=self.tools,
            )

    def test_a_different_agent_or_unregistered_tool_fails_loudly(self):
        """Selecting the wrong definition or misspelling a tool is a configuration error."""
        for config in (
            definition(id="another-agent"),
            definition(version=2),
            definition(tools=("missing",)),
        ):
            with self.subTest(id=config.id), self.assertRaises(ValueError):
                create_agent(
                    config,
                    domain_context=self.staff,
                    thread_context=self.thread,
                    tools=self.tools,
                )

    def test_catalogue_keeps_versions_separate_and_rejects_duplicate_selections(self):
        """Two versions can share an ID, but each ID and version identifies one definition."""
        first, second = definition(), definition(version=2)
        indexed = index_agent_definitions([first, second])
        self.assertEqual(indexed[self.thread.agent], first)
        self.assertEqual(indexed[AgentReference(id="concierge", version=2)], second)
        with self.assertRaises(ValueError):
            index_agent_definitions([first, definition(display_name="Different")])

    def test_tools_require_every_permission_and_are_copied_from_the_catalogue(self):
        """A tool with several requirements is offered only when all of them are allowed."""
        self.tools["find_guests"] = self.tools["find_guests"].model_copy(
            update={
                "required_permissions": scopes(
                    "moseby.guests:read", "moseby.activities:read"
                )
            }
        )
        agent = create_agent(
            definition(),
            domain_context=self.staff,
            thread_context=self.thread,
            tools=self.tools,
        )
        self.assertEqual(agent.tools, ())
        self.tools["find_guests"] = self.tools["find_guests"].model_copy(
            update={"required_permissions": scopes("moseby.guests:read")}
        )
        agent = create_agent(
            definition(),
            domain_context=self.staff,
            thread_context=self.thread,
            tools=self.tools,
        )
        agent.tools[0].parameters["title"] = "Local copy"
        self.assertNotIn("title", self.tools["find_guests"].definition.parameters)


class PermissionIntersectionTests(unittest.TestCase):
    def test_overlap_keeps_the_narrower_scope_in_either_order(self):
        """Broad and narrow grants agree only on the narrower permission."""
        broad = scopes("moseby:read")
        narrow = scopes("moseby.guests:read")
        self.assertEqual(PermissionResolver.intersection(broad, narrow), narrow)
        self.assertEqual(PermissionResolver.intersection(narrow, broad), narrow)

    def test_similar_names_and_different_actions_do_not_overlap(self):
        """Matching text fragments cannot bypass the permission path or action."""
        for other in (
            "moseby.guest:read",
            "moseby.guests:write",
            "moseby.activities:read",
        ):
            with self.subTest(other=other):
                self.assertEqual(
                    PermissionResolver.intersection(
                        scopes("moseby.guests:read"), scopes(other)
                    ),
                    (),
                )
        self.assertEqual(PermissionResolver.intersection((), scopes("moseby:read")), ())

    def test_redundant_descendants_are_removed_without_adding_access(self):
        """A shared parent permission already covers its shared descendants."""
        self.assertEqual(
            PermissionResolver.intersection(
                scopes("moseby:read", "moseby.guests:read"),
                scopes("moseby.guests:read", "moseby.guests.details:read"),
            ),
            scopes("moseby.guests:read"),
        )
