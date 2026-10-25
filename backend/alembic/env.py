"""Alembic environment: sync psycopg engine (D17), metadata from app.db.models."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

import app.db.models  # noqa: F401  (registers every table on Base.metadata)
from app.db.base import Base
from app.db.session import create_sync_engine, database_url

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL instead of running it: `alembic upgrade head --sql`."""
    context.configure(
        url=database_url().render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Tests pass an open connection to a throwaway database.
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return

    engine = create_sync_engine()
    try:
        with engine.connect() as connection:
            do_run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
