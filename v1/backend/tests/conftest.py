"""Shared pytest fixtures for the Niwa v1 backend."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app


@pytest.fixture()
def app():
    """The FastAPI application under test."""

    return fastapi_app


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    """A synchronous HTTP client bound to the app."""

    with TestClient(app) as test_client:
        yield test_client
