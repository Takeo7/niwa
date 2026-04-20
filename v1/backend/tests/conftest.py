"""Shared pytest fixtures for the Niwa v1 backend.

The ``client`` fixture now owns an in-memory SQLite engine built per test and
overrides ``app.api.deps.get_session`` so the real dev DB is never touched.
``StaticPool`` keeps the same underlying in-memory connection across the
short-lived sessions opened by each request.

``git_project`` is the shared "real git repo with one commit" fixture used
by the executor tests (PR-V1-08) — the adapter now expects
``project.local_path`` to be a git repo with a clean working tree.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

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


@pytest.fixture()
def git_project(tmp_path: Path) -> Path:
    """A real git repo with a single seed commit, ready for ``prepare_task_branch``.

    The executor tests assert on ``task.branch_name`` written by the
    ``git_workspace`` module, which requires both ``.git`` and a clean
    working tree. The seed commit also gives ``git checkout -b`` a base
    so we never hit the "unborn HEAD" branch of the spec.
    """

    d = tmp_path / "project"
    d.mkdir()
    _run = lambda args: subprocess.run(  # noqa: E731 — tiny helper, one-shot
        ["git", *args],
        cwd=str(d),
        check=True,
        capture_output=True,
        text=True,
    )
    _run(["init", "-b", "main"])
    _run(["config", "user.email", "niwa@test.local"])
    _run(["config", "user.name", "Niwa Test"])
    # Some sandboxes force commit signing globally; disable it locally so
    # the seed commit doesn't need a real key.
    _run(["config", "commit.gpgsign", "false"])
    (d / "README.md").write_text("seed\n")
    _run(["add", "README.md"])
    _run(["commit", "-m", "init"])
    return d
