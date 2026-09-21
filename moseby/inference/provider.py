from typing import Protocol

from .models.classification import ClassificationOutput, ClassificationRequest
from .models.common import InferenceResult
from .models.generation import AssistantMessage, GenerationRequest


class InferenceProvider(Protocol):
    """The inference operations that an application can request from a provider."""

    async def generate(
        self, request: GenerationRequest
    ) -> InferenceResult[AssistantMessage]: ...

    async def classify(
        self, request: ClassificationRequest
    ) -> InferenceResult[ClassificationOutput]: ...
