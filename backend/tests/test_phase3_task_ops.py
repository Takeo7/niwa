"""Tests for Phase 3 task management endpoints (edit, cancel, retry, summary).

Covers:
- PATCH /api/tasks/{id}  — update title/description
- POST /api/tasks/{id}/cancel
- POST /api/tasks/{id}/retry
- GET /api/summary
"""

from __future__ import annotations

from typing import Any

import pytest

PROJECT_PAYLOAD: dict[str, Any] = {
    "slug": "demo",
    "name": "Demo",
    "kind": "library",
    "local_path": "/tmp/demo",
}


def _create_project(client, **overrides: Any) -> dict[str, Any]:
    payload = {**PROJECT_PAYLOAD, **overrides}
    resp = client.post("/api/projects", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _create_task(client, title: str = "T1") -> dict[str, Any]:
    resp = client.post("/api/projects/demo/tasks", json={"title": title})
    assert resp.status_code == 201
    return resp.json()


def _patch_task_status(client, task_id: int, new_status: str) -> None:
    """Helper: directly patch task status via GET session override.
    Uses the SQLAlchemy session from the override fixture.
    """
    from app.api.deps import get_session
    session = next(client.app.dependency_overrides[get_session]())
    from app.models import Task
    t = session.get(Task, task_id)
    assert t is not None
    t.status = new_status
    session.commit()
    session.close()


# ---------------------------------------------------------------------------
# PATCH /api/tasks/{id}
# ---------------------------------------------------------------------------


def test_update_task_title(client) -> None:
    _create_project(client)
    task = _create_task(client)

    resp = client.patch(f"/api/tasks/{task['id']}", json={"title": "Updated title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated title"


def test_update_task_description(client) -> None:
    _create_project(client)
    task = _create_task(client)

    resp = client.patch(f"/api/tasks/{task['id']}", json={"description": "New description"})
    assert resp.status_code == 200
    assert resp.json()["description"] == "New description"


def test_update_task_no_changes(client) -> None:
    _create_project(client)
    task = _create_task(client, title="Same title")

    resp = client.patch(f"/api/tasks/{task['id']}", json={"title": "Same title"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Same title"


def test_update_task_not_found(client) -> None:
    resp = client.patch("/api/tasks/9999", json={"title": "x"})
    assert resp.status_code == 404


def test_update_task_already_running(client) -> None:
    _create_project(client)
    task = _create_task(client)
    _patch_task_status(client, task["id"], "running")

    resp = client.patch(f"/api/tasks/{task['id']}", json={"title": "Nope"})
    assert resp.status_code == 409
    assert "already started" in resp.json()["detail"]


def test_update_task_done_not_allowed(client) -> None:
    _create_project(client)
    task = _create_task(client)
    _patch_task_status(client, task["id"], "done")

    resp = client.patch(f"/api/tasks/{task['id']}", json={"title": "Nope"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# POST /api/tasks/{id}/cancel
# ---------------------------------------------------------------------------


def test_cancel_queued_task(client) -> None:
    _create_project(client)
    task = _create_task(client)

    resp = client.post(f"/api/tasks/{task['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_cancel_waiting_input_task(client) -> None:
    _create_project(client)
    task = _create_task(client)
    _patch_task_status(client, task["id"], "waiting_input")

    resp = client.post(f"/api/tasks/{task['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_cancel_waiting_approval_task(client) -> None:
    _create_project(client)
    task = _create_task(client)
    _patch_task_status(client, task["id"], "waiting_approval")

    resp = client.post(f"/api/tasks/{task['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_cancel_running_task_rejected(client) -> None:
    _create_project(client)
    task = _create_task(client)
    _patch_task_status(client, task["id"], "running")

    resp = client.post(f"/api/tasks/{task['id']}/cancel")
    assert resp.status_code == 409


def test_cancel_done_task_rejected(client) -> None:
    _create_project(client)
    task = _create_task(client)
    _patch_task_status(client, task["id"], "done")

    resp = client.post(f"/api/tasks/{task['id']}/cancel")
    assert resp.status_code == 409


def test_cancel_not_found(client) -> None:
    resp = client.post("/api/tasks/9999/cancel")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/tasks/{id}/retry
# ---------------------------------------------------------------------------


def test_retry_failed_task(client) -> None:
    _create_project(client)
    task = _create_task(client)
    _patch_task_status(client, task["id"], "failed")

    resp = client.post(f"/api/tasks/{task['id']}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert resp.json()["pending_question"] is None
    assert resp.json()["completed_at"] is None


def test_retry_cancelled_task(client) -> None:
    _create_project(client)
    task = _create_task(client)
    _patch_task_status(client, task["id"], "cancelled")

    resp = client.post(f"/api/tasks/{task['id']}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_retry_queued_task_rejected(client) -> None:
    _create_project(client)
    task = _create_task(client)

    resp = client.post(f"/api/tasks/{task['id']}/retry")
    assert resp.status_code == 409


def test_retry_not_found(client) -> None:
    resp = client.post("/api/tasks/9999/retry")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/summary
# ---------------------------------------------------------------------------


def test_summary_empty(client) -> None:
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_tasks"] == 0
    assert body["queued"] == 0
    assert body["done"] == 0
    assert body["failed"] == 0


def test_summary_with_tasks(client) -> None:
    _create_project(client)
    _create_task(client, "T1")
    _create_task(client, "T2")
    _create_task(client, "T3")

    task3 = client.get("/api/projects/demo/tasks").json()[-1]
    _patch_task_status(client, task3["id"], "done")

    resp = client.get("/api/summary")
    body = resp.json()
    assert body["total_tasks"] == 3
    assert body["queued"] == 2
    assert body["done"] == 1
