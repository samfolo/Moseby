"""Check runtime request boundaries and the generated public schema."""

import unittest

from pydantic import ValidationError

from moseby.contracts.api import app
from moseby.contracts.jobs import CreateJobRequest, Job
from moseby.contracts.notifications import NotificationRecipient, PublishedEventPage
from moseby.contracts.route_metadata import PERMISSIONS
from moseby.contracts.schedules import ScheduleTiming, UpdateScheduleRequest
from moseby.contracts.threads import (
    CreateIncomingThreadRecordRequest,
    SearchThreadRecordsRequest,
    SteerIncomingThreadRecordRequest,
)
from moseby.permissions import Permission, PermissionResolver


def identifier(prefix, number=1):
    return f"{prefix}_{number:026d}"


class RuntimeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = app.openapi()

    def resolve(self, reference):
        node = self.document
        for key in reference.removeprefix("#/").split("/"):
            node = node[key.replace("~1", "/").replace("~0", "~")]
        return node

    def public_fields(self, schema, seen=None):
        seen = set() if seen is None else seen
        fields = set()
        if isinstance(schema, dict):
            reference = schema.get("$ref")
            if reference and reference not in seen:
                seen.add(reference)
                fields |= self.public_fields(self.resolve(reference), seen)
            fields.update(schema.get("properties", {}))
            for value in schema.values():
                fields |= self.public_fields(value, seen)
        elif isinstance(schema, list):
            for value in schema:
                fields |= self.public_fields(value, seen)
        return fields

    def test_every_schema_reference_resolves(self):
        def visit(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    self.resolve(node["$ref"])
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(self.document)

    def test_runtime_responses_exclude_internal_request_and_claim_fields(self):
        for path, operations in self.document["paths"].items():
            for operation in operations.values():
                if not isinstance(operation, dict) or "Runtime" not in operation.get(
                    "tags", []
                ):
                    continue
                for status, response in operation["responses"].items():
                    if status.startswith("2"):
                        with self.subTest(path=path, status=status):
                            fields = self.public_fields(response)
                            self.assertFalse(
                                fields
                                & {
                                    "request_id",
                                    "token",
                                    "worker_id",
                                    "permissions_json",
                                    "request_json",
                                }
                            )

    def test_routes_declare_capabilities_ownership_and_current_authority(self):
        ids = []
        for operations in self.document["paths"].values():
            for operation in operations.values():
                if not isinstance(operation, dict) or "operationId" not in operation:
                    continue
                ids.append(operation["operationId"])
                if "Runtime" in operation.get("tags", []):
                    self.assertIn(
                        operation["x-ownership"],
                        {
                            "thread_creator",
                            "actor_and_thread_creator",
                            "notification_audience",
                            "actor",
                        },
                    )
                    self.assertTrue(operation["x-current-authority-required"])
                    alternatives = operation["x-permissions"]["anyOf"]
                    required = Permission(alternatives[0])
                    self.assertIn(required, PERMISSIONS)
                    self.assertEqual(
                        alternatives,
                        [
                            grant.root
                            for grant in PermissionResolver.covering_grants(required)
                        ],
                    )
                    self.assertIn("501", operation["responses"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_query_bodies_and_cancellation_semantics_are_exported(self):
        paths = self.document["paths"]
        for path, request_name in (
            ("/thread-records", "SearchThreadRecordsRequest"),
            ("/incoming-thread-records", "SearchIncomingThreadRecordsRequest"),
        ):
            body = paths[path]["query"]["requestBody"]
            self.assertTrue(body["required"])
            self.assertEqual(
                body["content"]["application/json"]["schema"]["$ref"],
                f"#/components/schemas/{request_name}",
            )
        for path in ("/runs/{id}:cancel", "/incoming-thread-records/{id}:cancel"):
            self.assertTrue(paths[path]["post"]["x-user-only"])
        self.assertIn("202", paths["/runs/{id}:cancel"]["post"]["responses"])
        self.assertIn(
            "200", paths["/incoming-thread-records/{id}:cancel"]["post"]["responses"]
        )
        self.assertTrue(paths["/jobs"]["post"]["x-operation-permissions-required"])

    def test_thread_queries_require_scope_and_bound_id_batches(self):
        payload = {
            "thread_id": identifier("thread"),
            "ids": [identifier("thread_record")],
        }
        SearchThreadRecordsRequest(request_id="read-1", payload=payload)
        for value in (
            {},
            payload | {"thread_id": identifier("guest")},
            payload | {"ids": []},
            payload | {"ids": [identifier("thread_record")] * 101},
        ):
            with self.subTest(payload=value), self.assertRaises(ValidationError):
                SearchThreadRecordsRequest(request_id="read-1", payload=value)
        with self.assertRaises(ValidationError):
            SteerIncomingThreadRecordRequest(request_id="steer-1", payload={})

    def test_input_creation_is_top_level_and_requires_a_thread_in_the_payload(self):
        self.assertNotIn(
            "/threads/{id}/incoming-thread-records", self.document["paths"]
        )
        operation = self.document["paths"]["/incoming-thread-records"]["post"]
        self.assertEqual(operation["operationId"], "createIncomingThreadRecord")
        request = {
            "request_id": "send-1",
            "payload": {"thread_id": identifier("thread"), "text": "Hello"},
        }
        CreateIncomingThreadRecordRequest.model_validate(request)
        for payload in (
            {"text": "Hello"},
            {"thread_id": identifier("guest"), "text": "Hello"},
        ):
            with self.assertRaises(ValidationError):
                CreateIncomingThreadRecordRequest.model_validate(
                    request | {"payload": payload}
                )

    def test_job_admission_cannot_forge_runtime_links_or_authority(self):
        payload = {"operation": "example.search", "input": {"query": "tennis"}}
        CreateJobRequest(request_id="job-1", payload=payload)
        for field, value in (
            ("actor_staff_member_id", identifier("staff_member")),
            ("run_id", identifier("run")),
            ("handler", "arbitrary.handler"),
            ("source_record_id", identifier("thread_record")),
            ("input", {"amount": float("nan")}),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CreateJobRequest(request_id="job-1", payload=payload | {field: value})

    def test_job_completion_and_tool_links_remain_consistent(self):
        job = dict(
            id=identifier("job"),
            actor_staff_member_id=identifier("staff_member"),
            operation="example.search",
            thread_id=None,
            run_id=None,
            source_record_id=None,
            tool_call_id=None,
            phase="START",
            status="JOB_STATUS_QUEUED",
            input={},
            result=None,
            error=None,
            created_at="2026-09-20T09:00:00Z",
            updated_at="2026-09-20T09:00:00Z",
            finished_at=None,
        )
        Job.model_validate(job)
        for changes in (
            {"run_id": identifier("run")},
            {"tool_call_id": "call-1"},
            {"status": "JOB_STATUS_SUCCEEDED"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Job.model_validate(job | changes)

    def test_schedule_timing_and_edits_are_complete(self):
        due = "2026-09-21T09:00:00Z"
        ScheduleTiming(due_at=due)
        ScheduleTiming(cron_expression="0 9 * * *", cron_dialect="example-parser")
        for fields in (
            {},
            {"due_at": due, "cron_expression": "0 9 * * *"},
            {"cron_expression": "0 9 * * *"},
            {"due_at": "2026-09-21T09:00:00"},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                ScheduleTiming.model_validate(fields)
        request = dict(
            request_id="edit-1",
            expected_revision=1,
            payload={"enabled": False},
            update_mask=["enabled"],
        )
        UpdateScheduleRequest.model_validate(request)
        for changes in (
            {"expected_revision": 0},
            {"update_mask": []},
            {"update_mask": ["enabled", "enabled"]},
            {"payload": {"enabled": False, "handler": "changed"}},
            {"payload": {"enabled": None}},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                UpdateScheduleRequest.model_validate(request | changes)

    def test_notifications_select_one_recipient_and_replay_in_order(self):
        NotificationRecipient(guest_id=identifier("guest"))
        for recipient in (
            {},
            {
                "guest_id": identifier("guest"),
                "staff_member_id": identifier("staff_member"),
            },
        ):
            with self.assertRaises(ValidationError):
                NotificationRecipient.model_validate(recipient)
        event = dict(
            sequence=3,
            notification_id=identifier("notification"),
            created_at="2026-09-20T09:00:00Z",
            content={"text": "The tour moved to 10am."},
        )
        PublishedEventPage(items=[event], next_sequence=4)
        PublishedEventPage(items=[], next_sequence=4)
        for page in (
            {"items": [event, event], "next_sequence": 3},
            {"items": [event], "next_sequence": 2},
            {"items": [event, event | {"sequence": 2}], "next_sequence": 3},
        ):
            with self.assertRaises(ValidationError):
                PublishedEventPage.model_validate(page)
