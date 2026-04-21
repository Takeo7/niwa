"""E2 — stream termination analyzer (PR-V1-11a, extended PR-V1-19).

Inspects the ordered stream payload dicts (same shape as
``AdapterEvent`` payloads on ``run_events``); returns a
``(error_code, pending_question)`` tuple so the verifier can tell the
non-fatal "Claude asked a clarification" case apart from real failures.

Last-event rules (SPEC §5, evidence 2), ignoring lifecycle frames
(``started``/``completed``/``failed``/``error``):

* ``result`` → ``(None, None)``, clean completion.
* ``assistant`` with text ending in ``?`` → ``("needs_input", text)``.
  PR-V1-19 replaces the old ``question_unanswered`` error code: the
  executor now parks the task in ``waiting_input`` so the user can
  answer without the task being marked failed.
* ``assistant`` not ending in ``?`` → ``(None, None)``.
* ``tool_use`` → ``("tool_use_incomplete", None)``.
* anything else (including no semantic events) → ``("empty_stream", None)``.
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


def check_stream_termination(
    events: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """Return ``(error_code, pending_question)`` describing the terminator."""

    semantic = [e for e in events if e.get("type") not in _LIFECYCLE]
    if not semantic:
        return ("empty_stream", None)
    last = semantic[-1]
    kind = last.get("type")
    if kind == "result":
        return (None, None)
    if kind == "tool_use":
        return ("tool_use_incomplete", None)
    if kind == "assistant":
        text = _assistant_text(last)
        if text.rstrip().endswith("?"):
            return ("needs_input", text)
        return (None, None)
    return ("empty_stream", None)


__all__ = ["check_stream_termination"]
