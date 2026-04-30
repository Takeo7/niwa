"""Tests for Phase 6/8 ops API — kill switch + audit endpoint."""

from __future__ import annotations


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
