"""Run hand-authored migrations; no application models or autogeneration."""

import os

from alembic import context

from moseby.db._transaction_state import WRITE_TRANSACTION_OPTION
from moseby.db.connection import create_database_engine

config = context.config
url = os.environ.get("MOSEBY_DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def configure(connection=None) -> None:
    context.configure(
        connection=connection,
        url=url if connection is None else None,
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"},
        transactional_ddl=True,
        render_as_batch=True,
    )
    if connection is None:
        context.execute("PRAGMA foreign_keys = ON")
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    configure()
elif (connection := config.attributes.get("connection")) is not None:
    configure(connection)
else:
    engine = create_database_engine(url)
    try:
        with engine.connect() as connection:
            connection = connection.execution_options(
                **{WRITE_TRANSACTION_OPTION: True}
            )
            configure(connection)
    finally:
        engine.dispose()
