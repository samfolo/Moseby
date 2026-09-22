"""Transaction and error handling shared by HTTP commands."""

from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import Engine

from moseby.db.errors import ActivityAlreadyReserved, WriteConflict
from moseby.db.transaction import transaction


@contextmanager
def write_command(engine: Engine, *, now: int):
    """Commit the command together or translate a rejected change into an HTTP error."""
    try:
        with transaction(engine, write=True) as connection:
            yield connection, now
    except ActivityAlreadyReserved as error:
        raise HTTPException(
            409,
            {
                "message": str(error),
                "activity_id": error.activity_id,
                "reservations_by_guest": error.reservations_by_guest,
            },
        ) from error
    except WriteConflict as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
