"""Exercise activity booking through HTTP and the agent's claimed tool jobs."""

import asyncio
import json
from unittest.mock import patch

from moseby.agents.agent import index_agent_definitions
from moseby.agents.concierge import definition
from moseby.db.models.activities import NewActivity
from moseby.db.models.filters import DateRange
from moseby.db.repositories import activities, activity_reservations
from moseby.db.tests.fixtures import NOW, identifier
from moseby.db.tests.gateway_fixtures import GatewayDatabaseTestCase
from moseby.db.tests.inference_fixtures import ScriptedProvider
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.domain.enums import StaffRole
from moseby.inference.models.common import InferenceResult
from moseby.inference.models.generation import AssistantMessage, ToolMessage
from moseby.runtime.enums import RunStatus
from moseby.runtime.guest_references import GuestReferenceRecorder
from moseby.runtime.loop import run_turn
from moseby.runtime.models.messages import ToolCall, ToolResultStatus
from moseby.runtime.storage import ConversationStore
from moseby.tools.concierge import create_tools as concierge_tools
from moseby.tools.definitions import index_tools


class JourneyProvider:
    """Walk through a reservation using IDs returned by real tool executions."""

    def __init__(self):
        self.requests = []
        self.results = []
        self.guest_id = None
        self.reservation_id = None
        self.steps = iter(
            (
                self.find_guest,
                self.find_activity,
                self.reserve_place,
                self.read_itinerary,
                self.cancel_reservation,
                self.finish,
            )
        )

    async def generate(self, request):
        value = None
        if self.requests:
            message = next(
                m for m in reversed(request.messages) if isinstance(m, ToolMessage)
            )
            result = json.loads(message.content)
            self.results.append(result)
            if result["status"] != ToolResultStatus.SUCCEEDED:
                raise AssertionError(result)
            value = result["result"]
        self.requests.append(request)
        reply = next(self.steps)(value)
        return InferenceResult(
            output=reply,
            request=request.model_dump(mode="json"),
            response={},
            total_tokens=20,
        )

    def call(self, tool_name, **arguments):
        return AssistantMessage(
            tool_calls=[
                ToolCall(
                    id=f"call-{len(self.requests)}", name=tool_name, arguments=arguments
                )
            ]
        )

    def find_guest(self, _):
        return self.call("search_guests", name="Dan")

    def find_activity(self, guests):
        self.guest_id = guests["items"][0]["id"]
        return self.call("search_activities", places_required=1)

    def reserve_place(self, activities):
        return self.call(
            "reserve_activity_places",
            activity_id=activities["items"][0]["id"],
            guest_ids=[self.guest_id],
        )

    def read_itinerary(self, reservations):
        self.reservation_id = reservations["reservations"][0]["id"]
        return self.call("search_activity_reservations", guest_ids=[self.guest_id])

    def cancel_reservation(self, itinerary):
        reservation = itinerary["items"][0]
        return self.call(
            "cancel_activity_reservation",
            reservation_id=reservation["id"],
            expected_revision=reservation["revision"],
            reason="The guest changed their plans",
        )

    def finish(self, _):
        return AssistantMessage(text="The place was reserved and then cancelled.")


class ActivityJourneyTests(GatewayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        for module in ("storage", "tool_worker", "tool_writes"):
            patcher = patch(
                f"moseby.runtime.{module}.now_microseconds", return_value=NOW + 1
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch(
            "moseby.gateway.activity_reservations.now_microseconds",
            return_value=NOW + 1,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        with transaction(self.engine, write=True) as connection:
            self.add_guest(connection, 3)
            self.insert(
                connection, "venues", id=identifier("venue"), name="Studio", capacity=20
            )
            activities.create(
                connection,
                NewActivity(
                    id=identifier("activity"),
                    venue_id=identifier("venue"),
                    title="Pottery",
                    type="ACTIVITY_TYPE_POTTERY",
                    description="Make a pot",
                    date_range=DateRange(min_date=NOW + 10, max_date=NOW + 20),
                    capacity=2,
                    min_booking_size=1,
                    max_booking_size=2,
                    minimum_age=18,
                    price_id=identifier("price"),
                ),
                now=NOW,
            )

    def reserve(self, guest_numbers=(1,), request_id="reserve-1"):
        return self.client.post(
            "/activity-reservations",
            json={
                "request_id": request_id,
                "payload": {
                    "activity_id": identifier("activity"),
                    "guest_ids": [identifier("guest", n) for n in guest_numbers],
                },
            },
        )

    def run_agent(self, provider):
        tools = index_tools(
            concierge_tools(
                self.engine,
                GuestReferenceRecorder(self.engine, provider, "test", "classifier"),
            )
        )
        store = ConversationStore(
            self.engine,
            identifier("staff_member"),
            identifier("hotel"),
            index_agent_definitions([definition()]),
            tools,
        )
        thread = store.create(definition())
        result = asyncio.run(
            run_turn(
                store,
                provider,
                thread_id=thread,
                text="Find Dan, book pottery, show his itinerary, then cancel it.",
                request_id="journey",
                provider_name="test",
                model="test",
            )
        )
        return result

    def test_agent_completes_the_activity_journey_through_saved_tool_jobs(self):
        """The agent can discover a guest and event, reserve, read the itinerary and cancel using returned IDs."""
        provider = JourneyProvider()
        result = self.run_agent(provider)
        self.assertEqual(result.status, RunStatus.COMPLETED)
        self.assertEqual(len(provider.results), 5)
        with transaction(self.engine) as connection:
            row = activity_reservations.find_by_id(
                connection, provider.reservation_id, hotel_id=identifier("hotel")
            )
            self.assertTrue(row.cancelled)
            self.assertFalse(row.effective)
            self.assertEqual(row.revision, 2)
            self.assertEqual(
                activity_reservations.count_effective_by_activity_id(
                    connection, identifier("activity")
                ),
                0,
            )

    def test_http_retries_reuse_reservations_and_cancellations(self):
        """Repeating a command keeps the same IDs and revision, while changed input conflicts."""
        first = self.reserve()
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(self.reserve().json(), first.json())
        self.assertEqual(self.reserve((3,)).status_code, 409)
        reservation = first.json()["reservations"][0]
        self.assertEqual(reservation["agreed_price"]["amount"]["value"], 20000)
        itinerary = self.query(
            "/activity-reservations", {"guest_ids": [identifier("guest")]}
        ).json()
        self.assertEqual(itinerary["items"], [reservation])
        url = f"/activity-reservations/{reservation['id']}:cancel"
        payload = {
            "request_id": "cancel-1",
            "payload": {"expected_revision": 1, "reason": "Change of plans"},
        }
        cancelled = self.client.post(url, json=payload)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(self.client.post(url, json=payload).json(), cancelled.json())
        self.assertTrue(cancelled.json()["cancelled"])
        self.assertEqual(self.query("/activity-reservations", {}).json()["items"], [])
        self.assertEqual(
            self.query("/activity-reservations", {"effective": False}).json()["items"][
                0
            ]["id"],
            reservation["id"],
        )
        payload["request_id"] = "cancel-stale"
        self.assertEqual(self.client.post(url, json=payload).status_code, 409)

    def test_foreign_hotel_guest_rejects_the_entire_group(self):
        """A mixed-hotel request reserves no places and does not expose the other hotel's itinerary."""
        response = self.reserve((1, 2))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.query("/activity-reservations", {}).json()["items"], [])
        self.assertEqual(
            self.query(
                "/activity-reservations", {"guest_ids": [identifier("guest", 2)]}
            ).json()["items"],
            [],
        )

    def test_duplicate_reservation_tells_the_agent_which_guest_already_has_a_place(
        self,
    ):
        """A second tool command returns the guest and existing reservation IDs without creating another place."""
        existing = self.reserve().json()["reservations"][0]
        # Another guest has a place too, but their ID must stay out of this error.
        self.assertEqual(self.reserve((3,), request_id="other-guest").status_code, 201)
        provider = ScriptedProvider(
            AssistantMessage(
                tool_calls=[
                    ToolCall(
                        id="repeat",
                        name="reserve_activity_places",
                        arguments={
                            "activity_id": identifier("activity"),
                            "guest_ids": [identifier("guest")],
                        },
                    )
                ]
            ),
            AssistantMessage(text="Dan already has a place."),
        )
        self.run_agent(provider)
        result = next(
            m for m in provider.requests[-1].messages if isinstance(m, ToolMessage)
        )
        error = json.loads(result.content)["error"]
        self.assertEqual(
            error["details"]["reservations_by_guest"],
            {identifier("guest"): existing["id"]},
        )

    def test_capacity_age_and_stay_checks_reach_the_http_caller(self):
        """Rejected bookings explain the conflict and leave the itinerary unchanged."""
        table = self.metadata.tables["activities"]
        with transaction(self.engine, write=True) as connection:
            connection.execute(table.update().values(capacity=1))
        response = self.reserve((1, 3))
        self.assertEqual(response.status_code, 409)
        self.assertIn("1 places remaining", response.text)
        people = self.metadata.tables["guests"]
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                people.update().where(people.c.id == identifier("guest")).values(age=10)
            )
        response = self.reserve()
        self.assertEqual(response.status_code, 409)
        self.assertIn(identifier("guest"), response.text)
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                people.update().where(people.c.id == identifier("guest")).values(age=30)
            )
            connection.execute(
                table.update().values(min_date=NOW + 200, max_date=NOW + 300)
            )
        self.assertEqual(self.reserve().status_code, 409)
        self.assertEqual(self.query("/activity-reservations", {}).json()["items"], [])

    def test_revoked_permissions_block_reads_writes_and_replayed_commands(self):
        """Losing concierge access also removes the ability to replay an earlier successful command."""
        self.assertEqual(self.reserve().status_code, 201)
        table = self.metadata.tables["staff_members"]
        with transaction(self.engine, write=True) as connection:
            connection.execute(table.update().values(role=StaffRole.UNKNOWN.value))
        self.assertEqual(self.reserve().status_code, 403)
        self.assertEqual(self.query("/activity-reservations", {}).status_code, 403)

    def test_search_reports_capacity_and_filters_activity_dates(self):
        """Room data is unnecessary: activity search returns the dated event, price and remaining capacity."""
        response = self.query(
            "/activities",
            {
                "date_range": {
                    "min_date": to_datetime(NOW).isoformat(),
                    "max_date": to_datetime(NOW + 30).isoformat(),
                },
                "places_required": 2,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["items"][0]["id"], identifier("activity"))
        self.reserve()
        self.assertEqual(
            self.query("/activities", {"places_required": 2}).json()["items"], []
        )
