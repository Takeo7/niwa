"""HTTP tests for the tasks CRUD endpoints (PR-V1-04).

Each test reuses the ``client`` fixture from ``conftest.py`` — an in-memory
SQLite engine is built per test, so side effects never leak. A project is
seeded per-test via ``_create_project`` because tasks need a parent.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app.api.deps import get_session


PROJECT_PAYLOAD: dict[str, Any] = {
    "slug": "demo",
    "name": "Demo",
    "kind": "library",
    "local_path": "/tmp/demo",
}


def _create_project(client, **overrides: Any) -> dict[str, Any]:
    """Seed a project via the API and return its body."""

    payload = {**PROJECT_PAYLOAD, **overrides}
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_list_tasks_empty(client) -> None:
    _create_project(client)
    response = client.get("/api/projects/demo/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_create_task_happy(client) -> None:
    _create_project(client)
    response = client.post(
        "/api/projects/demo/tasks",
        json={"title": "write the readme"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "write the readme"
    assert body["status"] == "queued"
    assert body["parent_task_id"] is None
    assert body["branch_name"] is None
    assert body["pr_url"] is None
    assert body["pending_question"] is None
    assert body["completed_at"] is None
    assert body["created_at"]
    assert body["updated_at"]
    assert isinstance(body["id"], int)
    assert isinstance(body["project_id"], int)


def test_create_task_project_not_found(client) -> None:
    response = client.post(
        "/api/projects/ghost/tasks",
        json={"title": "nothing here"},
    )
    assert response.status_code == 404


def test_create_task_missing_title(client) -> None:
    _create_project(client)
    response = client.post("/api/projects/demo/tasks", json={})
    assert response.status_code == 422


def test_create_task_title_too_long(client) -> None:
    _create_project(client)
    long_title = "x" * 201
    response = client.post(
        "/api/projects/demo/tasks",
        json={"title": long_title},
    )
    assert response.status_code == 422


def _fetch_task_events(app, task_id: int) -> list[dict[str, Any]]:
    """Return every ``task_events`` row for ``task_id`` via the test session.

    The conftest fixture overrides ``get_session`` with a generator bound to
    the per-test engine; calling it directly gives us a session on that same
    in-memory DB.
    """

    override = app.dependency_overrides[get_session]
    generator = override()
    session = next(generator)
    try:
        rows = session.execute(
            text(
                "SELECT kind, message, payload_json "
                "FROM task_events WHERE task_id = :tid ORDER BY id ASC"
            ),
            {"tid": task_id},
        ).all()
    finally:
        generator.close()
    return [
        {"kind": r[0], "message": r[1], "payload_json": r[2]}
        for r in rows
    ]


def test_create_task_writes_events(client, app) -> None:
    _create_project(client)
    created = client.post(
        "/api/projects/demo/tasks",
        json={"title": "hello world"},
    ).json()

    events = _fetch_task_events(app, created["id"])
    assert len(events) == 2
    assert events[0]["kind"] == "created"
    assert events[0]["message"] == "hello world"
    assert events[1]["kind"] == "status_changed"
    payload = json.loads(events[1]["payload_json"])
    assert payload == {"from": None, "to": "queued"}


def test_get_task_happy(client) -> None:
    _create_project(client)
    created = client.post(
        "/api/projects/demo/tasks",
        json={"title": "fetch me"},
    ).json()
    response = client.get(f"/api/tasks/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    assert response.json()["title"] == "fetch me"


def test_get_task_not_found(client) -> None:
    response = client.get("/api/tasks/999999")
    assert response.status_code == 404


def test_list_tasks_order(client) -> None:
    _create_project(client)
    first = client.post(
        "/api/projects/demo/tasks",
        json={"title": "first"},
    ).json()
    second = client.post(
        "/api/projects/demo/tasks",
        json={"title": "second"},
    ).json()

    response = client.get("/api/projects/demo/tasks")
    assert response.status_code == 200
    body = response.json()
    assert [t["id"] for t in body] == [first["id"], second["id"]]
    assert [t["title"] for t in body] == ["first", "second"]


def test_delete_task_queued(client) -> None:
    _create_project(client)
    created = client.post(
        "/api/projects/demo/tasks",
        json={"title": "bye"},
    ).json()
    response = client.delete(f"/api/tasks/{created['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/api/tasks/{created['id']}").status_code == 404


def _force_status(app, task_id: int, new_status: str) -> None:
    """Mutate ``tasks.status`` directly — the executor is not in this PR."""

    override = app.dependency_overrides[get_session]
    generator = override()
    session = next(generator)
    try:
        session.execute(
            text("UPDATE tasks SET status = :s WHERE id = :tid"),
            {"s": new_status, "tid": task_id},
        )
        session.commit()
    finally:
        generator.close()


def test_delete_task_running_conflict(client, app) -> None:
    _create_project(client)
    created = client.post(
        "/api/projects/demo/tasks",
        json={"title": "busy"},
    ).json()
    _force_status(app, created["id"], "running")

    response = client.delete(f"/api/tasks/{created['id']}")
    assert response.status_code == 409
    assert "cancel" in response.json()["detail"].lower()


def test_delete_task_cascades_events(client, app) -> None:
    _create_project(client)
    created = client.post(
        "/api/projects/demo/tasks",
        json={"title": "with-events"},
    ).json()
    assert len(_fetch_task_events(app, created["id"])) == 2

    assert client.delete(f"/api/tasks/{created['id']}").status_code == 204
    assert _fetch_task_events(app, created["id"]) == []


def _force_waiting_input(app, task_id: int, question: str) -> None:
    """Mark a seeded task as ``waiting_input`` with a pending question."""

    override = app.dependency_overrides[get_session]
    generator = override()
    session = next(generator)
    try:
        session.execute(
            text(
                "UPDATE tasks SET status = :s, pending_question = :q "
                "WHERE id = :tid"
            ),
            {"s": "waiting_input", "q": question, "tid": task_id},
        )
        session.commit()
    finally:
        generator.close()


def test_respond_transitions_waiting_input_to_queued(client, app) -> None:
    """Happy path: POST /respond clears pending_question and requeues."""

    _create_project(client)
    created = client.post(
        "/api/projects/demo/tasks",
        json={"title": "need answer"},
    ).json()
    _force_waiting_input(app, created["id"], "ok?")

    response = client.post(
        f"/api/tasks/{created['id']}/respond",
        json={"response": "yes"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["pending_question"] is None

    events = _fetch_task_events(app, created["id"])
    kinds = [e["kind"] for e in events]
    # created + status_changed (null→queued) are the first two from creation.
    assert kinds[-2:] == ["message", "status_changed"]
    message_payload = json.loads(events[-2]["payload_json"])
    assert message_payload == {"event": "user_response", "text": "yes"}
    last_transition = json.loads(events[-1]["payload_json"])
    assert last_transition == {"from": "waiting_input", "to": "queued"}


def test_respond_returns_409_if_not_waiting_input(client, app) -> None:
    """A task not in ``waiting_input`` rejects the response with 409."""

    _create_project(client)
    created = client.post(
        "/api/projects/demo/tasks",
        json={"title": "already done"},
    ).json()
    _force_status(app, created["id"], "done")

    response = client.post(
        f"/api/tasks/{created['id']}/respond",
        json={"response": "too late"},
    )
    assert response.status_code == 409
    assert "waiting" in response.json()["detail"].lower()
    # State untouched: still done, no new events appended.
    events_after = _fetch_task_events(app, created["id"])
    assert [e["kind"] for e in events_after] == ["created", "status_changed"]


def test_respond_404_on_missing_task(client) -> None:
    response = client.post(
        "/api/tasks/9999/respond",
        json={"response": "hello"},
    )
    assert response.status_code == 404
