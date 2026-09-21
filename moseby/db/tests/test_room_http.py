from fastapi.testclient import TestClient

from moseby.contracts.api import create_app
from moseby.contracts.rooms import SearchRoomsRequestPayload
from moseby.db.models.rooms import RoomFilters
from moseby.db.tests.fixtures import identifier
from moseby.db.tests.gateway_fixtures import GatewayDatabaseTestCase
from moseby.db.transaction import transaction
from moseby.domain.enums import BedType, RoomTier, StaffRole
from moseby.services import authority, rooms


class RoomHttpTests(GatewayDatabaseTestCase):
    def search(self, payload, **kwargs):
        return self.client.request(
            "QUERY",
            "/rooms",
            json={"request_id": "search-1", "payload": payload},
            **kwargs,
        )

    def test_http_returns_the_same_result_as_the_service(self):
        """The HTTP route uses the same scoped room operation as the agent tool."""
        context = authority.resolve(
            self.engine,
            staff_member_id=identifier("staff_member"),
            hotel_id=identifier("hotel"),
        )
        direct = rooms.search(
            self.engine,
            SearchRoomsRequestPayload(),
            hotel_id=context.hotel_id,
            permissions=context.permissions,
        )
        response = self.search({})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), direct.model_dump(mode="json"))
        self.assertEqual(
            [room["id"] for room in response.json()["items"]], [identifier("room")]
        )

    def test_request_headers_and_filters_cannot_expand_the_configured_hotel(self):
        """A client cannot select another staff identity, grant itself scopes or escape hotel scope."""
        response = self.search(
            {"hotel_ids": [identifier("hotel", 2)]},
            headers={
                "X-Hotel-Id": identifier("hotel", 2),
                "X-Permissions": "moseby:read",
                "X-Staff-Member-Id": identifier("staff_member", 2),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], [])

    def test_room_lookup_matches_search_and_hides_other_hotels(self):
        """Opening a search result returns the same room; other hotels' IDs return 404."""
        room = self.search({}).json()["items"][0]
        self.assertEqual(self.client.get(f"/rooms/{room['id']}").json(), room)
        for number in (2, 999):
            self.assertEqual(
                self.client.get(f"/rooms/{identifier('room', number)}").status_code, 404
            )

    def test_permissions_are_resolved_again_for_each_request(self):
        """Changing the staff role removes access on the next request to the same app."""
        self.assertEqual(self.search({}).status_code, 200)
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                self.metadata.tables["staff_members"]
                .update()
                .values(role=StaffRole.UNKNOWN.value)
            )
        response = self.search({}, headers={"X-Permissions": "moseby:read"})
        self.assertEqual(response.status_code, 403)

    def test_cursor_and_payload_errors_have_http_statuses(self):
        """Bad paging state returns 400; malformed request fields return 422."""
        self.assertEqual(self.search({"cursor": "broken"}).status_code, 400)
        self.assertEqual(self.search({"limit": 0}).status_code, 422)
        self.assertEqual(self.search({"permissions": ["moseby:read"]}).status_code, 422)

    def test_unconfigured_gateway_fails_closed_and_documents_the_working_route(self):
        """A contract-only app cannot serve data until its trusted binding is supplied."""
        with TestClient(create_app()) as client:
            self.assertEqual(
                client.request(
                    "QUERY", "/rooms", json={"request_id": "search-1", "payload": {}}
                ).status_code,
                503,
            )
        responses = self.app.openapi()["paths"]["/rooms"]["query"]["responses"]
        self.assertIn("200", responses)
        self.assertIn("403", responses)
        self.assertNotIn("501", responses)
        with self.assertRaises(ValueError):
            create_app(engine=self.engine)

    def test_room_enum_filters_share_validation_and_normalization(self):
        """Repeated choices mean the same thing in the API and repository filter models."""
        values = {
            "tiers": [RoomTier.VIP, RoomTier.STANDARD, RoomTier.STANDARD],
            "bed_types": [BedType.KING, BedType.KING],
        }
        request = SearchRoomsRequestPayload(**values)
        filters = RoomFilters(**values)
        self.assertEqual(request.tiers, filters.tiers)
        self.assertEqual(request.bed_types, filters.bed_types)
        self.assertEqual(request.tiers, sorted(set(values["tiers"])))
        self.assertEqual(
            self.search({"tiers": [RoomTier.STANDARD] * 101}).status_code, 200
        )
        self.assertEqual(self.search({"tiers": []}).status_code, 422)
