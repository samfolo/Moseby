"""Small checks shared by repository mutations."""

import json

from sqlalchemy import Connection

from moseby.runtime.models.common import JsonObject

from .._transaction_state import WRITE_TRANSACTION_MARKER


def require_write_transaction(connection: Connection) -> None:
    """Require the caller's BEGIN IMMEDIATE transaction before reading mutable state."""
    if not connection.in_transaction() or not connection.info.get(
        WRITE_TRANSACTION_MARKER
    ):
        raise RuntimeError("Use transaction(engine, write=True) for repository writes")


def encode_canonical_json(value: JsonObject) -> str:
    """Return a stable JSON string, leaving the input object unchanged.

    Sort object keys for comparisons and reject non-finite numbers before a write.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
