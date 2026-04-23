"""HTTP tests for the projects CRUD endpoints.

The ``client`` fixture (see ``conftest.py``) overrides the ``get_session``
dependency with an in-memory SQLite engine built per test, so the dev DB at
``data/niwa-v1.sqlite3`` is never touched. ``Base.metadata.create_all``
is used instead of running Alembic because the point here is to exercise
the API, not the migrations — migrations have their own tests.
"""

from __future__ import annotations

from typing import Any


VALID_PAYLOAD: dict[str, Any] = {
    "slug": "demo",
    "name": "Demo",
    "kind": "library",
    "local_path": "/tmp/demo",
}


def test_list_projects_empty(client) -> None:
    response = client.get("/api/projects")
    assert response.status_code == 200
    assert response.json() == []


def test_create_project_happy(client) -> None:
    response = client.post("/api/projects", json=VALID_PAYLOAD)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["slug"] == "demo"
    assert body["name"] == "Demo"
    assert body["kind"] == "library"
    assert body["local_path"] == "/tmp/demo"
    assert body["autonomy_mode"] == "safe"
    assert body["git_remote"] is None
    assert body["deploy_port"] is None
    assert isinstance(body["id"], int)
    assert body["created_at"]
    assert body["updated_at"]


def test_create_project_duplicate_slug(client) -> None:
    first = client.post("/api/projects", json=VALID_PAYLOAD)
    assert first.status_code == 201
    second = client.post("/api/projects", json=VALID_PAYLOAD)
    assert second.status_code == 409
    assert "slug" in second.json()["detail"].lower()


def test_create_project_invalid_slug(client) -> None:
    # Uppercase letters are not allowed by the slug regex.
    bad_upper = {**VALID_PAYLOAD, "slug": "Demo-Project"}
    assert client.post("/api/projects", json=bad_upper).status_code == 422

    # Whitespace is not allowed either.
    bad_space = {**VALID_PAYLOAD, "slug": "demo project"}
    assert client.post("/api/projects", json=bad_space).status_code == 422


def test_create_project_invalid_kind(client) -> None:
    bad = {**VALID_PAYLOAD, "kind": "desktop"}
    response = client.post("/api/projects", json=bad)
    assert response.status_code == 422


def test_get_project_by_slug(client) -> None:
    client.post("/api/projects", json=VALID_PAYLOAD)
    ok = client.get("/api/projects/demo")
    assert ok.status_code == 200
    assert ok.json()["slug"] == "demo"

    missing = client.get("/api/projects/does-not-exist")
    assert missing.status_code == 404


def test_patch_project(client) -> None:
    created = client.post("/api/projects", json=VALID_PAYLOAD).json()
    original_updated_at = created["updated_at"]

    response = client.patch(
        "/api/projects/demo",
        json={"autonomy_mode": "dangerous"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["autonomy_mode"] == "dangerous"
    # Untouched fields keep their previous value.
    assert body["name"] == "Demo"
    assert body["kind"] == "library"
    assert body["local_path"] == "/tmp/demo"
    # ``updated_at`` must move forward (or at least not regress) on write.
    assert body["updated_at"] >= original_updated_at


def test_patch_project_slug_rejected(client) -> None:
    client.post("/api/projects", json=VALID_PAYLOAD)
    response = client.patch("/api/projects/demo", json={"slug": "renamed"})
    assert response.status_code == 422


def test_delete_project(client) -> None:
    client.post("/api/projects", json=VALID_PAYLOAD)
    response = client.delete("/api/projects/demo")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/projects/demo").status_code == 404


def test_delete_project_not_found(client) -> None:
    response = client.delete("/api/projects/nope")
    assert response.status_code == 404


def test_list_projects_returns_created(client) -> None:
    first = {**VALID_PAYLOAD, "slug": "alpha", "name": "Alpha"}
    second = {**VALID_PAYLOAD, "slug": "bravo", "name": "Bravo"}
    assert client.post("/api/projects", json=first).status_code == 201
    assert client.post("/api/projects", json=second).status_code == 201

    response = client.get("/api/projects")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    # Sorted by created_at ascending → insertion order.
    assert [p["slug"] for p in body] == ["alpha", "bravo"]
