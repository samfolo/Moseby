from enum import StrEnum


class InferenceErrorCode(StrEnum):
    INCOMPLETE_RESPONSE = "INFERENCE_ERROR_INCOMPLETE_RESPONSE"
    INVALID_RESPONSE = "INFERENCE_ERROR_INVALID_RESPONSE"
    TIMEOUT = "INFERENCE_ERROR_TIMEOUT"
    CONNECTION_FAILED = "INFERENCE_ERROR_CONNECTION_FAILED"
    HTTP_ERROR = "INFERENCE_ERROR_HTTP_ERROR"
    PROVIDER_ERROR = "INFERENCE_ERROR_PROVIDER_ERROR"


class InferenceError(Exception):
    """A failed request with a stable code and a message safe to show to the caller."""

    def __init__(
        self, code: InferenceErrorCode, message: str, *, status_code: int | None = None
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
