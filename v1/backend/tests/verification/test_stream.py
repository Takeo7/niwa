"""E2 — stream termination analyzer unit tests (PR-V1-11a, PR-V1-21, PR-V1-21b).

Feeds ``check_stream_termination`` the ordered payload dicts a run would
produce and asserts which ``error_code`` (if any) it returns. The
synthetic lifecycle frames the executor writes
(``started``/``completed``/``failed``/``error``) must be ignored — only
the real Claude stream drives the decision.

PR-V1-21 reshapes the semantics: the analyzer now walks back to the
last ``assistant`` event instead of trusting the last semantic frame,
because the real Claude CLI always emits a trailing ``result``.

PR-V1-21b adds two structural signals on top of the text heuristic:
the ``AskUserQuestion`` native tool_use (primary) and
``result.permission_denials`` (secondary). Fixtures
``stream_ask_user_question.json`` / ``stream_question_with_imperative.json``
are synthetic fixtures modelled on smoke 2026-04-22 run_id=10 task 12 and
run_id=9 task 11 respectively, reconstructed from the brief payloads
because the sandbox has no access to the humanu2019s DB.
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


def test_ask_user_question_tool_use_signals_needs_input() -> None:
    """PR-V1-21b signal 1: AskUserQuestion embedded in assistant.content[]."""

    fixture_path = _FIXTURES_DIR / "stream_ask_user_question.json"
    events = json.loads(fixture_path.read_text(encoding="utf-8"))
    evidence: dict = {}
    code, pending = check_stream_termination(events, evidence=evidence)
    assert code == "needs_input"
    assert pending == "¿Qué enfoque quieres para el ensayo?"
    options = evidence.get("ask_user_question_options")
    assert isinstance(options, list) and len(options) == 3
    assert {o["label"] for o in options} == {
        "Alineamiento",
        "Limitaciones",
        "Interpretabilidad",
    }


def test_ask_user_question_in_permission_denials_signals_needs_input() -> None:
    """PR-V1-21b signal 2: denial present, tool_use event absent."""

    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "result",
            "subtype": "success",
            "permission_denials": [
                {
                    "tool_name": "AskUserQuestion",
                    "tool_input": {
                        "questions": [
                            {"question": "¿Procedo con tests?", "options": []}
                        ]
                    },
                }
            ],
        },
    ]
    code, pending = check_stream_termination(events)
    assert code == "needs_input"
    assert pending == "¿Procedo con tests?"


def test_question_with_imperative_closing_detects_via_paragraph_scan() -> None:
    """PR-V1-21b signal 3: text ends with '.' but a prior paragraph ends in '?'."""

    fixture_path = _FIXTURES_DIR / "stream_question_with_imperative.json"
    events = json.loads(fixture_path.read_text(encoding="utf-8"))
    code, pending = check_stream_termination(events)
    assert code == "needs_input"
    assert pending is not None
    assert "¿Python o Node?" in pending


def test_spanish_question_marks_detected() -> None:
    text = "¿Cómo quieres proceder?\n\nDime cuál prefieres."
    events = [_assistant(text), {"type": "result", "subtype": "success"}]
    code, pending = check_stream_termination(events)
    assert code == "needs_input"
    assert pending == text


def test_statement_with_question_mark_inside_code_not_detected() -> None:
    """Known false-negative trade-off: ? inside inline code with '.' end."""

    text = "Instalado. El archivo X contiene `?` como separador."
    events = [_assistant(text), {"type": "result", "subtype": "success"}]
    assert check_stream_termination(events) == (None, None)
