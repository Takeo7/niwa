"""Tests for Phase 8 metrics endpoint and Phase 5 task cancel/retry."""

from __future__ import annotations


PROJECT = {
    "slug": "demo",
    "name": "Demo",
    "kind": "web-deployable",
    "local_path": "/tmp/demo",
}


def test_metrics_empty(client) -> None:
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_projects"] == 0
    assert body["total_tasks"] == 0
    assert body["tasks_by_status"] == {}
    assert body["active_runs"] == 0


def test_metrics_with_projects_and_tasks(client) -> None:
    client.post("/api/projects", json=PROJECT)
    client.post("/api/projects/demo/tasks", json={"title": "T1"})
    client.post("/api/projects/demo/tasks", json={"title": "T2"})

    resp = client.get("/api/metrics")
    body = resp.json()
    assert body["total_projects"] == 1
    assert body["total_tasks"] == 2
    assert body["tasks_by_status"].get("queued", 0) == 2


def test_task_cancel_api(client) -> None:
    client.post("/api/projects", json=PROJECT)
    t = client.post("/api/projects/demo/tasks", json={"title": "Cancel me"}).json()
    task_id = t["id"]

    resp = client.post(f"/api/tasks/{task_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_task_retry_api(client) -> None:
    client.post("/api/projects", json=PROJECT)
    t = client.post("/api/projects/demo/tasks", json={"title": "Retry me"}).json()
    task_id = t["id"]

    client.post(f"/api/tasks/{task_id}/cancel")

    resp = client.post(f"/api/tasks/{task_id}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"


def test_task_cancel_404(client) -> None:
    resp = client.post("/api/tasks/9999/cancel")
    assert resp.status_code == 404


def test_task_retry_not_retryable_returns_409(client) -> None:
    client.post("/api/projects", json=PROJECT)
    t = client.post("/api/projects/demo/tasks", json={"title": "Running task"}).json()
    task_id = t["id"]

    # Task is queued, not failed — retry should 409
    resp = client.post(f"/api/tasks/{task_id}/retry")
    assert resp.status_code == 409
