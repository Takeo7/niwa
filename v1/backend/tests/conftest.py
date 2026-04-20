"""Shared pytest fixtures for the Niwa v1 backend.

The ``client`` fixture now owns an in-memory SQLite engine built per test and
overrides ``app.api.deps.get_session`` so the real dev DB is never touched.
``StaticPool`` keeps the same underlying in-memory connection across the
short-lived sessions opened by each request.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_session
from app.db import Base
from app.main import app as fastapi_app


@pytest.fixture()
def app():
    """The FastAPI application under test."""

    return fastapi_app


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    """A synchronous HTTP client bound to ``app`` with an isolated DB.

    Each test gets a fresh in-memory SQLite database, so side effects never
    leak across tests and the dev DB in ``v1/data/niwa-v1.sqlite3`` stays
    untouched.
    """

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    def override_get_session() -> Iterator[Session]:
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()
