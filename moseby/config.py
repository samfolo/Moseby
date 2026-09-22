"""Application settings supplied by the process that starts Moseby."""

import os
from collections.abc import Mapping
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class InferenceSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    openrouter_api_key: SecretStr = Field(exclude=True, repr=False)
    generation_model: str = Field(min_length=1)
    classification_model: str = Field(min_length=1)
    reasoning_effort: Literal["low", "medium", "high"] = "low"
    max_output_tokens: int = Field(default=4096, gt=0)

    @field_validator("openrouter_api_key")
    @classmethod
    def check_api_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if not secret or any(character.isspace() for character in secret):
            raise ValueError(
                "the OpenRouter API key must be nonempty without whitespace"
            )
        return value

    @field_validator("generation_model", "classification_model")
    @classmethod
    def check_model(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("model identifiers must not contain whitespace")
        return value

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Self:
        """Read credentials, model names and generation limits when the application starts."""
        environment = os.environ if environment is None else environment
        names = {
            "openrouter_api_key": "OPENROUTER_API_KEY",
            "generation_model": "MOSEBY_GENERATION_MODEL",
            "classification_model": "MOSEBY_CLASSIFICATION_MODEL",
            "reasoning_effort": "MOSEBY_REASONING_EFFORT",
            "max_output_tokens": "MOSEBY_MAX_OUTPUT_TOKENS",
        }
        return cls.model_validate(
            {
                field: environment[name]
                for field, name in names.items()
                if name in environment
            }
        )
