"""Alembic environment: runs against the application's models and config."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import _set_pragmas
from app.models import Base

config = context.config

# Logging is configured by the application (app.main.configure_logging); we
# intentionally do NOT call logging.config.fileConfig() here so that running
# migrations at startup does not reset the root logger to the alembic.ini
# console handler and break the app's key=value stdout logging.


def _alembic_url() -> str:
    """SQLite URL used by Alembic, derived from the application settings."""
    settings = get_settings()
    return f"sqlite:///{settings.db_path}"


# Point Alembic at the application database and metadata.
config.set_main_option("sqlalchemy.url", _alembic_url())

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DBAPI connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode, creating an Engine and connecting."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _set_pragmas(connection.connection.driver_connection, None)
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
