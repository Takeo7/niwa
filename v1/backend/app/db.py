"""SQLAlchemy engine, declarative base, and SQLite tuning.

The declarative ``Base`` is defined here so it is importable from both the app
and Alembic without creating a circular dependency with ``app.models`` (which
in turn imports ``Base`` to register each model).

SQLite only enforces FOREIGN KEY constraints when ``PRAGMA foreign_keys=ON``
is issued on every connection. We attach a ``connect`` event listener so that
CASCADE / RESTRICT behave as declared in the models.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import load_settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def _engine_url(db_path: Path) -> str:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


@event.listens_for(Engine, "connect")
def _sqlite_enable_foreign_keys(dbapi_connection, connection_record) -> None:
    """Enable FK enforcement on every SQLite connection we hand out."""

    # The listener fires for non-SQLite engines too; guard by checking the
    # driver module so we don't crash on dialects that lack ``PRAGMA``.
    module_name = type(dbapi_connection).__module__ or ""
    if "sqlite" not in module_name:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


_settings = load_settings()
engine = create_engine(
    _engine_url(_settings.db_path),
    future=True,
    echo=False,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_engine_url() -> str:
    """Return the current engine URL (used by Alembic env.py)."""

    return _engine_url(_settings.db_path)
