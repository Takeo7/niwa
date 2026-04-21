"""E2 — stream termination analyzer (PR-V1-11a).

Inspects the ordered stream payload dicts (same shape as
``AdapterEvent`` payloads on ``run_events``); returns ``None`` if Claude
terminated cleanly, or an ``error_code`` string otherwise.

Last-event rules (SPEC §5, evidence 2), ignoring lifecycle frames
(``started``/``completed``/``failed``/``error``):

* ``result`` → OK (MVP trusts any ``subtype``).
* ``assistant`` with text ending in ``?`` → ``question_unanswered``.
* ``tool_use`` → ``tool_use_incomplete``.
* anything else (including no semantic events) → ``empty_stream``.
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


def check_stream_termination(events: list[dict[str, Any]]) -> str | None:
    """Return ``None`` on success, otherwise an ``error_code`` string."""

    semantic = [e for e in events if e.get("type") not in _LIFECYCLE]
    if not semantic:
        return "empty_stream"
    last = semantic[-1]
    kind = last.get("type")
    if kind == "result":
        return None
    if kind == "tool_use":
        return "tool_use_incomplete"
    if kind == "assistant":
        return "question_unanswered" if _assistant_text(last).rstrip().endswith("?") else None
    return "empty_stream"


__all__ = ["check_stream_termination"]
