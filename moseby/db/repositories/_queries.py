"""Shared query expressions and bounded identity batches."""

from collections.abc import Sequence

from sqlalchemy import Column, Table, func, select
from sqlalchemy.sql.selectable import ScalarSelect


def latest_revision(
    history: Table, parent_column: Column, parent_id: Column
) -> ScalarSelect[int]:
    """Build a query for the highest saved revision of the current parent row.

    Keep the history table inside this query while referring to the parent in
    the surrounding query. The (parent, revision) primary key supports the lookup.
    """
    return (
        select(func.max(history.c.revision))
        .where(parent_column == parent_id)
        .correlate_except(history)
        .scalar_subquery()
    )


def unique_ids[T: str](ids: Sequence[T]) -> list[T]:
    """Remove repeated IDs, keeping their first occurrence and input order.

    Accept an empty sequence. Raise ValueError for a bare string or more than
    100 input IDs, counting repeats before removing them.
    """
    if isinstance(ids, (str, bytes)) or len(ids) > 100:
        raise ValueError("Supply a sequence of at most 100 IDs")
    return list(dict.fromkeys(ids))
