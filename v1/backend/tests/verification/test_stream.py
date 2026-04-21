"""E2 — stream termination analyzer unit tests (PR-V1-11a).

Feeds ``check_stream_termination`` the ordered payload dicts a run would
produce and asserts which ``error_code`` (if any) it returns. The
synthetic lifecycle frames the executor writes
(``started``/``completed``/``failed``/``error``) must be ignored — only
the real Claude stream drives the decision.
"""

from __future__ import annotations

from app.verification.stream import check_stream_termination


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
    assert check_stream_termination(events) is None


def test_assistant_ending_in_question_fails_question_unanswered() -> None:
    events = [_assistant("should I also add tests?")]
    assert check_stream_termination(events) == "question_unanswered"


def test_tool_use_last_fails_incomplete() -> None:
    events = [
        _assistant("let me edit"),
        {"type": "tool_use", "name": "Edit", "id": "tu_1"},
    ]
    assert check_stream_termination(events) == "tool_use_incomplete"


def test_empty_stream_fails_empty_stream() -> None:
    events = [
        {"type": "started"},
        {"type": "completed"},
    ]
    assert check_stream_termination(events) == "empty_stream"
