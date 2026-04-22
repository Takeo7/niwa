"""E2 — stream termination analyzer (PR-V1-11a, PR-V1-19, PR-V1-21).

Inspects the ordered stream payload dicts (same shape as
``AdapterEvent`` payloads on ``run_events``); returns a
``(error_code, pending_question)`` tuple so the verifier can tell the
non-fatal "Claude asked a clarification" case apart from real failures.

Decision rules, ignoring lifecycle frames
(``started``/``completed``/``failed``/``error``):

* No semantic events at all → ``("empty_stream", None)``.
* Otherwise walk back to the last ``assistant`` event. Real Claude CLI
  streams always end with a ``result`` frame, so the last semantic
  event is not load-bearing — the meaningful content is the last
  ``assistant`` text. If there is no ``assistant`` in the stream (only
  ``system``/``user``/``tool_use``/``result`` plumbing), the output is
  unusable → ``("empty_stream", None)``.
* If the last ``assistant`` has no text blocks (only ``tool_use``
  blocks, no wrap-up text) → ``("tool_use_incomplete", None)``. This
  case is very rare in real CLI output but kept for historical
  coherence with PR-V1-11a.
* If the last ``assistant`` text ends with ``?`` (trimmed) →
  ``("needs_input", text)``. PR-V1-19 parks the task in
  ``waiting_input`` instead of failing it.
* Otherwise → ``(None, None)`` (clean completion).
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

    # Claude CLI always emits a terminal ``result`` frame. The
    # semantically meaningful "what did Claude say last" lives in the
    # last ``assistant`` event, not in ``result``. Walk back.
    last_assistant: dict[str, Any] | None = None
    for event in reversed(semantic):
        if event.get("type") == "assistant":
            last_assistant = event
            break

    if last_assistant is None:
        # Stream has result/user/tool_use plumbing but no assistant
        # text — unusable output.
        return ("empty_stream", None)

    text = _assistant_text(last_assistant)
    if not text:
        # Last assistant has only tool_use blocks, no text wrap-up.
        return ("tool_use_incomplete", None)
    if text.rstrip().endswith("?"):
        return ("needs_input", text)
    return (None, None)


__all__ = ["check_stream_termination"]
