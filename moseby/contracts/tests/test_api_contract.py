"""Check that clients can use the schema for the implemented HTTP routes."""

import unittest

from moseby.contracts.api import app
from moseby.contracts.route_metadata import PERMISSIONS
from moseby.permissions import Permission, PermissionResolver


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = app.openapi()

    def test_every_schema_reference_resolves(self):
        """Every referenced request and response shape is included in the export."""

        def visit(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    target = self.document
                    for key in node["$ref"].removeprefix("#/").split("/"):
                        target = target[key.replace("~1", "/").replace("~0", "~")]
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(self.document)

    def test_routes_declare_permissions_and_unique_operation_ids(self):
        """Each operation tells clients which capabilities and data scope it uses."""
        ids = []
        for operations in self.document["paths"].values():
            for operation in operations.values():
                ids.append(operation["operationId"])
                self.assertIsInstance(operation["x-hotel-scoped"], bool)
                permissions = operation["x-permissions"]
                groups = permissions.get("allOf", [permissions])
                for group in groups:
                    alternatives = group["anyOf"]
                    required = Permission(alternatives[0])
                    self.assertIn(required, PERMISSIONS)
                    self.assertEqual(
                        alternatives,
                        [
                            grant.root
                            for grant in PermissionResolver.covering_grants(required)
                        ],
                    )
        self.assertEqual(len(ids), len(set(ids)))

    def test_query_operations_include_their_request_bodies(self):
        """Search clients receive a required body schema for the QUERY method."""
        for operations in self.document["paths"].values():
            if "query" in operations:
                operation = operations["query"]
                with self.subTest(operation=operation["operationId"]):
                    body = operation["requestBody"]
                    self.assertTrue(body["required"])
                    self.assertIn("$ref", body["content"]["application/json"]["schema"])
