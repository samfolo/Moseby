import json

from pydantic import TypeAdapter

from .models.common import JsonObject

_JSON_OBJECT = TypeAdapter(JsonObject)


def _reject_constant(value: str) -> None:
    raise ValueError(f"{value} is not a JSON number")


def parse_object(value: str | bytes) -> JsonObject:
    """Read a JSON object and reject non-finite numbers accepted by Python's parser."""
    return _JSON_OBJECT.validate_python(
        json.loads(value, parse_constant=_reject_constant)
    )
