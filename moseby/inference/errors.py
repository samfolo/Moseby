from enum import StrEnum


class InferenceErrorCode(StrEnum):
    INCOMPLETE_RESPONSE = "INFERENCE_INCOMPLETE_RESPONSE"
    INVALID_RESPONSE = "INFERENCE_INVALID_RESPONSE"
    TIMEOUT = "INFERENCE_TIMEOUT"
    CONNECTION_FAILED = "INFERENCE_CONNECTION_FAILED"
    HTTP_ERROR = "INFERENCE_HTTP_ERROR"
    PROVIDER_ERROR = "INFERENCE_PROVIDER_ERROR"


class InferenceError(Exception):
    """A failed request with a stable code and a message safe to show to the caller."""

    def __init__(
        self, code: InferenceErrorCode, message: str, *, status_code: int | None = None
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
