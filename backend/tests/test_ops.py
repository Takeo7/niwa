"""Tests for Phase 6/8 ops API — kill switch + audit endpoint."""

from __future__ import annotations

from app.api.deps import get_session
from app.models import Run, Task


PROJECT = {
    "slug": "demo",
    "name": "Demo",
    "kind": "web-deployable",
    "local_path": "/tmp/demo",
}


def test_kill_switch_empty(client) -> None:
    resp = client.post("/api/ops/kill-switch")
    assert resp.status_code == 200
    body = resp.json()
    assert body["cancelled_tasks"] == 0
    assert body["queued_tasks_cancelled"] == 0


def test_kill_switch_cancels_queued_tasks(client) -> None:
    client.post("/api/projects", json=PROJECT)
    client.post("/api/projects/demo/tasks", json={"title": "T1"})
    client.post("/api/projects/demo/tasks", json={"title": "T2"})

    resp = client.post("/api/ops/kill-switch")
    body = resp.json()
    assert body["cancelled_tasks"] == 2
    assert body["queued_tasks_cancelled"] == 2

    # Tasks should now be cancelled
    tasks = client.get("/api/projects/demo/tasks").json()
    assert all(t["status"] == "cancelled" for t in tasks)


def test_kill_switch_signals_running_run_process(client, monkeypatch) -> None:
    client.post("/api/projects", json=PROJECT)
    created = client.post("/api/projects/demo/tasks", json={"title": "T1"}).json()
    db = next(client.app.dependency_overrides[get_session]())
    task = db.get(Task, created["id"])
    assert task is not None
    task.status = "running"
    run = Run(
        task_id=task.id,
        status="running",
        model="claude-code",
        artifact_root="/tmp/demo",
        pid=12345,
    )
    db.add(run)
    db.commit()

    calls: list[tuple[str, int, int]] = []
    monkeypatch.setattr("app.api.ops.os.getpgid", lambda pid: pid)
    monkeypatch.setattr(
        "app.api.ops.os.killpg",
        lambda pid, sig: calls.append(("pg", pid, sig)),
    )

    resp = client.post("/api/ops/kill-switch")
    body = resp.json()

    assert body["running_tasks_marked"] == 1
    assert body["running_processes_signalled"] == 1
    assert calls == [("pg", 12345, 15)]


def test_audit_events_empty(client) -> None:
    resp = client.get("/api/audit/events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_audit_events_after_kill_switch(client) -> None:
    client.post("/api/ops/kill-switch")
    resp = client.get("/api/audit/events")
    assert resp.status_code == 200
    events = resp.json()
    assert any(e["action"] == "ops.kill_switch" for e in events)


def test_audit_events_filter_by_action(client) -> None:
    client.post("/api/ops/kill-switch")
    resp = client.get("/api/audit/events?action=ops.kill_switch")
    events = resp.json()
    assert len(events) == 1
    assert events[0]["action"] == "ops.kill_switch"
