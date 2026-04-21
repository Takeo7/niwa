"""Unit tests for the triage module (PR-V1-12a).

The adapter is mocked with ``monkeypatch`` — no subprocess spawn, no fake
CLI extension. Each test replaces ``ClaudeCodeAdapter`` with a fake class
that yields a scripted list of ``AdapterEvent`` and exposes a matching
``outcome`` / ``exit_code`` pair.

Coverage:

1. Execute decision parsed from ```json fence``` response.
2. Split decision with subtasks parsed from ```json fence``` response.
3. Invalid JSON raises ``TriageError``.
4. Plain JSON without a fence still parses (fallback balanced-match).
"""

from __future__ import annotations

import pytest

from app.adapters.claude_code import AdapterEvent


@pytest.fixture(autouse=True)
def _fake_cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Make ``resolve_cli_path`` return a path that exists.

    Without this the module would short-circuit to ``cli_not_found`` before
    our fake adapter ever ran. We only need a non-empty path; the fake
    replaces the real subprocess entirely.
    """

    fake_cli = tmp_path / "fake-claude"
    fake_cli.write_text("#!/bin/sh\n")
    fake_cli.chmod(0o755)
    monkeypatch.setenv("NIWA_CLAUDE_CLI", str(fake_cli))


class _FakeAdapter:
    """Stand-in for ``ClaudeCodeAdapter`` with a scripted stream."""

    def __init__(
        self,
        *,
        events: list[AdapterEvent],
        outcome: str = "cli_ok",
        exit_code: int = 0,
    ) -> None:
        self._events = events
        self._outcome = outcome
        self._exit_code = exit_code
        self.close_calls = 0

    # Constructor signature parity with ClaudeCodeAdapter so the module
    # can instantiate the fake the same way.
    def __call__(self, *_args, **_kwargs) -> "_FakeAdapter":
        return self

    @property
    def outcome(self) -> str:
        return self._outcome

    @property
    def exit_code(self) -> int:
        return self._exit_code

    def iter_events(self):
        yield from self._events

    def wait(self) -> int:
        return self._exit_code

    def close(self) -> None:
        self.close_calls += 1


def _install_fake_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[AdapterEvent],
    outcome: str = "cli_ok",
    exit_code: int = 0,
) -> _FakeAdapter:
    """Patch ``app.triage.ClaudeCodeAdapter`` with a fake; return the instance."""

    fake = _FakeAdapter(events=events, outcome=outcome, exit_code=exit_code)

    def _factory(*_args, **_kwargs):
        return fake

    import app.triage as triage_mod

    monkeypatch.setattr(triage_mod, "ClaudeCodeAdapter", _factory)
    return fake


class _FakeProject:
    def __init__(self, local_path: str, kind: str = "library") -> None:
        self.local_path = local_path
        self.kind = kind


class _FakeTask:
    def __init__(self, title: str, description: str = "") -> None:
        self.title = title
        self.description = description


def _assistant_text(text: str) -> AdapterEvent:
    return AdapterEvent(
        kind="assistant",
        payload={
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]},
        },
        raw_line="",
    )


def test_decision_execute_parsed_from_json_fence(monkeypatch, tmp_path):
    from app.triage import TriageDecision, triage_task

    text = (
        "```json\n"
        '{"decision":"execute","subtasks":[],'
        '"rationale":"single change"}\n'
        "```"
    )
    fake = _install_fake_adapter(monkeypatch, events=[_assistant_text(text)])

    decision = triage_task(
        _FakeProject(str(tmp_path)), _FakeTask("add a button")
    )

    assert isinstance(decision, TriageDecision)
    assert decision.kind == "execute"
    assert decision.subtasks == []
    assert decision.rationale == "single change"
    assert decision.raw_output  # non-empty
    assert fake.close_calls == 1


def test_decision_split_with_subtasks_parsed(monkeypatch, tmp_path):
    from app.triage import triage_task

    text = (
        "here is the plan\n"
        "```json\n"
        '{"decision":"split","subtasks":["one","two"],'
        '"rationale":"two areas"}\n'
        "```"
    )
    _install_fake_adapter(monkeypatch, events=[_assistant_text(text)])

    decision = triage_task(
        _FakeProject(str(tmp_path)), _FakeTask("big refactor")
    )

    assert decision.kind == "split"
    assert decision.subtasks == ["one", "two"]
    assert decision.rationale == "two areas"


def test_invalid_json_raises_triage_error(monkeypatch, tmp_path):
    from app.triage import TriageError, triage_task

    _install_fake_adapter(
        monkeypatch, events=[_assistant_text("I refuse to answer")]
    )

    with pytest.raises(TriageError) as excinfo:
        triage_task(_FakeProject(str(tmp_path)), _FakeTask("t"))

    assert "JSON" in str(excinfo.value) or "json" in str(excinfo.value)


def test_decision_plain_json_without_fence(monkeypatch, tmp_path):
    """Fallback branch: response with no ```json fence``` but a bare object."""

    from app.triage import triage_task

    text = (
        '{"decision":"execute","subtasks":[],"rationale":"ok"}'
    )
    _install_fake_adapter(monkeypatch, events=[_assistant_text(text)])

    decision = triage_task(
        _FakeProject(str(tmp_path)), _FakeTask("tiny")
    )

    assert decision.kind == "execute"
    assert decision.subtasks == []
    assert decision.rationale == "ok"
