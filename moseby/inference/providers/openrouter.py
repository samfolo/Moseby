import httpx

from moseby.config import InferenceSettings

from .._json import parse_object
from ..errors import InferenceError, InferenceErrorCode
from ..models.classification import ClassificationOutput, ClassificationRequest
from ..models.common import InferenceResult, JsonObject
from ..models.generation import AssistantMessage, GenerationRequest
from .endpoints import OPENROUTER_CHAT_COMPLETIONS_URL, OPENROUTER_DECISIONS_URL
from .openrouter_models import (
    chat_body,
    decisions_body,
    read_chat_response,
    read_decisions_response,
)

_TIMEOUT = httpx.Timeout(60, connect=10)


class OpenRouterProvider:
    """Make individual inference requests using the application's shared HTTP client."""

    def __init__(self, settings: InferenceSettings, client: httpx.AsyncClient):
        self._settings = settings
        self._client = client

    async def generate(
        self, request: GenerationRequest
    ) -> InferenceResult[AssistantMessage]:
        """Return a complete assistant reply, including any requested tool calls."""
        body = chat_body(request, self._settings.generation_model)
        response = await self._post(OPENROUTER_CHAT_COMPLETIONS_URL, body)
        try:
            output = read_chat_response(response)
        except ValueError:
            raise InferenceError(
                InferenceErrorCode.INVALID_RESPONSE,
                "OpenRouter returned an invalid assistant reply.",
            ) from None
        return InferenceResult(
            output=output,
            request=body,
            response=response,
            total_tokens=_total_tokens(response),
        )

    async def classify(
        self, request: ClassificationRequest
    ) -> InferenceResult[ClassificationOutput]:
        """Return answers for the supplied questions and preserve their probabilities."""
        body = decisions_body(request, self._settings.classification_model)
        response = await self._post(OPENROUTER_DECISIONS_URL, body)
        try:
            output = read_decisions_response(response)
            output.check_questions(request)
        except ValueError:
            raise InferenceError(
                InferenceErrorCode.INVALID_RESPONSE,
                "OpenRouter returned invalid classification answers.",
            ) from None
        return InferenceResult(
            output=output,
            request=body,
            response=response,
            total_tokens=_total_tokens(response),
        )

    async def _post(self, url: str, body: JsonObject) -> JsonObject:
        """Send one request and translate transport failures into safe, stable errors."""
        try:
            response = await self._client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._settings.openrouter_api_key.get_secret_value()}"
                },
                timeout=_TIMEOUT,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise InferenceError(
                InferenceErrorCode.TIMEOUT, "OpenRouter did not respond in time."
            ) from None
        except httpx.RequestError:
            raise InferenceError(
                InferenceErrorCode.CONNECTION_FAILED, "The OpenRouter request failed."
            ) from None

        # Provider error bodies may echo prompts. Keep those out of exception messages.
        if not response.is_success:
            raise InferenceError(
                InferenceErrorCode.HTTP_ERROR,
                f"OpenRouter returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        try:
            payload = parse_object(response.content)
        except ValueError:
            raise InferenceError(
                InferenceErrorCode.INVALID_RESPONSE, "OpenRouter returned invalid JSON."
            ) from None
        if "error" in payload:
            raise InferenceError(
                InferenceErrorCode.PROVIDER_ERROR,
                "OpenRouter could not complete the request.",
            )
        return payload


def _total_tokens(response: JsonObject) -> int | None:
    """Read reported usage without treating an absent or malformed count as zero."""
    usage = response.get("usage")
    total = usage.get("total_tokens") if isinstance(usage, dict) else None
    return total if type(total) is int and total >= 0 else None
