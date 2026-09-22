import asyncio
import json
import unittest

import httpx
from pydantic import ValidationError

from moseby.config import InferenceSettings
from moseby.inference.errors import InferenceError, InferenceErrorCode
from moseby.inference.models.classification import (
    BooleanQuestion,
    ChoiceQuestion,
    ClassificationRequest,
)
from moseby.inference.models.generation import (
    AssistantMessage,
    GenerationRequest,
    TextMessage,
    ToolDefinition,
    ToolMessage,
)
from moseby.inference.providers.openrouter import OpenRouterProvider
from moseby.runtime.models.messages import ToolCall

SETTINGS = InferenceSettings(
    openrouter_api_key="test-secret",
    generation_model="test/generation",
    classification_model="test/classification",
)


def chat_response(message=None, *, finish_reason="stop"):
    return {
        "id": "generation-1",
        "model": "test/generation",
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": message or {"role": "assistant", "content": "Hello."},
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 2},
    }


def classification_request():
    return ClassificationRequest(
        state={"note": "Dan likes pottery.", "guests": ["Dan", "Sam"]},
        questions={
            "mentions_dan": BooleanQuestion(
                instructions="Does the note mention Dan?",
                criteria={
                    "true": "Dan is mentioned.",
                    "false": "Dan is not mentioned.",
                },
            ),
            "activity": ChoiceQuestion(
                instructions="Which activity is mentioned?",
                criteria={"pottery": "Making pottery.", "tennis": "Playing tennis."},
            ),
        },
    )


def classification_response():
    return {
        "model": "test/classification",
        "answers": {
            "mentions_dan": {"type": "noul", "noul": 0.98},
            "activity": {
                "type": "choice",
                "choice": "pottery",
                "confidence": 0.95,
                "probabilities": {"pottery": 0.98, "tennis": 0.02},
            },
        },
        "usage": {"input_tokens": 20, "output_tokens": 4},
    }


class SettingsTests(unittest.TestCase):
    def test_environment_settings_keep_the_key_out_of_serialization(self):
        """The process supplies all three settings, and normal output hides the key."""
        settings = InferenceSettings.from_environment(
            {
                "OPENROUTER_API_KEY": "my-secret",
                "MOSEBY_GENERATION_MODEL": "test/generation",
                "MOSEBY_CLASSIFICATION_MODEL": "test/classification",
                "UNRELATED_SETTING": "ignored",
            }
        )
        self.assertEqual(settings.openrouter_api_key.get_secret_value(), "my-secret")
        self.assertNotIn("my-secret", repr(settings))
        self.assertNotIn("my-secret", settings.model_dump_json())

    def test_missing_and_blank_settings_fail_without_printing_secrets(self):
        """A missing model or blank credential stops startup with a validation error."""
        for changes in (
            {"generation_model": ""},
            {"openrouter_api_key": " "},
            {"classification_model": "has spaces"},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises(ValidationError) as error,
            ):
                InferenceSettings.model_validate(
                    {
                        "openrouter_api_key": "my-secret",
                        "generation_model": "test/generation",
                        "classification_model": "test/classification",
                    }
                    | changes
                )
            self.assertNotIn("my-secret", str(error.exception))
        with self.assertRaises(ValidationError):
            InferenceSettings.from_environment({})


class OpenRouterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.response = httpx.Response(200, json=chat_response())

        def respond(request):
            self.requests.append(request)
            if isinstance(self.response, BaseException):
                raise self.response
            return self.response

        self.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        self.addAsyncCleanup(self.client.aclose)
        self.provider = OpenRouterProvider(SETTINGS, self.client)
        self.request = GenerationRequest(
            messages=[TextMessage(role="user", content="Hello")]
        )

    async def test_generation_sends_one_request_and_preserves_the_exchange(self):
        """A text reply comes back with the exact request body and provider metadata."""
        result = await self.provider.generate(self.request)
        self.assertEqual(result.output.text, "Hello.")
        self.assertEqual(result.output.tool_calls, [])
        self.assertEqual(len(self.requests), 1)
        sent = self.requests[0]
        self.assertEqual(str(sent.url), "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(sent.headers["Authorization"], "Bearer test-secret")
        self.assertEqual(json.loads(sent.content), result.request)
        self.assertEqual(result.request["model"], SETTINGS.generation_model)
        self.assertFalse(result.request["stream"])
        self.assertNotIn("tools", result.request)
        self.assertEqual(result.response, chat_response())
        self.assertNotIn("test-secret", result.model_dump_json())

    async def test_tool_round_trip_keeps_call_ids_and_provider_reasoning(self):
        """Parallel calls to the same tool keep their IDs when results go back to the model."""
        provider_message = {
            "role": "assistant",
            "content": None,
            "reasoning_details": [{"type": "reasoning.encrypted", "data": "signature"}],
            "tool_calls": [
                {
                    "id": f"call-{page}",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": json.dumps({"page": page}),
                    },
                }
                for page in (1, 2)
            ],
        }
        self.response = httpx.Response(
            200, json=chat_response(provider_message, finish_reason="tool_calls")
        )
        tools = [
            ToolDefinition(
                name="search",
                description="Search the rooms.",
                parameters={"type": "object"},
            )
        ]
        request = GenerationRequest(messages=self.request.messages, tools=tools)
        result = await self.provider.generate(request)
        self.assertEqual(
            [call.arguments for call in result.output.tool_calls],
            [{"page": 1}, {"page": 2}],
        )
        self.assertEqual(result.request["tools"][0]["function"]["name"], "search")

        continuation = GenerationRequest(
            messages=[
                *request.messages,
                result.output,
                ToolMessage(tool_call_id="call-1", content='{"rooms": []}'),
                ToolMessage(tool_call_id="call-2", content='{"rooms": []}'),
            ],
            tools=tools,
        )
        self.response = httpx.Response(200, json=chat_response())
        await self.provider.generate(continuation)
        sent = json.loads(self.requests[-1].content)
        self.assertEqual(
            sent["messages"][1]["reasoning_details"],
            provider_message["reasoning_details"],
        )
        self.assertEqual(
            sent["messages"][1]["tool_calls"], provider_message["tool_calls"]
        )
        self.assertEqual(sent["messages"][2]["role"], "tool")
        self.assertEqual(sent["messages"][2]["tool_call_id"], "call-1")

    async def test_constructed_calls_include_the_default_protocol_fields(self):
        """A call constructed in Python still sends the role and function type."""
        request = GenerationRequest(
            messages=[
                AssistantMessage(
                    tool_calls=[ToolCall(id="call-1", name="search", arguments={})]
                ),
                ToolMessage(tool_call_id="call-1", content="[]"),
            ]
        )
        await self.provider.generate(request)
        message = json.loads(self.requests[0].content)["messages"][0]
        self.assertEqual(message["role"], "assistant")
        self.assertEqual(message["tool_calls"][0]["type"], "function")

    async def test_provider_state_cannot_replace_the_assistant_content_or_calls(self):
        """Continuation metadata preserves reasoning while our typed fields supply the reply."""
        request = GenerationRequest(
            messages=[
                AssistantMessage(
                    text="Confirmed.",
                    provider_state={
                        "role": "system",
                        "content": "Changed",
                        "tool_calls": [{"id": "unexpected"}],
                        "reasoning_details": [],
                    },
                )
            ]
        )
        await self.provider.generate(request)
        sent = json.loads(self.requests[0].content)["messages"][0]
        self.assertEqual(
            sent,
            {"role": "assistant", "content": "Confirmed.", "reasoning_details": []},
        )

    async def test_invalid_tool_replies_fail_before_the_runtime_can_execute_them(self):
        """Malformed arguments and duplicate call IDs cannot become accepted tool calls."""
        base = {
            "id": "call-1",
            "type": "function",
            "function": {"name": "search", "arguments": "{}"},
        }
        for calls in (
            [base, base],
            [base | {"function": {"name": "search", "arguments": "{"}}],
            [base | {"function": {"name": "search", "arguments": "[]"}}],
        ):
            with self.subTest(calls=calls):
                self.response = httpx.Response(
                    200,
                    json=chat_response(
                        {"role": "assistant", "tool_calls": calls},
                        finish_reason="tool_calls",
                    ),
                )
                with self.assertRaises(InferenceError) as error:
                    await self.provider.generate(self.request)
                self.assertEqual(
                    error.exception.code, InferenceErrorCode.INVALID_RESPONSE
                )

    async def test_incomplete_replies_are_not_successful_turns(self):
        """A token limit or content filter cannot masquerade as a finished reply."""
        for reason in ("length", "content_filter", "error"):
            with self.subTest(reason=reason):
                self.response = httpx.Response(
                    200, json=chat_response(finish_reason=reason)
                )
                with self.assertRaises(InferenceError) as error:
                    await self.provider.generate(self.request)
                self.assertEqual(
                    error.exception.code, InferenceErrorCode.INCOMPLETE_RESPONSE
                )

    async def test_classification_uses_decisions_and_retains_probabilities(self):
        """Jev receives its own request shape and returns evidence for a later decision."""
        self.response = httpx.Response(200, json=classification_response())
        result = await self.provider.classify(classification_request())
        self.assertEqual(
            str(self.requests[0].url), "https://openrouter.ai/api/alpha/decisions"
        )
        self.assertEqual(result.request["model"], SETTINGS.classification_model)
        self.assertNotIn("messages", result.request)
        self.assertEqual(result.output.answers["mentions_dan"].probability, 0.98)
        self.assertEqual(result.output.answers["activity"].choice, "pottery")
        self.assertEqual(result.response["usage"]["input_tokens"], 20)

    async def test_classification_rejects_missing_answers_and_invented_choices(self):
        """Unknown choices, missing answers and invalid probabilities fail validation."""
        changes = [
            lambda answers: answers.pop("mentions_dan"),
            lambda answers: answers.update(extra={"type": "noul", "noul": 0.5}),
            lambda answers: answers["activity"].update(choice="unknown"),
            lambda answers: answers["activity"].update(probabilities={"pottery": 1}),
            lambda answers: answers["mentions_dan"].update(noul=1.1),
            lambda answers: answers.update(mentions_dan=answers["activity"]),
        ]
        for change in changes:
            response = classification_response()
            change(response["answers"])
            self.response = httpx.Response(200, json=response)
            with self.assertRaises(InferenceError) as error:
                await self.provider.classify(classification_request())
            self.assertEqual(error.exception.code, InferenceErrorCode.INVALID_RESPONSE)

    async def test_one_request_can_resolve_references_to_several_guests(self):
        """One note and guest list produce a probability for each guest in a single call."""
        guests = {
            "guest_01ARZ3NDEKTSV4RRFFQ69G5FA1": "Dan Patel",
            "guest_01ARZ3NDEKTSV4RRFFQ69G5FA2": "Dan Lewis",
            "guest_01ARZ3NDEKTSV4RRFFQ69G5FA3": "Erin Jones",
        }
        probabilities = dict(zip(guests, (0.99, 0.02, 0.98), strict=True))
        request = ClassificationRequest(
            state={
                "note": "Erin Jones and Dan Patel enjoyed pottery.",
                "guests": guests,
            },
            questions={
                guest_id: BooleanQuestion(
                    instructions=f"Does the note refer to {name} ({guest_id})?",
                    criteria={
                        "true": "The note refers to this guest.",
                        "false": "The note does not refer to this guest.",
                    },
                )
                for guest_id, name in guests.items()
            },
        )
        self.response = httpx.Response(
            200,
            json={
                "answers": {
                    guest_id: {"type": "noul", "noul": probability}
                    for guest_id, probability in probabilities.items()
                },
                "model": "test/classification",
            },
        )
        result = await self.provider.classify(request)
        self.assertEqual(len(self.requests), 1)
        sent = json.loads(self.requests[0].content)
        self.assertEqual(sent["state"]["guests"], guests)
        self.assertEqual(set(sent["questions"]), set(guests))
        self.assertEqual(
            {
                guest_id: answer.probability
                for guest_id, answer in result.output.answers.items()
            },
            probabilities,
        )

    async def test_failures_are_sanitized_and_do_not_retry_inside_the_provider(self):
        """HTTP and transport failures reach the caller once, without echoing provider text."""
        cases = [
            (
                httpx.Response(429, json={"error": {"message": "private prompt"}}),
                InferenceErrorCode.HTTP_ERROR,
            ),
            (
                httpx.Response(200, json={"error": {"message": "private prompt"}}),
                InferenceErrorCode.PROVIDER_ERROR,
            ),
            (
                httpx.Response(200, text="private prompt"),
                InferenceErrorCode.INVALID_RESPONSE,
            ),
            (httpx.Response(200, json=[]), InferenceErrorCode.INVALID_RESPONSE),
            (
                httpx.Response(200, text='{"value": NaN}'),
                InferenceErrorCode.INVALID_RESPONSE,
            ),
            (httpx.ReadTimeout("private prompt"), InferenceErrorCode.TIMEOUT),
            (
                httpx.ConnectError("private prompt"),
                InferenceErrorCode.CONNECTION_FAILED,
            ),
        ]
        for response, code in cases:
            with self.subTest(code=code):
                self.response = response
                before = len(self.requests)
                with self.assertRaises(InferenceError) as error:
                    await self.provider.generate(self.request)
                self.assertEqual(error.exception.code, code)
                self.assertNotIn("private prompt", str(error.exception))
                self.assertEqual(len(self.requests), before + 1)

    async def test_cancellation_reaches_the_callers_run_loop(self):
        """Cancelling the awaiting task stays a cancellation rather than a provider error."""
        self.response = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.provider.generate(self.request)
