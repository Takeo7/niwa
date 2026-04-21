"""Triage module — one LLM call to decide execute vs split (PR-V1-12a).

Public surface: ``TriageDecision`` (frozen dataclass), ``TriageError``,
and ``triage_task(project, task) -> TriageDecision``. The function
spawns the Claude Code adapter with the triage prompt, drains events
in memory (no ``run_events`` persistence), and parses the last textual
response. Wiring into the executor pipeline lands in PR-V1-12b —
nothing in ``app/executor/`` imports this yet.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.adapters.claude_code import (
    AdapterEvent,
    ClaudeCodeAdapter,
    resolve_cli_path,
)


_TRIAGE_TIMEOUT = 180.0
_PROMPT_TEMPLATE = """\
You are a triage agent for Niwa. Decide if this task should be
executed directly or split into subtasks.

# Task
Title: {title}
Description: {description}
Project kind: {kind}
Project path: {local_path}

# Instructions
- If the task is a single cohesive change (one bug fix, one
  feature, one refactor) -> decision "execute".
- If the task requires multiple independent changes that would
  naturally land in separate PRs -> decision "split", and list
  the subtask titles (short, imperative, in English).
- Do NOT modify any files. Your only output is the JSON below.

# Response format (JSON only, in a ```json fence)
{{
  "decision": "execute" | "split",
  "subtasks": ["title1", "title2", ...],
  "rationale": "one sentence explaining the choice"
}}
"""


@dataclass(frozen=True)
class TriageDecision:
    """Parsed verdict. ``kind`` in {"execute","split"}; ``subtasks`` is
    empty iff ``kind=="execute"``. ``raw_output`` is the last event text,
    kept for debug logs only."""

    kind: str
    subtasks: list[str]
    rationale: str
    raw_output: str


class TriageError(Exception):
    """Raised when triage cannot produce a valid decision."""


def triage_task(project: Any, task: Any) -> TriageDecision:
    """Run one triage pass against ``task`` on ``project``.

    Raises ``TriageError`` on adapter failure, missing JSON, or bad
    shape. ``adapter.close()`` always runs to avoid orphan subprocesses.
    """

    prompt = _build_triage_prompt(task, project)
    adapter = ClaudeCodeAdapter(
        cli_path=resolve_cli_path(),
        cwd=project.local_path,
        prompt=prompt,
        timeout=_TRIAGE_TIMEOUT,
    )
    try:
        events: list[AdapterEvent] = list(adapter.iter_events())
        adapter.wait()
        if adapter.outcome != "cli_ok" or adapter.exit_code != 0:
            raise TriageError(
                f"triage adapter failed: outcome={adapter.outcome!r} "
                f"exit_code={adapter.exit_code!r}"
            )
        text = _extract_final_text(events)
        if not text:
            raise TriageError("triage produced no textual response")
        return _validate_shape(_parse_triage_json(text), raw_output=text)
    finally:
        adapter.close()


def _build_triage_prompt(task: Any, project: Any) -> str:
    return _PROMPT_TEMPLATE.format(
        title=task.title,
        description=(getattr(task, "description", "") or "(none)"),
        kind=project.kind,
        local_path=project.local_path,
    )


def _extract_final_text(events: list[AdapterEvent]) -> str:
    """Prefer ``result`` event (``payload.result`` or ``.text``); fall back
    to the last ``assistant`` event, joining its ``type:"text"`` blocks."""

    for event in reversed(events):
        if event.kind == "result":
            value = event.payload.get("result") or event.payload.get("text")
            if isinstance(value, str) and value.strip():
                return value
    for event in reversed(events):
        if event.kind == "assistant":
            blocks = (event.payload.get("message") or {}).get("content") or []
            joined = "".join(
                b.get("text", "")
                for b in blocks
                if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
            if joined:
                return joined
    return ""


def _parse_triage_json(text: str) -> dict[str, Any]:
    """Extract a JSON object: ```json fence``` first, else first balanced
    ``{...}`` via stack scan. Raises ``TriageError`` if none found."""

    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = match.group(1) if match else _first_balanced_object(text)
    if candidate is None:
        raise TriageError("no JSON object found in response")
    try:
        parsed = json.loads(candidate)
    except ValueError as exc:
        raise TriageError(f"invalid JSON in triage response: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TriageError("triage JSON is not an object")
    return parsed


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _validate_shape(parsed: dict[str, Any], *, raw_output: str) -> TriageDecision:
    decision = parsed.get("decision")
    subtasks = parsed.get("subtasks", [])
    rationale = parsed.get("rationale", "")
    if decision not in ("execute", "split"):
        raise TriageError(f"invalid decision value: {decision!r}")
    if not isinstance(subtasks, list) or not all(isinstance(s, str) for s in subtasks):
        raise TriageError("subtasks must be a list of strings")
    if not isinstance(rationale, str):
        raise TriageError("rationale must be a string")
    if decision == "execute" and subtasks:
        raise TriageError("decision=execute requires empty subtasks")
    if decision == "split":
        if not subtasks:
            raise TriageError("decision=split requires at least one subtask")
        if any(not s.strip() for s in subtasks):
            raise TriageError("split subtasks must be non-empty strings")
    return TriageDecision(
        kind=decision,
        subtasks=list(subtasks),
        rationale=rationale,
        raw_output=raw_output,
    )


__all__ = ["TriageDecision", "TriageError", "triage_task"]
