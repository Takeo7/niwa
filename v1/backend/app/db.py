"""SQLAlchemy engine and session factory.

The schema itself arrives in PR-V1-02 (the five tables). For now we only wire
the engine and a declarative base so the rest of the app (and Alembic) can
import the same metadata.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import load_settings


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def _engine_url(db_path: Path) -> str:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


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
