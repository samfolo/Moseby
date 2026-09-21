"""Read the small shared catalogue of activity categories."""

from sqlalchemy import Connection, select

from ..models.activities import ActivityTypeCode
from ..models.activity_types import ActivityTypeRow
from ..tables import activity_types


def find_by_code(
    connection: Connection, code: ActivityTypeCode
) -> ActivityTypeRow | None:
    """Fetch the category identified by its code, or None if it is missing."""
    row = (
        connection.execute(select(activity_types).where(activity_types.c.code == code))
        .mappings()
        .one_or_none()
    )
    return ActivityTypeRow.model_validate(dict(row)) if row is not None else None


def find_all(connection: Connection) -> list[ActivityTypeRow]:
    """Fetch the complete category list ordered by code, including UNKNOWN.

    This small configuration catalogue is returned in full, without pagination
    or a result cap, so added categories are available to callers immediately.
    """
    rows = connection.execute(
        select(activity_types).order_by(activity_types.c.code)
    ).mappings()
    return [ActivityTypeRow.model_validate(dict(row)) for row in rows]
