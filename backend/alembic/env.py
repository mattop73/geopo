"""Alembic environment — async-aware, wired to the project's Settings.

The runtime engine in ``backend/database.py`` is async (aiosqlite), but Alembic
itself is synchronous. We construct a sync ``pysqlite`` URL targeting the same
file so migrations can run via the standard CLI and during app startup.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make backend/ importable when running `alembic` from the project root.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import get_settings  # noqa: E402
from database import ASYNC_DB_URL, Base, _sync_url_for_alembic  # noqa: E402

# Import all models so they register on Base.metadata BEFORE autogenerate runs.
from models import commodity, news, polymarket, podcast  # noqa: F401,E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Use whatever runtime DB we're pointed at (SQLite locally, Supabase Postgres
# in prod). ``_sync_url_for_alembic`` swaps the async driver for the sync
# driver Alembic needs (psycopg2 / pysqlite).
config.set_main_option("sqlalchemy.url", _sync_url_for_alembic(ASYNC_DB_URL))

target_metadata = Base.metadata
IS_SQLITE = ASYNC_DB_URL.startswith("sqlite")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL without a DBAPI connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Batch mode is required for SQLite ALTER and harmless to skip on
        # Postgres (where native ALTER works).
        render_as_batch=IS_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live DBAPI connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=IS_SQLITE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
