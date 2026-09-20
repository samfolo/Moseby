"""Validate recorded messages and the boundary between internal and public data."""

import json
import unittest

from pydantic import TypeAdapter, ValidationError

from moseby.contracts.runs import Run
from moseby.contracts.threads import (
    CancelIncomingThreadRecordRequest,
    ConversationRecord,
    CreateIncomingThreadRecordRequest,
    CreateThreadRequest,
    IncomingThreadRecordReceipt,
    Thread,
)
from moseby.runtime.models.incoming_thread_records import incoming_thread_record_adapter
from moseby.runtime.models.messages import AssistantMessagePayload
from moseby.runtime.models.thread_records import (
    AssistantMessageRecord,
    ClassifierDecisionRecord,
    ThreadCreatedRecord,
    ToolResultRecord,
    thread_record_adapter,
    validate_tool_result_source,
)

NOW = "2026-09-20T09:00:00Z"
LATER = "2026-09-20T09:01:00Z"


def identifier(prefix, number=1):
    return f"{prefix}_{number:026d}"


def record(kind, payload, **changes):
    return (
        dict(
            id=identifier("thread_record"),
            thread_id=identifier("thread"),
            run_id=identifier("run"),
            sequence=2,
            created_at=NOW,
            format_version=1,
            kind=f"THREAD_RECORD_KIND_{kind}",
            payload=payload,
        )
        | changes
    )


def incoming(**changes):
    return (
        dict(
            id=identifier("incoming_thread_record"),
            thread_id=identifier("thread"),
            actor_staff_member_id=identifier("staff_member"),
            sequence=1,
            kind="INCOMING_THREAD_RECORD_KIND_USER_MESSAGE",
            delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE",
            created_at=NOW,
            updated_at=NOW,
            format_version=1,
            request_id="input-1",
            payload={"text": "Please avoid morning activities"},
        )
        | changes
    )


class RuntimeModelTests(unittest.TestCase):
    def test_every_record_kind_round_trips_through_json(self):
        examples = [
            record(
                "THREAD_CREATED",
                {
                    "creator_staff_member_id": identifier("staff_member"),
                    "permissions": ["moseby:read"],
                },
                sequence=1,
                run_id=None,
            ),
            record("USER_MESSAGE", {"text": "Hello"}),
            record("ASSISTANT_MESSAGE", {"text": "I will check"}),
            record(
                "TOOL_RESULT",
                {"status": "TOOL_RESULT_STATUS_SUCCEEDED", "result": None},
                source_record_id=identifier("thread_record", 2),
                tool_call_id="call-1",
            ),
            record(
                "CLASSIFIER_DECISION",
                {
                    "inference_request_id": identifier("inference_request"),
                    "status": "CLASSIFIER_DECISION_STATUS_AMBIGUOUS",
                    "decision": {"candidates": ["tennis", "pottery"]},
                },
            ),
            record(
                "INFERENCE_REQUEST",
                {"inference_request_id": identifier("inference_request")},
            ),
            record(
                "CONTROL_EVENT", {"name": "run.waiting", "data": {"wake_at": LATER}}
            ),
        ]
        for example in examples:
            with self.subTest(kind=example["kind"]):
                parsed = thread_record_adapter.validate_json(json.dumps(example))
                self.assertEqual(
                    thread_record_adapter.validate_json(parsed.model_dump_json()),
                    parsed,
                )

    def test_unknown_kind_version_and_wrong_payload_fail(self):
        example = record("USER_MESSAGE", {"text": "Hello"})
        for changes in (
            {"kind": "USER_MESSAGE"},
            {"kind": "THREAD_RECORD_KIND_UNKNOWN"},
            {"format_version": 2},
            {"payload": {"result": "wrong shape"}},
            {"payload": {"text": "Hello", "unrecognised": True}},
            {"sequence": 1},
            {"sequence": True},
            {"created_at": "2026-09-20T09:00:00"},
            {"thread_id": identifier("guest")},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                thread_record_adapter.validate_python(example | changes)

    def test_assistant_messages_have_content_and_unique_calls(self):
        call = {"id": "call-1", "name": "search_rooms", "arguments": {}}
        for payload in (
            {},
            {"text": ""},
            {"tool_calls": [call, call]},
            {"tool_calls": [call | {"arguments": {"value": float("nan")}}]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                AssistantMessagePayload.model_validate(payload)
        self.assertEqual(
            len(
                AssistantMessagePayload.model_validate(
                    {"tool_calls": [call]}
                ).tool_calls
            ),
            1,
        )

    def test_tool_results_match_the_actual_source_call(self):
        source = AssistantMessageRecord.model_validate(
            record(
                "ASSISTANT_MESSAGE",
                {
                    "tool_calls": [
                        {"id": "call-1", "name": "search_rooms", "arguments": {}}
                    ],
                },
            )
        )
        result_data = record(
            "TOOL_RESULT",
            {"status": "TOOL_RESULT_STATUS_SUCCEEDED", "result": {"rooms": []}},
            id=identifier("thread_record", 2),
            sequence=3,
            source_record_id=source.id,
            tool_call_id="call-1",
        )
        validate_tool_result_source(
            ToolResultRecord.model_validate(result_data), source
        )
        with self.assertRaises(ValueError):
            validate_tool_result_source(
                ToolResultRecord.model_validate(result_data),
                thread_record_adapter.validate_python(
                    record("USER_MESSAGE", {"text": "Hello"})
                ),
            )
        for changes in (
            {"tool_call_id": "invented"},
            {"thread_id": identifier("thread", 2)},
            {"run_id": identifier("run", 2)},
            {"sequence": 2},
            {"source_record_id": identifier("thread_record", 3)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_tool_result_source(
                    ToolResultRecord.model_validate(result_data | changes), source
                )

    def test_result_outcomes_require_the_matching_fields(self):
        base = record(
            "TOOL_RESULT",
            {},
            id=identifier("thread_record", 2),
            sequence=3,
            source_record_id=identifier("thread_record"),
            tool_call_id="call-1",
        )
        for payload in (
            {"status": "TOOL_RESULT_STATUS_FAILED"},
            {"status": "TOOL_RESULT_STATUS_SUCCEEDED"},
            {"status": "TOOL_RESULT_STATUS_CANCELLED", "reason": ""},
            {
                "status": "TOOL_RESULT_STATUS_SUCCEEDED",
                "result": None,
                "error": {"code": "FAIL", "message": "Failed"},
            },
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                thread_record_adapter.validate_python(base | {"payload": payload})

    def test_classifier_calls_require_resolution_and_a_run(self):
        payload = dict(
            inference_request_id=identifier("inference_request"),
            status="CLASSIFIER_DECISION_STATUS_RESOLVED",
            decision={"tool": "search_rooms"},
            tool_calls=[{"id": "call-1", "name": "search_rooms", "arguments": {}}],
        )
        source = ClassifierDecisionRecord.model_validate(
            record("CLASSIFIER_DECISION", payload)
        )
        result = ToolResultRecord.model_validate(
            record(
                "TOOL_RESULT",
                {"status": "TOOL_RESULT_STATUS_SUCCEEDED", "result": []},
                id=identifier("thread_record", 2),
                sequence=3,
                source_record_id=source.id,
                tool_call_id="call-1",
            )
        )
        validate_tool_result_source(result, source)
        with self.assertRaises(ValidationError):
            ClassifierDecisionRecord.model_validate(
                record("CLASSIFIER_DECISION", payload, run_id=None)
            )
        with self.assertRaises(ValidationError):
            ClassifierDecisionRecord.model_validate(
                record(
                    "CLASSIFIER_DECISION",
                    payload | {"status": "CLASSIFIER_DECISION_STATUS_AMBIGUOUS"},
                )
            )

    def test_incoming_delivery_and_acceptance_are_separate(self):
        queued = incoming_thread_record_adapter.validate_python(incoming())
        self.assertIsNone(queued.appended_at)
        self.assertIsNone(queued.record_id)
        accepted = incoming_thread_record_adapter.validate_python(
            incoming(
                delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE",
                target_run_id=identifier("run"),
                updated_at=LATER,
                appended_at=LATER,
                record_id=identifier("thread_record"),
            )
        )
        self.assertEqual(accepted.target_run_id, identifier("run"))
        for changes in (
            {"target_run_id": identifier("run")},
            {"delivery_mode": "INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE"},
            {"appended_at": LATER},
            {"record_id": identifier("thread_record")},
            {
                "appended_at": LATER,
                "record_id": identifier("thread_record"),
                "updated_at": NOW,
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                incoming_thread_record_adapter.validate_python(incoming(**changes))

    def test_scheduled_input_uses_occurrence_identity_and_polite_delivery(self):
        scheduled = incoming(
            kind="INCOMING_THREAD_RECORD_KIND_SCHEDULED_INPUT",
            request_id=None,
            payload={
                "occurrence_id": identifier("occurrence"),
                "text": "Prepare today's briefing",
            },
        )
        self.assertIsNone(
            incoming_thread_record_adapter.validate_python(scheduled).request_id
        )
        with self.assertRaises(ValidationError):
            incoming_thread_record_adapter.validate_python(
                scheduled
                | {
                    "delivery_mode": "INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE",
                    "target_run_id": identifier("run"),
                }
            )

    def test_pending_user_input_can_be_cancelled(self):
        cancellation = dict(
            updated_at=LATER,
            cancelled_at=LATER,
            cancelled_by_staff_member_id=identifier("staff_member"),
        )
        for delivery in (
            {},
            dict(
                delivery_mode="INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE",
                target_run_id=identifier("run"),
            ),
        ):
            cancelled = incoming_thread_record_adapter.validate_python(
                incoming(**delivery, **cancellation)
            )
            receipt = IncomingThreadRecordReceipt.model_validate(
                {
                    name: getattr(cancelled, name)
                    for name in IncomingThreadRecordReceipt.model_fields
                }
            )
            self.assertIsNotNone(receipt.cancelled_at)
            self.assertIsNone(receipt.record_id)

        request = CancelIncomingThreadRecordRequest.model_validate(
            {"request_id": "withdraw-1", "payload": {}}
        )
        self.assertEqual(request.payload.model_dump(), {})
        with self.assertRaises(ValidationError):
            CancelIncomingThreadRecordRequest.model_validate(
                {
                    "request_id": "withdraw-1",
                    "payload": {
                        "cancelled_by_staff_member_id": identifier("staff_member")
                    },
                }
            )

    def test_cancellation_requires_an_actor_and_unappended_user_input(self):
        cancelled = incoming(
            updated_at=LATER,
            cancelled_at=LATER,
            cancelled_by_staff_member_id=identifier("staff_member"),
        )
        for changes in (
            {"cancelled_by_staff_member_id": None},
            {"cancelled_at": None},
            {"updated_at": NOW},
            {"cancelled_at": "2026-09-20T08:59:00Z"},
            {"record_id": identifier("thread_record"), "appended_at": LATER},
            {
                "kind": "INCOMING_THREAD_RECORD_KIND_SCHEDULED_INPUT",
                "payload": {"occurrence_id": identifier("occurrence"), "text": "Check"},
            },
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                incoming_thread_record_adapter.validate_python(cancelled | changes)

    def test_public_requests_require_idempotency_but_responses_omit_it(self):
        request = CreateIncomingThreadRecordRequest.model_validate(
            {"request_id": "request-1", "payload": {"text": "Hello"}}
        )
        self.assertEqual(request.request_id, "request-1")
        with self.assertRaises(ValidationError):
            CreateIncomingThreadRecordRequest.model_validate(
                {"payload": {"text": "Hello"}}
            )
        with self.assertRaises(ValidationError):
            CreateThreadRequest.model_validate(
                {
                    "request_id": "request-1",
                    "payload": {"permissions": ["moseby:write"]},
                }
            )
        for model in (Thread, Run, IncomingThreadRecordReceipt):
            self.assertNotIn("request_id", model.model_json_schema()["properties"])
        with self.assertRaises(ValidationError):
            TypeAdapter(ConversationRecord).validate_python(
                record("CONTROL_EVENT", {"name": "run.waiting", "data": {}})
            )

    def test_run_state_matches_completion_and_wake_fields(self):
        run = dict(
            id=identifier("run"),
            thread_id=identifier("thread"),
            status="RUN_STATUS_WAITING",
            created_at=NOW,
            updated_at=NOW,
            wake_at=LATER,
            cancel_requested_at=None,
            cancel_requested_by_staff_member_id=None,
            recovery_attempts=0,
            finished_at=None,
        )
        Run.model_validate(run)
        for changes in (
            {"status": "RUN_STATUS_RUNNING"},
            {"status": "RUN_STATUS_CANCELLED"},
            {"cancel_requested_at": NOW},
            {"recovery_attempts": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Run.model_validate(run | changes)
        Run.model_validate(
            run
            | {
                "status": "RUN_STATUS_CANCELLED",
                "wake_at": None,
                "finished_at": LATER,
                "updated_at": LATER,
            }
        )

    def test_schemas_expose_tagged_payloads_and_reject_extra_fields(self):
        schema = thread_record_adapter.json_schema()
        self.assertEqual(schema["discriminator"]["propertyName"], "kind")
        self.assertEqual(len(schema["oneOf"]), 7)
        self.assertFalse(
            ThreadCreatedRecord.model_json_schema()["additionalProperties"]
        )
        self.assertEqual(
            incoming_thread_record_adapter.json_schema()["discriminator"][
                "propertyName"
            ],
            "kind",
        )
