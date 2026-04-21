"""Unit tests for the triage planner (PR-V1-12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.adapters import AdapterEvent
from app.models import Project, Task
from app.triage import TriageDecision, TriageError, triage_task


@dataclass
class _FakeAdapter:
    events: list[AdapterEvent]
    outcome_str: str = "cli_ok"
    exit_code_int: int | None = 0

    @property
    def outcome(self) -> str | None:
        return self.outcome_str

    @property
    def exit_code(self) -> int | None:
        return self.exit_code_int

    def iter_events(self):
        yield from self.events

    def wait(self) -> int | None:
        return self.exit_code_int

    def close(self) -> None:  # pragma: no cover
        return None


def _assistant(text: str) -> AdapterEvent:
    payload: dict[str, Any] = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    return AdapterEvent(kind="assistant", payload=payload, raw_line="")


def _project() -> Project:
    return Project(
        id=1, slug="demo", name="Demo", kind="library",
        local_path="/tmp/demo", autonomy_mode="safe",
    )


def _task() -> Task:
    return Task(id=42, project_id=1, title="t", description="", status="running")


def _install(
    monkeypatch: pytest.MonkeyPatch,
    events: list[AdapterEvent],
    *,
    outcome: str = "cli_ok",
    exit_code: int | None = 0,
) -> list[str]:
    prompts: list[str] = []

    def factory(*args, **kwargs):
        prompts.append(kwargs.get("prompt", ""))
        return _FakeAdapter(events=events, outcome_str=outcome, exit_code_int=exit_code)

    monkeypatch.setattr("app.triage.ClaudeCodeAdapter", factory)
    monkeypatch.setattr("app.triage.resolve_cli_path", lambda: "/bin/true")
    return prompts


def test_decision_execute_parsed_from_json_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [_assistant(
        'Planning.\n```json\n'
        '{"decision":"execute","subtasks":[],"rationale":"single change"}\n```'
    )]
    prompts = _install(monkeypatch, events)
    decision = triage_task(_project(), _task())
    assert isinstance(decision, TriageDecision)
    assert decision.kind == "execute"
    assert decision.subtasks == []
    assert decision.rationale == "single change"
    assert prompts and "triage agent for Niwa" in prompts[0]


def test_decision_split_with_subtasks_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [_assistant(
        '```json\n{"decision":"split","subtasks":["one","two"],"rationale":"two areas"}\n```'
    )]
    _install(monkeypatch, events)
    decision = triage_task(_project(), _task())
    assert decision.kind == "split"
    assert decision.subtasks == ["one", "two"]
    assert decision.rationale == "two areas"


def test_invalid_json_raises_triage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, [_assistant("no json here, just prose")])
    with pytest.raises(TriageError):
        triage_task(_project(), _task())
