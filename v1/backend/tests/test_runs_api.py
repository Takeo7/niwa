"""HTTP tests for ``GET /api/tasks/{id}/runs`` (PR-V1-05 + PR-V1-07).

The executor swap from echo (PR-V1-05) to the Claude adapter (PR-V1-07)
means ``local_path`` now has to be an existing directory — the adapter
spawns a subprocess with ``cwd=project.local_path``. The fake CLI below
plus a ``tmp_path``-backed project directory keep this HTTP test
hermetic: no network, no real ``claude`` binary.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.executor.core import process_pending


FAKE_CLI_PATH = (
    Path(__file__).parent / "fixtures" / "fake_claude_cli.py"
).resolve()


@pytest.fixture(autouse=True)
def _fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire every test in this module to the fake CLI by default."""

    st = os.stat(FAKE_CLI_PATH)
    os.chmod(FAKE_CLI_PATH, st.st_mode | 0o111)

    script = tmp_path / "api_script.jsonl"
    script.write_text(json.dumps({"type": "result", "exit_code": 0}) + "\n")

    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(FAKE_CLI_PATH))
    monkeypatch.setenv("FAKE_CLAUDE_SCRIPT", str(script))
    monkeypatch.setenv("FAKE_CLAUDE_EXIT", "0")


@pytest.fixture()
def project_payload(tmp_path: Path) -> dict[str, Any]:
    local = tmp_path / "demo_project"
    local.mkdir()
    return {
        "slug": "demo",
        "name": "Demo",
        "kind": "library",
        "local_path": str(local),
    }


def _create_project(client, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/projects", json=payload)
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


def test_list_runs_for_task_empty(client, project_payload) -> None:
    _create_project(client, project_payload)
    task = _create_task(client)

    response = client.get(f"/api/tasks/{task['id']}/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_runs_for_task_after_echo(client, app, project_payload) -> None:
    _create_project(client, project_payload)
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
    assert run["model"] == "claude-code"
    assert run["exit_code"] == 0
    assert run["outcome"] == "cli_ok"
    assert run["artifact_root"] == project_payload["local_path"]
    assert run["finished_at"] is not None


def test_list_runs_for_task_not_found(client) -> None:
    response = client.get("/api/tasks/999999/runs")
    assert response.status_code == 404
