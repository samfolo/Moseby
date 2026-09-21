"""Forward pages ordered by creation time and ID, or by a saved sequence."""

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Select, Table, and_, or_

from .models.common import Row


class InvalidCursor(ValueError):
    """The cursor is malformed or belongs to another query or scope."""


class PageRequest(BaseModel):
    """Request 1–100 rows, defaulting to 50; use next_cursor for the next page."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    limit: int = Field(default=50, ge=1, le=100)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


class _BoundCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    query: str


class _Cursor(_BoundCursor):
    created_at: int = Field(ge=-(2**63), le=2**63 - 1)
    id: str = Field(min_length=1, max_length=128)


class _SequenceCursor(_BoundCursor):
    sequence: int = Field(ge=1, le=2**63 - 1)


def _query_identity(query: str, criteria: Mapping[str, str]) -> str:
    """Give the query and its filters a stable fingerprint for cursor checks."""
    encoded = json.dumps([query, dict(criteria)], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _decode[T: _BoundCursor](token: str, query: str, cursor_type: type[T]) -> T:
    """Read a cursor, raising InvalidCursor if malformed or for another query."""
    try:
        raw = base64.b64decode(
            (token + "=" * (-len(token) % 4)).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        cursor = cursor_type.model_validate_json(raw)
    except ValueError as error:
        raise InvalidCursor("Invalid pagination cursor") from error
    if cursor.query != query:
        raise InvalidCursor("Cursor belongs to a different query or scope")
    return cursor


def _encode(cursor: _BoundCursor) -> str:
    """Encode the saved position and query identity as a URL-safe token."""
    return (
        base64.urlsafe_b64encode(cursor.model_dump_json().encode()).decode().rstrip("=")
    )


def read_page[T: Row](
    connection: Connection,
    statement: Select,
    *,
    table: Table,
    row_type: type[T],
    page: PageRequest,
    query: str,
    criteria: Mapping[str, str],
) -> Page[T]:
    """Fetch a page ordered by creation time, then ID, using one SELECT.

    The supplied query must return one row per resource, including id and
    created_at. Read one extra row to decide whether to return a next_cursor.
    Raise InvalidCursor for a malformed cursor or different query/filter values.
    Each call reads current data; later pages can reflect changes between calls.
    """
    identity = _query_identity(query, criteria)
    if page.cursor is not None:
        cursor = _decode(page.cursor, identity, _Cursor)
        statement = statement.where(
            or_(
                table.c.created_at > cursor.created_at,
                and_(table.c.created_at == cursor.created_at, table.c.id > cursor.id),
            )
        )
    statement = (
        statement.order_by(None)
        .order_by(table.c.created_at, table.c.id)
        .limit(page.limit + 1)
    )
    rows = connection.execute(statement).mappings().all()
    selected = rows[: page.limit]
    next_cursor = None
    if len(rows) > page.limit:
        last = selected[-1]
        position = _Cursor(
            version=1, query=identity, created_at=last["created_at"], id=last["id"]
        )
        next_cursor = _encode(position)
    return Page[row_type](
        items=[row_type.model_validate(dict(row)) for row in selected],
        next_cursor=next_cursor,
    )


def read_sequence_page[T: Row](
    connection: Connection,
    statement: Select,
    *,
    table: Table,
    row_type: type[T],
    page: PageRequest,
    query: str,
    criteria: Mapping[str, str],
) -> Page[T]:
    """Read the next page in saved sequence order, regardless of timestamps or IDs.

    The query must select one row per sequence within its scope. A cursor belongs
    to that query and its filters; every page reapplies them. Gaps are allowed,
    and rows appended after a page was read can appear on a later page.
    """
    identity = _query_identity(query, criteria)
    if page.cursor is not None:
        cursor = _decode(page.cursor, identity, _SequenceCursor)
        statement = statement.where(table.c.sequence > cursor.sequence)
    statement = (
        statement.order_by(None).order_by(table.c.sequence).limit(page.limit + 1)
    )
    rows = connection.execute(statement).mappings().all()
    selected = rows[: page.limit]
    next_cursor = None
    if len(rows) > page.limit:
        next_cursor = _encode(
            _SequenceCursor(
                version=1, query=identity, sequence=selected[-1]["sequence"]
            )
        )
    return Page[row_type](
        items=[row_type.model_validate(dict(row)) for row in selected],
        next_cursor=next_cursor,
    )
