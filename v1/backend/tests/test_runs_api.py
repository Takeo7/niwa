"""HTTP tests for ``GET /api/tasks/{id}/runs`` (PR-V1-05)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.executor.core import process_pending


PROJECT_PAYLOAD: dict[str, Any] = {
    "slug": "demo",
    "name": "Demo",
    "kind": "library",
    "local_path": "/tmp/demo",
}


def _create_project(client) -> dict[str, Any]:
    response = client.post("/api/projects", json=PROJECT_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()


def _create_task(client, title: str = "echo me") -> dict[str, Any]:
    response = client.post(
        "/api/projects/demo/tasks",
        json={"title": title},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run_executor_on_test_db(app) -> int:
    """Drain the in-memory test DB by invoking the executor against it."""

    override = app.dependency_overrides[get_session]
    generator = override()
    session: Session = next(generator)
    try:
        return process_pending(session)
    finally:
        generator.close()


def test_list_runs_for_task_empty(client) -> None:
    _create_project(client)
    task = _create_task(client)

    response = client.get(f"/api/tasks/{task['id']}/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_runs_for_task_after_echo(client, app) -> None:
    _create_project(client)
    task = _create_task(client)

    processed = _run_executor_on_test_db(app)
    assert processed == 1

    response = client.get(f"/api/tasks/{task['id']}/runs")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    run = body[0]
    assert run["task_id"] == task["id"]
    assert run["status"] == "completed"
    assert run["model"] == "echo"
    assert run["exit_code"] == 0
    assert run["outcome"] == "echo"
    assert run["artifact_root"] == ""
    assert run["finished_at"] is not None


def test_list_runs_for_task_not_found(client) -> None:
    response = client.get("/api/tasks/999999/runs")
    assert response.status_code == 404
