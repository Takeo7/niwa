"""Unit tests for the triage planner (PR-V1-12).

The triage module wraps ``ClaudeCodeAdapter`` with a dedicated prompt and
parses the JSON decision out of the stream. These tests stub the adapter
with a minimal fake that yields pre-baked ``AdapterEvent`` objects so the
subprocess layer is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.adapters import AdapterEvent
from app.models import Project, Task
from app.triage import TriageDecision, TriageError, triage_task


@dataclass
class _FakeAdapter:
    """Minimal stand-in for ``ClaudeCodeAdapter`` driven by canned events."""

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
        for ev in self.events:
            yield ev

    def wait(self) -> int | None:
        return self.exit_code_int

    def close(self) -> None:  # pragma: no cover - noop
        return None


def _assistant(text: str) -> AdapterEvent:
    payload: dict[str, Any] = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    return AdapterEvent(kind="assistant", payload=payload, raw_line="")


def _result(text: str) -> AdapterEvent:
    payload: dict[str, Any] = {"type": "result", "result": text}
    return AdapterEvent(kind="result", payload=payload, raw_line="")


def _project() -> Project:
    return Project(
        id=1,
        slug="demo",
        name="Demo",
        kind="library",
        local_path="/tmp/demo",
        autonomy_mode="safe",
    )


def _task(title: str = "refactor core") -> Task:
    return Task(
        id=42,
        project_id=1,
        title=title,
        description="",
        status="running",
    )


def _install_fake_adapter(
    monkeypatch: pytest.MonkeyPatch, events: list[AdapterEvent]
) -> list[str]:
    """Patch ``ClaudeCodeAdapter`` in the triage module; capture the prompt."""

    captured_prompts: list[str] = []

    def factory(*args, **kwargs):
        captured_prompts.append(kwargs.get("prompt", ""))
        return _FakeAdapter(events=events)

    monkeypatch.setattr("app.triage.ClaudeCodeAdapter", factory)
    # The CLI path resolver should be bypassed — any truthy string keeps
    # the real class happy in prod, and the factory ignores it anyway.
    monkeypatch.setattr("app.triage.resolve_cli_path", lambda: "/bin/true")
    return captured_prompts


# ---------------------------------------------------------------------------
# Happy-path parsing
# ---------------------------------------------------------------------------


def test_decision_execute_parsed_from_json_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        _assistant(
            'Planning complete.\n```json\n'
            '{"decision":"execute","subtasks":[],"rationale":"single change"}\n'
            "```"
        ),
        _result("done"),
    ]
    prompts = _install_fake_adapter(monkeypatch, events)

    decision = triage_task(_project(), _task())

    assert isinstance(decision, TriageDecision)
    assert decision.kind == "execute"
    assert decision.subtasks == []
    assert decision.rationale == "single change"
    assert prompts and "triage agent for Niwa" in prompts[0]


def test_decision_split_with_subtasks_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        _assistant(
            '```json\n'
            '{"decision":"split","subtasks":["one","two"],"rationale":"two areas"}\n'
            '```'
        ),
    ]
    _install_fake_adapter(monkeypatch, events)

    decision = triage_task(_project(), _task())

    assert decision.kind == "split"
    assert decision.subtasks == ["one", "two"]
    assert decision.rationale == "two areas"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_invalid_json_raises_triage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [_assistant("no json here, just prose")]
    _install_fake_adapter(monkeypatch, events)

    with pytest.raises(TriageError):
        triage_task(_project(), _task())


def test_missing_cli_raises_triage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``outcome != cli_ok`` from the adapter must surface as ``TriageError``."""

    def factory(*args, **kwargs):
        return _FakeAdapter(events=[], outcome_str="cli_not_found", exit_code_int=None)

    monkeypatch.setattr("app.triage.ClaudeCodeAdapter", factory)
    monkeypatch.setattr("app.triage.resolve_cli_path", lambda: None)

    with pytest.raises(TriageError):
        triage_task(_project(), _task())


def test_shape_invalid_raises_triage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Execute decision with non-empty subtasks list is an invalid shape."""

    events = [
        _assistant(
            '```json\n'
            '{"decision":"execute","subtasks":["leaked"],"rationale":"bad"}\n'
            '```'
        ),
    ]
    _install_fake_adapter(monkeypatch, events)

    with pytest.raises(TriageError):
        triage_task(_project(), _task())
