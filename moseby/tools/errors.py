"""Translate expected domain failures into useful tool results."""

from contextlib import contextmanager

from moseby.db.errors import ActivityAlreadyReserved, ClaimLost, WriteConflict
from moseby.db.pagination import InvalidCursor
from moseby.runtime.models.common import ErrorDetails

from .execution import ToolErrorCode, ToolFailure


@contextmanager
def report_errors():
    """Give the agent actionable conflicts while letting ownership loss stop the worker."""
    try:
        yield
    except ClaimLost:
        raise
    except ActivityAlreadyReserved as error:
        raise ToolFailure(
            ErrorDetails(
                code=ToolErrorCode.CONFLICT,
                message=str(error),
                details={
                    "activity_id": error.activity_id,
                    "reservations_by_guest": error.reservations_by_guest,
                },
            )
        ) from error
    except (ValueError, InvalidCursor, WriteConflict) as error:
        raise ToolFailure(
            ErrorDetails(
                code=ToolErrorCode.CONFLICT
                if isinstance(error, WriteConflict)
                else ToolErrorCode.INVALID_ARGUMENTS,
                message=str(error),
            )
        ) from error
