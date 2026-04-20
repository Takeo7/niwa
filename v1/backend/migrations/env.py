"""Alembic environment for Niwa v1.

``render_as_batch=True`` is required because SQLite does not support ALTER
TABLE for most schema changes; Alembic's batch mode rewrites the table in a
copy-and-rename pattern. Keep it on even though no migrations exist yet.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import get_engine_url
from app.models import Base  # noqa: F401 — import side effect registers tables

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tests and scripts can override the engine URL without touching the real
# config by invoking ``alembic -x db_url=sqlite:///...``. When no ``-x db_url``
# is given we fall back to the URL derived from the app settings, so regular
# CLI usage keeps working.
_x_args = context.get_x_argument(as_dictionary=True)
_override_url = _x_args.get("db_url")
config.set_main_option(
    "sqlalchemy.url", _override_url if _override_url else get_engine_url()
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
