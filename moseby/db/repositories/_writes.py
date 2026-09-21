"""Small checks shared by repository mutations."""

import json

from sqlalchemy import Connection, Table, select

from moseby.runtime.models.common import JsonObject

from .._transaction_state import WRITE_TRANSACTION_MARKER
from ..errors import WriteConflict


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


def require_found[T](row: T | None) -> T:
    """Reject missing and out-of-scope resources without distinguishing between them."""
    if row is None:
        raise WriteConflict("The resource is missing or inaccessible")
    return row


def check_updated_at(saved: int, expected: int, now: int) -> None:
    """Reject stale edits and give each accepted edit a distinct version timestamp."""
    if saved != expected or now <= saved:
        raise WriteConflict("The resource changed or the update timestamp is stale")


def check_revision(saved: int, expected: int) -> None:
    """A command must name the revision it intends to replace."""
    if saved != expected:
        raise WriteConflict("The resource revision changed")


def require_reason(reason: str) -> None:
    if not reason.strip():
        raise ValueError("Supply a nonempty reason")


def check_history_time(
    connection: Connection, table: Table, parent_column: str, id: str, now: int
) -> None:
    """Keep a revision timestamp at or after the preceding revision."""
    previous = connection.scalar(
        select(table.c.created_at)
        .where(table.c[parent_column] == id)
        .order_by(table.c.revision.desc())
        .limit(1)
    )
    if previous is not None and now < previous:
        raise WriteConflict("A revision cannot precede the history it changes")
