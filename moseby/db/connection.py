"""SQLite connections with explicit transactions and foreign-key enforcement."""

import sqlite3

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, Connection
from sqlalchemy.pool import ConnectionPoolEntry


def create_database_engine(url: str | URL, *, timeout: float = 5.0) -> Engine:
    engine = create_engine(url, connect_args={"timeout": timeout})
    if engine.dialect.name != "sqlite":
        engine.dispose()
        raise ValueError("Moseby's migrations currently target SQLite")

    @event.listens_for(engine, "connect")
    def configure(connection: sqlite3.Connection, _: ConnectionPoolEntry) -> None:
        # SQLAlchemy owns BEGIN, including transactional DDL and savepoints.
        connection.isolation_level = None
        with connection:
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys = ON")
            finally:
                cursor.close()

    @event.listens_for(engine, "begin")
    def begin(connection: Connection) -> None:
        immediate = connection.get_execution_options().get("moseby_write", False)
        connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

    return engine
