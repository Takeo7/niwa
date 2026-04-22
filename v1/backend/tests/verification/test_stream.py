"""E2 — stream termination analyzer unit tests (PR-V1-11a, PR-V1-21).

Feeds ``check_stream_termination`` the ordered payload dicts a run would
produce and asserts which ``error_code`` (if any) it returns. The
synthetic lifecycle frames the executor writes
(``started``/``completed``/``failed``/``error``) must be ignored — only
the real Claude stream drives the decision.

PR-V1-21 reshapes the semantics: the analyzer now walks back to the
last ``assistant`` event instead of trusting the last semantic frame,
because the real Claude CLI always emits a trailing ``result``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.verification.stream import check_stream_termination


_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _assistant(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }


def test_stream_terminated_with_result_success_passes() -> None:
    events = [
        {"type": "started"},  # lifecycle, ignored
        _assistant("doing work"),
        {"type": "result", "subtype": "success"},
    ]
    assert check_stream_termination(events) == (None, None)


def test_assistant_ending_in_question_signals_needs_input() -> None:
    """PR-V1-19: questions are not failures; propagate the text as pending_question."""

    question = "should I also add tests?"
    events = [_assistant(question)]
    assert check_stream_termination(events) == ("needs_input", question)


def test_last_assistant_without_text_fails_incomplete() -> None:
    """PR-V1-21: last assistant with only tool_use blocks is unusable."""

    events = [
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Edit", "id": "tu_1"}]},
        },
        {"type": "result", "subtype": "success"},
    ]
    assert check_stream_termination(events) == ("tool_use_incomplete", None)


def test_empty_stream_fails_empty_stream() -> None:
    events = [
        {"type": "started"},
        {"type": "completed"},
    ]
    assert check_stream_termination(events) == ("empty_stream", None)


def test_stream_with_result_after_assistant_question_detects_needs_input() -> None:
    """PR-V1-21 regression: real Claude CLI streams end with ``result``.

    The analyzer must walk back to the last ``assistant`` frame and
    notice that its text ends with ``?`` even though the very last
    semantic event is ``result``.
    """

    fixture_path = _FIXTURES_DIR / "stream_real_question.json"
    events = json.loads(fixture_path.read_text(encoding="utf-8"))
    code, pending = check_stream_termination(events)
    assert code == "needs_input"
    assert pending is not None
    assert "¿" in pending and "?" in pending


def test_last_assistant_answer_with_result_after_passes() -> None:
    events = [
        {"type": "system", "subtype": "init"},
        _assistant("Listo, añadido el comentario."),
        {"type": "result", "subtype": "success", "stop_reason": "end_turn"},
    ]
    assert check_stream_termination(events) == (None, None)


def test_stream_with_only_plumbing_no_assistant_returns_empty() -> None:
    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"}]},
        },
        {"type": "result", "subtype": "success"},
    ]
    assert check_stream_termination(events) == ("empty_stream", None)
