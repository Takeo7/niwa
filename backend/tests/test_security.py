"""Tests for Phase 6 security — secret redaction, audit log."""

from __future__ import annotations

import json

import pytest

from app.adapters import AdapterEvent
from app.executor.core import _write_event
from app.models import Project, Run, RunEvent, Task
from app.security.redaction import redact
from app.services.audit import list_events, log_event


# ── Secret redaction ──────────────────────────────────────────────────────────


def test_redact_github_token() -> None:
    text = "GITHUB_TOKEN=ghp_abcdefghij1234567890ABCDEF"
    result = redact(text)
    assert "ghp_" not in result
    assert "[REDACTED]" in result


def test_redact_anthropic_key() -> None:
    text = "key=sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
    result = redact(text)
    assert "sk-ant" not in result
    assert "[REDACTED]" in result


def test_redact_niwa_token() -> None:
    text = "auth: niwa_aabbccdd1122334455667788990011aabbccdd"
    result = redact(text)
    assert "niwa_" not in result
    assert "[REDACTED]" in result


def test_redact_url_with_credentials() -> None:
    text = "url=https://user:secretpass@github.com/org/repo.git"
    result = redact(text)
    assert "secretpass" not in result
    assert "https://[REDACTED]@" in result


def test_redact_bearer_header() -> None:
    text = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsImtpZCI6IjFiYjk2MDBh"
    result = redact(text)
    assert "eyJhbGciO" not in result
    assert "[REDACTED]" in result


def test_redact_does_not_touch_normal_text() -> None:
    text = "INFO: task 42 started in /tmp/project"
    result = redact(text)
    assert result == text


def test_redact_preserves_key_name_in_key_value() -> None:
    text = "token=ghp_abc123def456ghi789jkl012"
    result = redact(text)
    assert "[REDACTED]" in result
    assert "token" in result.lower()


def test_run_event_payloads_are_redacted_before_persisting(client) -> None:
    from app.api.deps import get_session

    db = next(client.app.dependency_overrides[get_session]())
    project = Project(
        slug="demo",
        name="Demo",
        kind="library",
        local_path="/tmp/demo",
    )
    db.add(project)
    db.commit()
    task = Task(project_id=project.id, title="t", description="")
    db.add(task)
    db.commit()
    run = Run(task_id=task.id, status="running", model="claude-code", artifact_root="/tmp/demo")
    db.add(run)
    db.commit()

    _write_event(
        db,
        run,
        AdapterEvent(
            kind="assistant",
            payload={"text": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz12345"},
            raw_line="{}",
        ),
    )

    event = db.query(RunEvent).filter(RunEvent.run_id == run.id).one()
    payload = json.loads(event.payload_json or "{}")
    assert "abcdefghijklmnopqrstuvwxyz" not in payload["text"]
    assert "[REDACTED]" in payload["text"]


# ── Audit log ─────────────────────────────────────────────────────────────────


def test_log_event_and_query(client) -> None:
    from app.api.deps import get_session
    db = next(client.app.dependency_overrides[get_session]())

    e = log_event(
        db,
        actor_type="human",
        action="login",
        ip_address="127.0.0.1",
    )
    assert e.id is not None
    assert e.action == "login"


def test_list_events_filters_by_action(client) -> None:
    from app.api.deps import get_session
    db = next(client.app.dependency_overrides[get_session]())

    log_event(db, actor_type="token", action="task.create", target_type="task", target_id=1)
    log_event(db, actor_type="token", action="task.cancel", target_type="task", target_id=1)

    creates = list_events(db, action="task.create")
    assert all(e.action == "task.create" for e in creates)
    assert len(creates) == 1


def test_list_events_pagination(client) -> None:
    from app.api.deps import get_session
    db = next(client.app.dependency_overrides[get_session]())

    for i in range(5):
        log_event(db, actor_type="executor", action=f"action_{i}")

    page1 = list_events(db, limit=3, offset=0)
    page2 = list_events(db, limit=3, offset=3)
    assert len(page1) == 3
    assert len(page2) == 2
