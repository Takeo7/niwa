"""FastAPI dependencies shared across resource routers.

``get_session`` yields a SQLAlchemy ``Session`` tied to the process-wide
``SessionLocal`` and guarantees it is closed after the request. Tests
override this dependency via ``app.dependency_overrides`` (see
``tests/conftest.py``) so they can inject an in-memory DB.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..db import SessionLocal


def get_session() -> Iterator[Session]:
    """Yield a session, closing it once the request handler returns."""

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
