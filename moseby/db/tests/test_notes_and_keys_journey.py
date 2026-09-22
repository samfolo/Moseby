"""Note retrieval and key management through HTTP and durable agent jobs."""

import asyncio
from unittest.mock import patch

from moseby.agents.agent import index_agent_definitions
from moseby.agents.concierge import definition
from moseby.db.models.party_details import GuestReferences, NewPartyDetail
from moseby.db.repositories import party_details
from moseby.db.tests.fixtures import NOW, identifier
from moseby.db.tests.gateway_fixtures import GatewayDatabaseTestCase
from moseby.db.tests.inference_fixtures import ScriptedProvider, tool_call, tool_result
from moseby.db.transaction import transaction
from moseby.domain.enums import GuestReferenceStatus, StaffRole
from moseby.inference.models.generation import AssistantMessage
from moseby.runtime.enums import RunStatus
from moseby.runtime.guest_references import GuestReferenceRecorder
from moseby.runtime.loop import run_turn
from moseby.runtime.storage import ConversationStore
from moseby.tools.concierge import create_tools
from moseby.tools.definitions import index_tools


class NotesAndKeysJourneyTests(GatewayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        for module in ("guest_support", "stays"):
            patcher = patch(
                f"moseby.gateway.{module}.now_microseconds", return_value=NOW + 2
            )
            clock = patcher.start()
            if module == "guest_support":
                self.clock = clock
            self.addCleanup(patcher.stop)
        with transaction(self.engine, write=True) as connection:
            # Each fixture hotel has one party; the second hotel's note must stay private.
            for number, hotel_number, text in (
                (1, 1, "Dan likes café pottery"),
                (2, 2, "Other hotel's private note"),
                (3, 1, "Dan asked for another key"),
            ):
                party_details.create(
                    connection,
                    NewPartyDetail(
                        id=identifier("party_detail", number),
                        party_id=identifier("party", hotel_number),
                        text=text,
                    ),
                    hotel_id=identifier("hotel", hotel_number),
                    now=NOW,
                )
            party_details.save_references(
                connection,
                identifier("party_detail"),
                GuestReferences(
                    status=GuestReferenceStatus.RESOLVED,
                    guest_ids=[identifier("guest")],
                ),
                expected_updated_at=NOW,
                hotel_id=identifier("hotel"),
                now=NOW + 1,
            )

    def issue(self, request_id="issue-1", reservation_number=1):
        return self.client.post(
            "/room-keys",
            json={
                "request_id": request_id,
                "payload": {
                    "room_reservation_id": identifier(
                        "room_reservation", reservation_number
                    ),
                    "code": "Spare",
                },
            },
        )

    def deactivate(self, key_id, request_id="deactivate-1", reason="Lost key"):
        return self.client.post(
            f"/room-keys/{key_id}:deactivate",
            json={"request_id": request_id, "payload": {"reason": reason}},
        )

    def test_notes_search_uses_keywords_references_and_hotel_scope(self):
        """Keyword search ignores case and accents; guest filters use saved references and hotel scope always applies."""
        payload = {
            "party_ids": [identifier("party"), identifier("party", 2)],
            "text": "CAFÉ POTTERY",
        }
        found = self.query("/party-details", payload)
        self.assertEqual(found.status_code, 200, found.text)
        self.assertEqual(
            [row["id"] for row in found.json()["items"]], [identifier("party_detail")]
        )
        all_notes = self.query(
            "/party-details",
            {"party_ids": [identifier("party"), identifier("party", 2)]},
        ).json()["items"]
        self.assertEqual(len(all_notes), 2)
        self.assertIn(
            GuestReferenceStatus.PENDING, {row["reference_status"] for row in all_notes}
        )
        by_guest = self.query(
            "/party-details",
            {"party_ids": [identifier("party")], "guest_ids": [identifier("guest")]},
        ).json()["items"]
        self.assertEqual(len(by_guest), 1)
        self.assertEqual(
            self.client.get(
                f"/party-details/{identifier('party_detail', 2)}"
            ).status_code,
            404,
        )

    def test_note_and_key_pages_continue_without_repeating_rows(self):
        """Both collections expose a forward cursor that stays tied to its search."""
        request = {"party_ids": [identifier("party")], "limit": 1}
        first = self.query("/party-details", request).json()
        second = self.query(
            "/party-details", request | {"cursor": first["next_cursor"]}
        ).json()
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(
            self.query(
                "/party-details",
                request | {"cursor": first["next_cursor"], "text": "pottery"},
            ).status_code,
            400,
        )
        self.assertEqual(self.issue().status_code, 201)
        first = self.client.get("/room-keys", params={"limit": 1}).json()
        second = self.client.get(
            "/room-keys", params={"limit": 1, "cursor": first["next_cursor"]}
        ).json()
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        self.assertIsNone(second["next_cursor"])

    def test_key_retries_preserve_identity_and_revocation_is_individual(self):
        """Issuing twice with one request creates one key; revoking it leaves the original key usable."""
        response = self.issue()
        self.assertEqual(response.status_code, 201, response.text)
        key = response.json()
        self.assertTrue(key["effective"])
        self.assertEqual(self.issue().json(), key)
        self.assertEqual(self.issue(reservation_number=2).status_code, 409)
        done = self.deactivate(key["id"])
        self.assertEqual(done.status_code, 200, done.text)
        self.assertFalse(done.json()["effective"])
        self.assertEqual(self.deactivate(key["id"]).json(), done.json())
        self.assertEqual(
            self.deactivate(
                key["id"], request_id="other-reason", reason="Another reason"
            ).status_code,
            409,
        )
        stay = self.query("/bookings", {"booking_id": identifier("booking")}).json()
        keys = {row["id"]: row for row in stay["room_keys"]}
        self.assertEqual(len(keys), 2)
        self.assertTrue(keys[identifier("room_key")]["effective"])
        self.assertFalse(keys[key["id"]]["effective"])

    def test_key_access_follows_dates_and_parent_cancellation(self):
        """An issued key expires with its allocation and cannot outlive a cancelled booking."""
        key = self.issue().json()
        self.clock.return_value = NOW + 100
        self.assertFalse(self.client.get(f"/room-keys/{key['id']}").json()["effective"])
        self.assertEqual(self.issue(request_id="expired").status_code, 409)
        self.clock.return_value = NOW + 2
        cancelled = self.client.post(
            f"/bookings/{identifier('booking')}:cancel",
            json={
                "request_id": "cancel-stay",
                "payload": {"expected_revision": 1, "reason": "Plans changed"},
            },
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertTrue(
            all(not row["effective"] for row in cancelled.json()["room_keys"])
        )
        self.assertEqual(self.issue(request_id="cancelled").status_code, 409)

    def test_foreign_ids_and_revoked_permissions_block_keys_and_notes(self):
        """Another hotel's keys remain hidden, and losing authority blocks retries as well as new work."""
        self.assertEqual(
            self.client.get(f"/room-keys/{identifier('room_key', 2)}").status_code, 404
        )
        self.assertEqual(self.issue(reservation_number=2).status_code, 422)
        self.assertEqual(self.deactivate(identifier("room_key", 2)).status_code, 422)
        self.assertEqual(self.issue().status_code, 201)
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                self.metadata.tables["staff_members"]
                .update()
                .values(role=StaffRole.UNKNOWN)
            )
        self.assertEqual(self.issue().status_code, 403)
        self.assertEqual(self.client.get("/room-keys").status_code, 403)
        self.assertEqual(
            self.query(
                "/party-details", {"party_ids": [identifier("party")]}
            ).status_code,
            403,
        )

    def test_agent_finds_notes_issues_a_key_and_revokes_the_returned_id(self):
        """All three tools run through persisted jobs and use results returned by earlier calls."""
        for module in ("storage", "tool_worker", "tool_writes"):
            patcher = patch(
                f"moseby.runtime.{module}.now_microseconds", return_value=NOW + 2
            )
            patcher.start()
            self.addCleanup(patcher.stop)

        def issue_key(request):
            self.assertEqual(
                tool_result(request)["items"][0]["text"], "Dan likes café pottery"
            )
            return tool_call(
                "issue_room_key",
                room_reservation_id=identifier("room_reservation"),
                code="Spare",
            )

        def deactivate_key(request):
            key = tool_result(request)
            self.assertTrue(key["effective"])
            return tool_call(
                "deactivate_room_key",
                key_id=key["id"],
                reason="Guest returned the spare",
            )

        def finish(request):
            self.assertFalse(tool_result(request)["effective"])
            return AssistantMessage(
                text="The spare key was issued and then deactivated."
            )

        provider = ScriptedProvider(
            tool_call(
                "search_party_details", party_ids=[identifier("party")], text="cafe"
            ),
            issue_key,
            deactivate_key,
            finish,
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
        thread = store.create(definition())
        result = asyncio.run(
            run_turn(
                store,
                provider,
                thread_id=thread,
                text="Read Dan's notes and manage his spare key",
                request_id="notes-and-keys",
                provider_name="test",
                model="test",
            )
        )
        self.assertEqual(result.status, RunStatus.COMPLETED, result.reason)
        self.assertEqual(len(provider.requests), 4)
