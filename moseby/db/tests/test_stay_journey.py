"""Stay and guest journeys through shared HTTP services and durable agent tools."""

import asyncio
import json
from unittest.mock import patch

from pydantic import ValidationError
from sqlalchemy import func, select

from moseby.agents.agent import index_agent_definitions
from moseby.agents.concierge import definition
from moseby.contracts.stays import GetStayRequestPayload
from moseby.db.models.party_details import NewPartyDetail
from moseby.db.repositories import party_details, room_keys
from moseby.db.tests.fixtures import NOW, identifier
from moseby.db.tests.gateway_fixtures import GatewayDatabaseTestCase
from moseby.db.tests.inference_fixtures import ScriptedProvider, tool_call, tool_result
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.domain.enums import BedType, BookingStatus, ContactPreference, StaffRole
from moseby.inference.models.generation import AssistantMessage
from moseby.permissions import Permission
from moseby.runtime.enums import RunStatus
from moseby.runtime.guest_references import GuestReferenceRecorder
from moseby.runtime.loop import run_turn
from moseby.runtime.storage import ConversationStore
from moseby.services import authority, stays
from moseby.tools.concierge import create_tools
from moseby.tools.definitions import index_tools
from moseby.tools.guests import UpdateDietaryRequirementsArguments


def dates(start=200, end=300):
    return {
        "min_date": to_datetime(NOW + start).isoformat(),
        "max_date": to_datetime(NOW + end).isoformat(),
    }


class StayJourneyTests(GatewayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("moseby.gateway.stays.now_microseconds", return_value=NOW + 1)
        self.clock = patcher.start()
        self.addCleanup(patcher.stop)
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "beds",
                id=identifier("bed"),
                room_id=identifier("room"),
                type=BedType.KING,
            )
            room = (
                connection.execute(
                    select(self.metadata.tables["rooms"]).where(
                        self.metadata.tables["rooms"].c.id == identifier("room")
                    )
                )
                .mappings()
                .one()
            )
            self.insert(
                connection,
                "rooms",
                **(dict(room) | {"id": identifier("room", 3), "label": "Garden"}),
            )
            self.insert(
                connection,
                "beds",
                id=identifier("bed", 3),
                room_id=identifier("room", 3),
                type=BedType.KING,
            )
        self.quote = self.client.get(f"/rooms/{identifier('room')}").json()["price"]
        self.payload = {
            "name": "Johnson and Kelly",
            "guests": [
                {"first_name": "Sam", "last_name": "Johnson", "age": 30},
                {"first_name": "Jennifer", "last_name": "Kelly", "age": 30},
            ],
            "rooms": [
                {
                    "room_id": identifier("room"),
                    "date_range": dates(),
                    "quoted_price": self.quote,
                }
            ],
        }

    def create(self, *, payload=None, request_id="create-1"):
        return self.client.post(
            "/bookings",
            json={"request_id": request_id, "payload": payload or self.payload},
        )

    def command(self, booking_id, action, payload, request_id=None):
        return self.client.post(
            f"/bookings/{booking_id}:{action}",
            json={"request_id": request_id or action, "payload": payload},
        )

    def test_creation_replay_guest_lookup_and_atomic_room_conflict(self):
        """Retries return the same stay; an overlapping new command creates no extra party or guests."""
        first = self.create()
        self.assertEqual(first.status_code, 201, first.text)
        stay = first.json()
        self.assertEqual(self.create().json(), stay)
        found = self.query("/bookings", {"guest_id": stay["guests"][0]["id"]})
        self.assertEqual(found.json(), stay)
        self.assertEqual(self.create(request_id="other-command").status_code, 409)
        with transaction(self.engine) as connection:
            self.assertEqual(
                connection.scalar(
                    select(func.count()).select_from(self.metadata.tables["bookings"])
                ),
                3,
            )
            self.assertEqual(
                connection.scalar(
                    select(func.count()).select_from(self.metadata.tables["guests"])
                ),
                4,
            )
        self.assertEqual(
            self.client.get(f"/bookings/{stay['booking']['id']}").json(),
            stay["booking"],
        )

    def test_add_room_preserves_existing_allocation_and_replays_once(self):
        """Adding a room extends the same booking; a duplicate request cannot add it twice."""
        stay = self.create().json()
        payload = {
            "room_id": identifier("room", 3),
            "date_range": dates(),
            "quoted_price": self.quote,
        }
        response = self.command(stay["booking"]["id"], "add-room", payload)
        self.assertEqual(response.status_code, 201, response.text)
        rooms = response.json()["booking"]["room_reservations"]
        self.assertEqual(len(rooms), 2)
        original = stay["booking"]["room_reservations"][0]
        self.assertIn(original, rooms)
        self.assertEqual(
            self.command(stay["booking"]["id"], "add-room", payload).json(),
            response.json(),
        )
        self.assertEqual(
            self.command(
                stay["booking"]["id"], "add-room", payload, "another"
            ).status_code,
            409,
        )

    def test_quote_change_foreign_room_and_insufficient_capacity_roll_back(self):
        """Changed prices and invalid room choices fail before any new stay survives."""
        payload = json.loads(json.dumps(self.payload))
        payload["rooms"][0]["quoted_price"]["amount"]["value"] += 1
        self.assertEqual(self.create(payload=payload).status_code, 409)
        payload = json.loads(json.dumps(self.payload))
        payload["rooms"][0]["room_id"] = identifier("room", 2)
        self.assertEqual(self.create(payload=payload).status_code, 422)
        payload = json.loads(json.dumps(self.payload))
        payload["guests"].append(
            {"first_name": "Third", "last_name": "Guest", "age": 25}
        )
        self.assertEqual(self.create(payload=payload).status_code, 409)
        self.assertEqual(len(self.client.get("/bookings").json()["items"]), 1)

    def test_amendment_moves_room_and_rejects_stale_or_conflicting_changes(self):
        """Room moves replace one allocation; stale revisions and conflicts leave its current room intact."""
        stay = self.create().json()
        booking_id = stay["booking"]["id"]
        old = stay["booking"]["room_reservations"][0]
        payload = {
            "room_reservation_id": old["id"],
            "expected_revision": 1,
            "room_id": identifier("room", 3),
            "date_range": dates(200, 400),
            "quoted_price": self.quote,
            "reason": "Guest requested another room",
        }
        response = self.command(booking_id, "amend", payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.command(booking_id, "amend", payload).json(), response.json()
        )
        allocations = response.json()["booking"]["room_reservations"]
        self.assertEqual(len(allocations), 2)
        self.assertTrue(
            next(row for row in allocations if row["id"] == old["id"])["cancelled"]
        )
        current = next(row for row in allocations if not row["cancelled"])
        stale = payload | {
            "room_reservation_id": current["id"],
            "expected_revision": 99,
        }
        self.assertEqual(
            self.command(booking_id, "amend", stale, "stale").status_code, 409
        )
        conflict = payload | {
            "room_reservation_id": current["id"],
            "room_id": identifier("room"),
            "date_range": dates(0, 400),
        }
        self.assertEqual(
            self.command(booking_id, "amend", conflict, "conflict").status_code, 409
        )
        unchanged = self.query("/bookings", {"booking_id": booking_id}).json()
        self.assertEqual(unchanged, response.json())

    def test_cancellation_disables_existing_key_and_cannot_be_reversed(self):
        """Cancelling a booking disables its key immediately and a second cancellation cannot create a revision."""
        booking_id = identifier("booking")
        result = self.command(
            booking_id, "cancel", {"expected_revision": 1, "reason": "Guest cancelled"}
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["booking"]["status"], BookingStatus.CANCELLED)
        self.assertEqual(
            self.command(
                booking_id,
                "cancel",
                {"expected_revision": 1, "reason": "Guest cancelled"},
            ).json(),
            result.json(),
        )
        with transaction(self.engine) as connection:
            key = room_keys.find_by_id(
                connection,
                identifier("room_key"),
                hotel_id=identifier("hotel"),
                now=NOW + 1,
            )
            self.assertFalse(key.effective)
        self.assertEqual(
            self.command(
                booking_id,
                "cancel",
                {"expected_revision": 2, "reason": "Again"},
                "again",
            ).status_code,
            409,
        )

    def test_completion_requires_checkout_time_and_is_idempotent(self):
        """Completion is allowed at checkout and repeating it returns the original outcome."""
        booking_id = identifier("booking")
        payload = {"expected_revision": 1}
        self.assertEqual(self.command(booking_id, "complete", payload).status_code, 409)
        self.clock.return_value = NOW + 100
        done = self.command(booking_id, "complete", payload)
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["booking"]["status"], BookingStatus.COMPLETED)
        self.assertEqual(
            self.command(booking_id, "complete", payload).json(), done.json()
        )

    def test_guest_update_checks_evidence_version_and_merged_contacts(self):
        """A dietary update keeps its evidence reference; retries are safe and stale edits cannot overwrite it."""
        guest = self.client.get(f"/guests/{identifier('guest')}").json()
        with transaction(self.engine, write=True) as connection:
            for number in (1, 2):
                party_details.create(
                    connection,
                    NewPartyDetail(
                        id=identifier("party_detail", number),
                        party_id=identifier("party", number),
                        text="Dan reports a peanut allergy",
                    ),
                    hotel_id=identifier("hotel", number),
                    now=NOW,
                )
        request = {
            "request_id": "diet",
            "payload": {"dietary_requirements": "Peanut allergy"},
            "update_mask": ["dietary_requirements"],
            "expected_updated_at": guest["updated_at"],
            "evidence_detail_id": identifier("party_detail"),
        }
        path = f"/guests/{guest['id']}"
        self.assertEqual(
            self.client.patch(
                path,
                json=request | {"evidence_detail_id": identifier("party_detail", 2)},
            ).status_code,
            422,
        )
        response = self.client.patch(path, json=request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["dietary_requirements"], "Peanut allergy")
        self.assertEqual(self.client.patch(path, json=request).json(), response.json())
        self.assertEqual(
            self.client.patch(path, json=request | {"request_id": "stale"}).status_code,
            409,
        )
        bad_contact = {
            "request_id": "phone",
            "payload": {"contact_preference": ContactPreference.PHONE},
            "update_mask": ["contact_preference"],
            "expected_updated_at": response.json()["updated_at"],
        }
        self.assertEqual(self.client.patch(path, json=bad_contact).status_code, 422)
        self.assertEqual(
            self.client.patch(
                path,
                json=request
                | {"request_id": "no-evidence", "evidence_detail_id": None},
            ).status_code,
            422,
        )

    def test_scoping_and_revoked_authority_apply_to_reads_writes_and_replays(self):
        """Another hotel's identifiers disclose nothing, and losing access blocks even saved responses."""
        self.assertEqual(
            self.query("/bookings", {"guest_id": identifier("guest", 2)}).status_code,
            404,
        )
        self.assertEqual(
            self.command(
                identifier("booking", 2),
                "cancel",
                {"expected_revision": 1, "reason": "Wrong hotel"},
            ).status_code,
            422,
        )
        self.assertEqual(self.create().status_code, 201)
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                self.metadata.tables["staff_members"]
                .update()
                .values(role=StaffRole.UNKNOWN)
            )
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(self.client.get("/bookings").status_code, 403)

    def test_stay_lookup_requires_guest_access_as_well_as_booking_access(self):
        """Booking access alone cannot reveal the party's guest details through a composed stay."""
        context = authority.resolve(
            self.engine,
            staff_member_id=identifier("staff_member"),
            hotel_id=identifier("hotel"),
        )
        context = context.model_copy(
            update={"permissions": (Permission("moseby.bookings:read"),)}
        )
        self.assertEqual(
            stays.get_booking(self.engine, identifier("booking"), context=context).id,
            identifier("booking"),
        )
        with self.assertRaises(PermissionError):
            stays.get(
                self.engine,
                GetStayRequestPayload(booking_id=identifier("booking")),
                context=context,
                now=NOW,
            )
        operation = self.app.openapi()["paths"]["/bookings"]["post"]
        self.assertEqual(
            {group["anyOf"][0] for group in operation["x-permissions"]["allOf"]},
            {permission.root for permission in stays.CREATE_PERMISSIONS},
        )

    def test_agent_uses_saved_results_to_create_amend_update_and_cancel(self):
        """Tool jobs compose the stay journey using IDs and versions returned by earlier calls."""
        for module in ("storage", "tool_worker", "tool_writes"):
            patcher = patch(
                f"moseby.runtime.{module}.now_microseconds", return_value=NOW + 1
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        state = {}

        def read_stay(request):
            stay = tool_result(request)
            state["booking_id"] = stay["booking"]["id"]
            return tool_call("get_stay", guest_id=stay["guests"][0]["id"])

        def amend_stay(request):
            stay = tool_result(request)
            room = stay["booking"]["room_reservations"][0]
            state["guest"] = stay["guests"][0]
            return tool_call(
                "amend_stay",
                booking_id=stay["booking"]["id"],
                room_reservation_id=room["id"],
                expected_revision=room["revision"],
                room_id=room["room_id"],
                date_range=dates(200, 400),
                quoted_price=room["nightly_price"],
                reason="An extra night",
            )

        def update_guest(request):
            tool_result(request)
            guest = state["guest"]
            return tool_call(
                "update_guest",
                guest_id=guest["id"],
                expected_updated_at=guest["updated_at"],
                changes={"preferred_name": "Samuel"},
            )

        def cancel_stay(request):
            self.assertEqual(tool_result(request)["preferred_name"], "Samuel")
            return tool_call(
                "cancel_stay",
                booking_id=state["booking_id"],
                expected_revision=1,
                reason="Guest cancelled",
            )

        def finish(request):
            self.assertEqual(
                tool_result(request)["booking"]["status"], BookingStatus.CANCELLED
            )
            return AssistantMessage(text="The stay was cancelled.")

        provider = ScriptedProvider(
            tool_call("create_stay", **self.payload),
            read_stay,
            amend_stay,
            update_guest,
            cancel_stay,
            finish,
        )
        # Guest updates require a later timestamp than creation.
        with patch(
            "moseby.runtime.tool_writes.now_microseconds",
            side_effect=range(NOW + 2, NOW + 20),
        ):
            tools = index_tools(
                create_tools(
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
                    text="Manage this stay",
                    request_id="journey",
                    provider_name="test",
                    model="test",
                )
            )
        self.assertEqual(result.status, RunStatus.COMPLETED, result.reason)
        self.assertEqual(len(provider.requests), 6)

    def test_dietary_tool_changes_only_dietary_requirements(self):
        """A dietary request keeps the guest's existing contact details and rejects extra fields."""
        for module in ("storage", "tool_worker", "tool_writes"):
            patcher = patch(
                f"moseby.runtime.{module}.now_microseconds", return_value=NOW + 3
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        guest_id = identifier("guest")
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                self.metadata.tables["guests"]
                .update()
                .where(self.metadata.tables["guests"].c.id == guest_id)
                .values(phone="+441234567890")
            )
            party_details.create(
                connection,
                NewPartyDetail(
                    id=identifier("party_detail"),
                    party_id=identifier("party"),
                    text="Dan avoids peanuts.",
                ),
                hotel_id=identifier("hotel"),
                now=NOW,
            )
        arguments = dict(
            guest_id=guest_id,
            expected_updated_at=to_datetime(NOW).isoformat(),
            dietary_requirements="Avoids peanuts",
            evidence_detail_id=identifier("party_detail"),
        )
        with self.assertRaises(ValidationError):
            UpdateDietaryRequirementsArguments.model_validate(
                arguments | {"phone": None}
            )

        def finish(request):
            result = tool_result(request)
            self.assertEqual(result["phone"], "+441234567890")
            self.assertEqual(result["dietary_requirements"], "Avoids peanuts")
            return AssistantMessage(text="Dietary requirements updated.")

        provider = ScriptedProvider(
            tool_call("update_guest_dietary_requirements", **arguments), finish
        )
        tools = index_tools(
            create_tools(
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
        result = asyncio.run(
            run_turn(
                store,
                provider,
                thread_id=store.create(definition()),
                text="Update Dan's dietary requirements",
                request_id="diet",
                provider_name="test",
                model="test",
            )
        )
        self.assertEqual(result.status, RunStatus.COMPLETED, result.reason)
