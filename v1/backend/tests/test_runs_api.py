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
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.executor.core import process_pending
from app.models import Run, RunEvent


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
def project_payload(git_project: Path) -> dict[str, Any]:
    """Reuse the shared ``git_project`` fixture so the executor's git
    workspace prep (PR-V1-08) finds a real repo with a clean tree."""

    return {
        "slug": "demo",
        "name": "Demo",
        "kind": "library",
        "local_path": str(git_project),
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
    # PR-V1-11a: adapter's ``cli_ok`` now flows through the verifier and
    # the run-level outcome is ``verified``.
    assert run["outcome"] == "verified"
    assert run["artifact_root"] == project_payload["local_path"]
    assert run["finished_at"] is not None


def test_list_runs_for_task_not_found(client) -> None:
    response = client.get("/api/tasks/999999/runs")
    assert response.status_code == 404


# --- SSE stream tests (PR-V1-09) ---------------------------------------------


def _parse_sse_stream(text: str) -> list[dict[str, Any]]:
    """Parse a raw SSE text blob into a list of ``{id, event, data}`` dicts.

    Ignores comment-only heartbeat frames (``: heartbeat``). ``data`` is
    JSON-decoded when present.
    """

    frames: list[dict[str, Any]] = []
    for block in text.split("\n\n"):
        block = block.strip("\n")
        if not block:
            continue
        if all(line.startswith(":") for line in block.splitlines()):
            # Heartbeat-only frame.
            continue
        frame: dict[str, Any] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            value = value.lstrip(" ")
            if key == "data":
                frame["data"] = json.loads(value)
            else:
                frame[key] = value
        if frame:
            frames.append(frame)
    return frames


def _seed_run_with_events(
    session: Session,
    *,
    status: str,
    event_count: int,
    exit_code: int | None = None,
    outcome: str | None = None,
) -> Run:
    """Insert a ``Project`` + ``Task`` + ``Run`` + N ``RunEvent`` rows."""

    from app.models import Project, Task

    project = Project(slug="sse-demo", name="SSE Demo", kind="library", local_path="/tmp/sse-demo")
    session.add(project)
    session.flush()
    task = Task(
        project_id=project.id,
        title="sse task",
        description="",
        status="done" if status == "completed" else "running",
    )
    session.add(task)
    session.flush()
    now = datetime.now(timezone.utc)
    run = Run(
        task_id=task.id,
        status=status,
        model="claude-code",
        started_at=now,
        finished_at=now if status in ("completed", "failed", "cancelled") else None,
        artifact_root="/tmp/sse-demo",
        exit_code=exit_code,
        outcome=outcome,
    )
    session.add(run)
    session.flush()
    for i in range(event_count):
        session.add(RunEvent(run_id=run.id, event_type="assistant", payload_json=json.dumps({"text": f"msg-{i}"})))
    session.commit()
    return run


def test_events_stream_returns_historical_then_eos_for_terminal_run(
    client, app
) -> None:
    override = app.dependency_overrides[get_session]
    generator = override()
    session: Session = next(generator)
    try:
        run = _seed_run_with_events(
            session,
            status="completed",
            event_count=3,
            exit_code=0,
            outcome="cli_ok",
        )
        run_id = run.id
    finally:
        generator.close()

    with client.stream("GET", f"/api/runs/{run_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(chunk for chunk in response.iter_text())

    frames = _parse_sse_stream(body)
    # 3 historical events + 1 eos.
    assert len(frames) == 4, frames
    for i, frame in enumerate(frames[:3]):
        assert frame["event"] == "assistant"
        assert frame["data"]["event_type"] == "assistant"
        assert frame["data"]["payload"] == {"text": f"msg-{i}"}
        assert "id" in frame
    eos = frames[3]
    assert eos["event"] == "eos"
    assert eos["data"] == {
        "run_id": run_id,
        "final_status": "completed",
        "exit_code": 0,
        "outcome": "cli_ok",
    }


def test_events_stream_emits_new_events_for_running_run(client, app) -> None:
    override = app.dependency_overrides[get_session]
    generator = override()
    session: Session = next(generator)
    try:
        run = _seed_run_with_events(
            session, status="running", event_count=1
        )
        run_id = run.id
    finally:
        generator.close()

    # Writer thread that appends 2 more events after a delay, then flips the
    # run to ``completed`` with a final event. Uses its own session because
    # the test's session is closed; we write through the same override so
    # the in-memory DB is shared.
    def _add(s: Session, event_type: str, payload: dict | None) -> None:
        s.add(RunEvent(
            run_id=run_id,
            event_type=event_type,
            payload_json=json.dumps(payload) if payload is not None else None,
        ))
        s.commit()

    def _writer() -> None:
        time.sleep(0.4)
        gen = override()
        s: Session = next(gen)
        try:
            _add(s, "assistant", {"text": "msg-1"})
            time.sleep(0.4)
            _add(s, "assistant", {"text": "msg-2"})
            time.sleep(0.4)
            _add(s, "completed", None)
            run_row = s.get(Run, run_id)
            assert run_row is not None
            run_row.status = "completed"
            run_row.exit_code = 0
            run_row.outcome = "cli_ok"
            run_row.finished_at = datetime.now(timezone.utc)
            s.commit()
        finally:
            gen.close()

    writer = threading.Thread(target=_writer, daemon=True)
    writer.start()
    try:
        with client.stream(
            "GET", f"/api/runs/{run_id}/events", timeout=10.0
        ) as response:
            assert response.status_code == 200
            body = "".join(chunk for chunk in response.iter_text())
    finally:
        writer.join(timeout=5)

    frames = _parse_sse_stream(body)
    # 1 initial + 2 tail + 1 completed + 1 eos = 5.
    assert len(frames) == 5, frames
    texts = [f["data"]["payload"] for f in frames[:3]]
    assert texts == [
        {"text": "msg-0"},
        {"text": "msg-1"},
        {"text": "msg-2"},
    ]
    assert frames[3]["event"] == "completed"
    assert frames[4]["event"] == "eos"
    assert frames[4]["data"]["final_status"] == "completed"
    assert frames[4]["data"]["exit_code"] == 0


def test_events_stream_404_for_missing_run(client) -> None:
    response = client.get("/api/runs/999999/events")
    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}
