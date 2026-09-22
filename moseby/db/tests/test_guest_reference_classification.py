"""Exercise note classification through the real loop, task claims and SQLite writes."""

import asyncio
from dataclasses import replace
from itertools import count
from unittest.mock import Mock, patch

from moseby.agents.agent import index_agent_definitions
from moseby.agents.concierge import definition
from moseby.db.errors import ClaimLost
from moseby.db.models.party_details import PartyDetailFilters
from moseby.db.repositories import guests, party_details
from moseby.db.tests.fixtures import NOW, identifier
from moseby.db.tests.gateway_fixtures import GatewayDatabaseTestCase
from moseby.db.tests.inference_fixtures import ScriptedProvider
from moseby.db.transaction import transaction
from moseby.domain.enums import GuestReferenceStatus
from moseby.inference.errors import InferenceError, InferenceErrorCode
from moseby.inference.guest_references import AMBIGUITY_QUESTION
from moseby.inference.models.classification import (
    BooleanAnswer,
    ClassificationKind,
    ClassificationOutput,
)
from moseby.inference.models.common import InferenceResult
from moseby.inference.models.generation import AssistantMessage, ToolMessage
from moseby.runtime.enums import RunStatus
from moseby.runtime.guest_references import GuestReferenceRecorder
from moseby.runtime.loop import run_turn
from moseby.runtime.models.messages import ToolCall
from moseby.runtime.models.thread_records import ThreadRecordKind
from moseby.runtime.storage import ConversationStore
from moseby.tools.concierge import create_tools as concierge_tools
from moseby.tools.definitions import index_tools


class ReferenceProvider(ScriptedProvider):
    def __init__(
        self,
        *,
        probabilities=None,
        failure=None,
        before_reply=None,
        usage=30,
        party_id=None,
    ):
        super().__init__(
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        id="note",
                        name="record_party_detail",
                        arguments={
                            "party_id": party_id or identifier("party"),
                            "text": "Dan does not eat peanuts.",
                        },
                    )
                ]
            ),
            AssistantMessage(text="The note is saved."),
        )
        self.probabilities = probabilities or {}
        self.failure = failure
        self.before_reply = before_reply
        self.usage = usage
        self.classifications = []

    async def classify(self, request):
        self.classifications.append(request)
        if self.before_reply:
            self.before_reply(request)
        if self.failure:
            raise self.failure
        output = ClassificationOutput(
            answers={
                name: BooleanAnswer(
                    kind=ClassificationKind.BOOLEAN,
                    probability=self.probabilities.get(
                        name, 0.01 if name == AMBIGUITY_QUESTION else 0.99
                    ),
                )
                for name in request.questions
            }
        )
        return InferenceResult(
            output=output,
            request=request.model_dump(mode="json"),
            response=output.model_dump(mode="json"),
            total_tokens=self.usage,
        )


class GuestReferenceClassificationTests(GatewayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        ticks = count(NOW + 1_000)
        clock = Mock(side_effect=lambda: next(ticks))
        for module in ("storage", "tool_worker", "tool_writes"):
            patcher = patch(f"moseby.runtime.{module}.now_microseconds", clock)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.provider = ReferenceProvider()

    def run_note(self, *, wrap_handler=None):
        recorder = GuestReferenceRecorder(
            self.engine, self.provider, "test", "classifier"
        )
        tools = index_tools(concierge_tools(self.engine, recorder))
        if wrap_handler:
            tool = tools["record_party_detail"]
            tools[tool.name] = replace(tool, handler=wrap_handler(tool.handler))
        self.store = ConversationStore(
            self.engine,
            identifier("staff_member"),
            identifier("hotel"),
            index_agent_definitions([definition()]),
            tools,
        )
        self.thread = self.store.create(definition())
        return asyncio.run(
            run_turn(
                self.store,
                self.provider,
                thread_id=self.thread,
                text="Please record Dan's note",
                request_id=f"message-{self.thread}",
                provider_name="test",
                model="generation",
            )
        )

    def notes(self):
        with transaction(self.engine) as connection:
            return party_details.find_all_by_party_id(
                connection, identifier("party"), hotel_id=identifier("hotel")
            ).items

    def test_note_is_saved_before_classification_and_references_are_auditable(self):
        """Jev sees only this party; its decision is saved without changing guest facts."""

        def while_waiting(request):
            self.assertEqual(
                self.notes()[0].reference_status, GuestReferenceStatus.PENDING
            )
            self.assertEqual(
                [guest["id"] for guest in request.state["guests"]],
                [identifier("guest")],
            )
            self.assertNotIn("dietary_requirements", request.state["guests"][0])

        self.provider.before_reply = while_waiting
        result = self.run_note()
        self.assertEqual(result.status, RunStatus.COMPLETED)
        note = self.notes()[0]
        self.assertEqual(note.referenced_guest_ids, [identifier("guest")])
        with transaction(self.engine) as connection:
            self.assertIsNone(
                guests.find_by_id(
                    connection, identifier("guest"), hotel_id=identifier("hotel")
                ).dietary_requirements
            )
        history = self.store.history(self.thread)
        decision = next(
            row for row in history if row.kind == ThreadRecordKind.CLASSIFIER_DECISION
        )
        self.assertEqual(decision.payload["decision"]["party_detail_id"], note.id)
        messages = self.provider.requests[-1].messages
        tool_result = next(
            message for message in messages if isinstance(message, ToolMessage)
        )
        self.assertIn(note.id, tool_result.content)
        self.assertNotIn(
            AMBIGUITY_QUESTION,
            " ".join(message.model_dump_json() for message in messages),
        )
        self.assertEqual(self.store.token_usage(result.run_id), 70)

    def test_empty_resolved_references_differ_from_uncertain_references(self):
        """Clear non-matches resolve to an empty list; uncertain identities remain ambiguous."""
        for probabilities, expected in (
            ({identifier("guest"): 0.01}, GuestReferenceStatus.RESOLVED),
            ({identifier("guest"): 0.5}, GuestReferenceStatus.AMBIGUOUS),
            (
                {AMBIGUITY_QUESTION: 0.99, identifier("guest"): 0.01},
                GuestReferenceStatus.AMBIGUOUS,
            ),
        ):
            with self.subTest(probabilities=probabilities):
                self.provider = ReferenceProvider(probabilities=probabilities)
                self.run_note()
                note = self.notes()[-1]
                self.assertEqual(note.reference_status, expected)
                self.assertEqual(note.referenced_guest_ids, [])

    def test_provider_failure_preserves_the_note_and_failed_decision(self):
        """A provider failure leaves readable evidence and a failed classification receipt."""
        self.provider.failure = InferenceError(InferenceErrorCode.TIMEOUT, "Timed out")
        self.run_note()
        self.assertEqual(self.notes()[0].reference_status, GuestReferenceStatus.FAILED)
        decision = next(
            row
            for row in self.store.history(self.thread)
            if row.kind == ThreadRecordKind.CLASSIFIER_DECISION
        )
        self.assertEqual(decision.payload["error"]["code"], InferenceErrorCode.TIMEOUT)
        self.assertEqual(self.notes()[0].text, "Dan does not eat peanuts.")

    def test_same_command_reuses_the_note_without_another_classification(self):
        """Repeating an accepted note command returns its result and makes no new provider call."""

        def wrap(handler):
            async def repeat(context, arguments):
                first = await handler(context, arguments)
                second = await handler(context, arguments)
                self.assertEqual(first, second)
                return second

            return repeat

        self.run_note(wrap_handler=wrap)
        self.assertEqual(len(self.notes()), 1)
        self.assertEqual(len(self.provider.classifications), 1)

    def test_other_hotels_party_is_rejected_before_saving_or_classifying(self):
        """An out-of-hotel party ID cannot cause evidence to be saved or sent to Jev."""
        self.provider = ReferenceProvider(party_id=identifier("party", 2))
        self.run_note()
        self.assertEqual(self.notes(), [])
        self.assertEqual(self.provider.classifications, [])

    def test_changed_guest_identity_discards_a_confident_match(self):
        """A reply based on an older guest name leaves the saved note ambiguous."""

        def rename(request):
            with transaction(self.engine, write=True) as connection:
                connection.execute(
                    self.metadata.tables["guests"]
                    .update()
                    .where(self.metadata.tables["guests"].c.id == identifier("guest"))
                    .values(first_name="Sam")
                )

        self.provider.before_reply = rename
        self.run_note()
        self.assertEqual(
            self.notes()[0].reference_status, GuestReferenceStatus.AMBIGUOUS
        )
        self.assertEqual(self.notes()[0].referenced_guest_ids, [])

    def test_lost_claim_prevents_saving_the_classification_result(self):
        """When the lease expires during inference, the worker leaves the note pending for recovery."""

        def expire(request):
            with transaction(self.engine, write=True) as connection:
                claims = self.metadata.tables["task_claims"]
                connection.execute(
                    claims.update().values(expires_at=claims.c.claimed_at + 1)
                )

        self.provider.before_reply = expire
        with self.assertRaises(ClaimLost):
            self.run_note()
        self.assertEqual(self.notes()[0].reference_status, GuestReferenceStatus.PENDING)
        self.assertFalse(
            any(
                row.kind == ThreadRecordKind.CLASSIFIER_DECISION
                for row in self.store.history(self.thread)
            )
        )

    def test_classification_usage_counts_towards_the_run_budget(self):
        """After a classification exhausts the budget, its result is saved and generation stops."""
        self.provider.usage = 20_000
        result = self.run_note()
        self.assertEqual(result.status, RunStatus.FAILED)
        self.assertEqual(result.reason, "Token budget reached")
        self.assertEqual(len(self.provider.requests), 1)
        self.assertEqual(
            self.notes()[0].reference_status, GuestReferenceStatus.RESOLVED
        )

    def test_cancellation_preserves_the_note_and_closes_the_tool_exchange(self):
        """Cancelling Jev leaves failed references and a complete tool result in history."""
        self.provider.failure = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.run_note()
        self.assertEqual(self.notes()[0].reference_status, GuestReferenceStatus.FAILED)
        history = self.store.history(self.thread)
        self.assertTrue(
            any(row.kind == ThreadRecordKind.TOOL_RESULT for row in history)
        )

    def test_partial_references_are_saved_returned_and_searchable(self):
        """A clear match remains on an ambiguous note and can be found through that guest."""
        with transaction(self.engine, write=True) as connection:
            self.add_guest(connection, 3)
        self.provider.probabilities = {
            AMBIGUITY_QUESTION: 0.95,
            identifier("guest"): 0.99,
            identifier("guest", 3): 0.5,
        }
        self.run_note()
        note = self.notes()[0]
        self.assertEqual(note.reference_status, GuestReferenceStatus.AMBIGUOUS)
        self.assertEqual(note.referenced_guest_ids, [identifier("guest")])
        with transaction(self.engine) as connection:
            matches = party_details.search(
                connection,
                PartyDetailFilters(
                    party_ids=[identifier("party")], guest_ids=[identifier("guest")]
                ),
                hotel_id=identifier("hotel"),
            )
        self.assertEqual([row.id for row in matches.items], [note.id])
        message = next(
            m for m in self.provider.requests[-1].messages if isinstance(m, ToolMessage)
        )
        self.assertIn(GuestReferenceStatus.AMBIGUOUS.value, message.content)
        self.assertIn(identifier("guest"), message.content)
