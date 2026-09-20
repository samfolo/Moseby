"""One connection shared by all repositories participating in an operation."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine


@contextmanager
def transaction(engine: Engine, *, write: bool = False) -> Iterator[Connection]:
    """Commit once on success; roll back the entire operation on failure."""
    with engine.connect() as connection:
        connection = connection.execution_options(moseby_write=write)
        with connection.begin():
            yield connection
