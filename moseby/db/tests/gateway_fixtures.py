"""A configured HTTP gateway backed by the same database used by service tests."""

from fastapi.testclient import TestClient

from moseby.contracts.api import create_app
from moseby.db.tests.fixtures import StayDatabaseTestCase, identifier
from moseby.db.transaction import transaction
from moseby.domain.enums import StaffRole


class GatewayDatabaseTestCase(StayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with transaction(self.engine, write=True) as connection:
            self.insert(
                connection,
                "staff_members",
                id=identifier("staff_member"),
                hotel_id=identifier("hotel"),
                staff_code="CONCIERGE",
                first_name="Alex",
                last_name="Morgan",
                role=StaffRole.CONCIERGE.value,
            )
        self.app = create_app(
            engine=self.engine,
            staff_member_id=identifier("staff_member"),
            hotel_id=identifier("hotel"),
        )
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def query(self, path, payload):
        return self.client.request(
            "QUERY", path, json={"request_id": "read-1", "payload": payload}
        )
