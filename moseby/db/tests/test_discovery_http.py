from moseby.contracts.activities import SearchActivitiesRequestPayload
from moseby.contracts.guests import SearchGuestsRequestPayload
from moseby.db.models.guests import GuestFilters
from moseby.db.pagination import InvalidCursor, PageRequest
from moseby.db.repositories import guests as guests_repository
from moseby.db.tests.fixtures import NOW, identifier
from moseby.db.tests.gateway_fixtures import GatewayDatabaseTestCase
from moseby.db.timestamps import to_datetime
from moseby.db.transaction import transaction
from moseby.domain.enums import ActivityPriceUnit, StaffRole
from moseby.services import activities, authority, guests


class DiscoveryHttpTests(GatewayDatabaseTestCase):
    def setUp(self):
        super().setUp()
        with transaction(self.engine, write=True) as connection:
            self.add_guest(
                connection,
                3,
                first_name="Élodie",
                last_name="Martin",
                preferred_name="Ellie",
            )
            self.add_guest(connection, 4, first_name="Dan", last_name="Martin")
            self.insert(
                connection, "venues", id=identifier("venue"), name="Studio", capacity=10
            )
            for number, capacity in ((1, 1), (2, None)):
                self.insert(
                    connection,
                    "activities",
                    id=identifier("activity", number),
                    venue_id=identifier("venue"),
                    title=f"Pottery {number}",
                    type="ACTIVITY_TYPE_POTTERY",
                    description="Make a bowl",
                    min_date=NOW,
                    max_date=NOW + 100,
                    capacity=capacity,
                    min_booking_size=1,
                    max_booking_size=10,
                    minimum_age=0,
                    price_id=identifier("price"),
                    price_unit=ActivityPriceUnit.PER_GUEST.value,
                )
            # A guest from the other hotel uses the final place in the shared event.
            self.insert(
                connection,
                "activity_reservations",
                id=identifier("activity_reservation"),
                party_id=identifier("party", 2),
                guest_id=identifier("guest", 2),
                activity_id=identifier("activity"),
            )
            self.insert(
                connection,
                "activity_reservation_revisions",
                activity_reservation_id=identifier("activity_reservation"),
                revision=1,
                cancelled=0,
                price_id=identifier("price"),
                price_revision=1,
                price_unit=ActivityPriceUnit.PER_GUEST.value,
            )

    def test_name_search_combines_filters_before_pagination(self):
        """Name keywords identify guests without revealing another hotel's guests."""
        for name in ("ÉLODIE Martin", "MARTIN elodie", "ellie"):
            with self.subTest(name=name):
                response = self.query("/guests", {"name": name})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [g["id"] for g in response.json()["items"]],
                    [identifier("guest", 3)],
                )
        response = self.query(
            "/guests",
            {
                "name": "dan",
                "ids": [identifier("guest", n) for n in (1, 2, 4)],
                "party_ids": [identifier("party")],
                "booking_ids": [identifier("booking")],
            },
        )
        self.assertEqual(
            [g["id"] for g in response.json()["items"]],
            [identifier("guest"), identifier("guest", 4)],
        )
        for name in ("%", "_", "' OR 1=1 --"):
            self.assertEqual(self.query("/guests", {"name": name}).json()["items"], [])
        self.assertEqual(
            self.query("/guests", {"booking_ids": [identifier("booking", 2)]}).json()[
                "items"
            ],
            [],
        )

    def test_guest_pages_and_single_reads_preserve_scope(self):
        """Pages continue in a stable order; a changed filter cannot reuse the same cursor."""
        first = self.query("/guests", {"limit": 1}).json()
        second = self.query(
            "/guests", {"limit": 1, "cursor": first["next_cursor"]}
        ).json()
        self.assertEqual(first["items"][0]["id"], identifier("guest"))
        self.assertEqual(second["items"][0]["id"], identifier("guest", 3))
        self.assertEqual(
            self.query(
                "/guests", {"cursor": first["next_cursor"], "name": "Dan"}
            ).status_code,
            400,
        )
        self.assertEqual(len(self.client.get("/guests").json()["items"]), 3)
        self.assertEqual(
            self.client.get(f"/guests/{identifier('guest')}").status_code, 200
        )
        for number in (2, 999):
            self.assertEqual(
                self.client.get(f"/guests/{identifier('guest', number)}").status_code,
                404,
            )
        with transaction(self.engine) as connection:
            with self.assertRaises(InvalidCursor):
                guests_repository.search(
                    connection,
                    GuestFilters(),
                    hotel_id=identifier("hotel", 2),
                    page=PageRequest(cursor=first["next_cursor"]),
                )

    def test_activity_availability_counts_all_hotels_without_exposing_attendees(self):
        """A full activity stays readable, while a capacity search returns the unlimited event."""
        full = self.client.get(f"/activities/{identifier('activity')}")
        self.assertEqual(full.status_code, 200)
        body = full.json()
        self.assertEqual(body["reserved_places"], 1)
        self.assertEqual(body["price"]["amount"], {"value": 20000, "currency": "GBP"})
        self.assertNotIn("guest_ids", body)
        date_range = {
            "min_date": to_datetime(NOW).isoformat(),
            "max_date": to_datetime(NOW + 100).isoformat(),
        }
        available = self.query(
            "/activities", {"places_required": 1, "date_range": date_range}
        ).json()
        self.assertEqual(
            [a["id"] for a in available["items"]], [identifier("activity", 2)]
        )
        self.assertIsNone(available["items"][0]["capacity"])
        self.assertEqual(available["items"][0]["reserved_places"], 0)
        touching = {
            "min_date": to_datetime(NOW + 100).isoformat(),
            "max_date": to_datetime(NOW + 200).isoformat(),
        }
        self.assertEqual(
            self.query("/activities", {"date_range": touching}).json()["items"], []
        )
        self.assertEqual(len(self.client.get("/activities").json()["items"]), 2)
        self.assertEqual(
            self.client.get(f"/activities/{identifier('activity', 999)}").status_code,
            404,
        )

    def test_services_and_http_share_authority_and_shapes(self):
        """Calling a service directly still checks permissions and returns the HTTP contract."""
        context = authority.resolve(
            self.engine,
            staff_member_id=identifier("staff_member"),
            hotel_id=identifier("hotel"),
        )
        for service, path, payload, scope in (
            (
                guests,
                "/guests",
                SearchGuestsRequestPayload(),
                {"hotel_id": context.hotel_id},
            ),
            (activities, "/activities", SearchActivitiesRequestPayload(), {}),
        ):
            direct = service.search(
                self.engine, payload, permissions=context.permissions, **scope
            )
            self.assertEqual(
                self.query(path, {}).json(), direct.model_dump(mode="json")
            )
            with self.assertRaises(PermissionError):
                service.search(self.engine, payload, permissions=(), **scope)
        with transaction(self.engine, write=True) as connection:
            connection.execute(
                self.metadata.tables["staff_members"]
                .update()
                .values(role=StaffRole.UNKNOWN.value)
            )
        for path in ("/guests", "/activities"):
            self.assertEqual(self.query(path, {}).status_code, 403)
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_bad_filters_and_cursors_return_client_errors(self):
        """Invalid input is rejected before a service can turn it into a database query."""
        for path in ("/guests", "/activities"):
            self.assertEqual(self.query(path, {"cursor": "bad"}).status_code, 400)
            for cursor in ("", "x" * 2049):
                self.assertEqual(self.query(path, {"cursor": cursor}).status_code, 422)
            self.assertEqual(self.query(path, {"ids": []}).status_code, 422)
        self.assertEqual(self.query("/guests", {"name": "   "}).status_code, 422)
        self.assertEqual(
            self.query(
                "/activities", {"types": ["ACTIVITY_TYPE_POTTERY"] * 101}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.query("/activities", {"places_required": 0}).status_code, 422
        )

    def test_working_routes_have_one_handler_and_document_their_responses(self):
        """Each read resolves to its implemented handler and no longer advertises a 501 stub."""
        schema = self.app.openapi()
        for path in ("/guests", "/activities"):
            for method in ("get", "query"):
                responses = schema["paths"][path][method]["responses"]
                self.assertIn("200", responses)
                self.assertIn("403", responses)
                self.assertNotIn("501", responses)
            self.assertIn("404", schema["paths"][path + "/{id}"]["get"]["responses"])
        operation_ids = [
            route.operation_id
            for route in self.app.routes
            if getattr(route, "operation_id", None)
        ]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertFalse(
            any(
                permission.root.endswith(":write")
                for permission in authority.CONCIERGE_PERMISSIONS
            )
        )
