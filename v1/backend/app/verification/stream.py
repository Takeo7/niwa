"""E2 — stream termination analyzer (PR-V1-11a / 19 / 21 / 21b).

Inspects ``run_events`` payload dicts; returns
``(error_code, pending_question)`` so the verifier tells the non-fatal
"Claude asked a clarification" case apart from real failures.

Signals (order of priority, PR-V1-21b):

1. ``AskUserQuestion`` ``tool_use`` (top-level or embedded in
   ``assistant.message.content[]``) → ``("needs_input", question)``;
   the optional ``evidence`` kwarg captures ``options`` under
   ``evidence["ask_user_question_options"]``.
2. Walk back to the last ``assistant`` (real CLI always ends on
   ``result``, so the last semantic frame is not load-bearing).
   Empty text → ``("tool_use_incomplete", None)``. Text ends with
   ``?`` → ``("needs_input", text)``. Otherwise ``(None, None)``.

No semantic events or no ``assistant`` → ``("empty_stream", None)``.
"""

from __future__ import annotations

from typing import Any


_LIFECYCLE = {"started", "completed", "failed", "error"}


def _assistant_text(payload: dict[str, Any]) -> str:
    """Concatenated ``type:"text"`` blocks of an assistant payload."""

    content = (payload.get("message") or {}).get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        item.get("text", "")
        for item in content
        if isinstance(item, dict)
        and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    )


def _iter_tool_use_blocks(events: list[dict[str, Any]]):
    """Yield every ``tool_use`` dict — top-level or embedded in assistant."""

    for event in events:
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "tool_use":
            yield event
            continue
        if kind == "assistant":
            content = (event.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    yield block


def _find_ask_user_question(
    events: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]] | None] | None:
    """Return ``(question, options)`` from the first AskUserQuestion tool_use."""

    for block in _iter_tool_use_blocks(events):
        if block.get("name") != "AskUserQuestion":
            continue
        questions = (block.get("input") or {}).get("questions")
        if not isinstance(questions, list) or not questions:
            continue
        first = questions[0]
        if not isinstance(first, dict):
            continue
        question = first.get("question")
        if not isinstance(question, str) or not question:
            continue
        options = first.get("options") if isinstance(first.get("options"), list) else None
        return (question, options)
    return None


def check_stream_termination(
    events: list[dict[str, Any]],
    *,
    evidence: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Return ``(error_code, pending_question)`` describing the terminator.

    ``evidence`` is an optional side-channel: if supplied and signal 1
    captures ``options`` for the ``AskUserQuestion`` tool_use, they land
    on ``evidence["ask_user_question_options"]`` so the caller can
    persist them on ``run.verification_json``.
    """

    # Signal 1 — AskUserQuestion tool_use (primary).
    found = _find_ask_user_question(events)
    if found is not None:
        question, options = found
        if evidence is not None and options is not None:
            evidence["ask_user_question_options"] = options
        return ("needs_input", question)

    semantic = [e for e in events if e.get("type") not in _LIFECYCLE]
    if not semantic:
        return ("empty_stream", None)

    # Claude CLI always emits a terminal ``result`` frame. The
    # semantically meaningful "what did Claude say last" lives in the
    # last ``assistant`` event, not in ``result``. Walk back.
    last_assistant: dict[str, Any] | None = None
    for event in reversed(semantic):
        if event.get("type") == "assistant":
            last_assistant = event
            break

    if last_assistant is None:
        return ("empty_stream", None)

    text = _assistant_text(last_assistant)
    if not text:
        return ("tool_use_incomplete", None)
    if text.rstrip().endswith("?"):
        return ("needs_input", text)
    return (None, None)


__all__ = ["check_stream_termination"]
