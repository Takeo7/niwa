"""Triage planner — single-call ``execute | split`` decision (SPEC §4).

Wraps ``ClaudeCodeAdapter`` with a dedicated prompt, parses the JSON
decision, returns a ``TriageDecision`` to ``executor.core``. No retries,
no loops. Any failure raises ``TriageError`` and the caller terminates
the task with ``outcome="triage_failed"``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from .adapters import ClaudeCodeAdapter, resolve_cli_path
from .models import Project, Task

logger = logging.getLogger("niwa.triage")

_TRIAGE_TIMEOUT = 180.0
_PROMPT_MARKER = "triage agent for Niwa"


@dataclass(frozen=True)
class TriageDecision:
    kind: str  # "execute" | "split"
    subtasks: list[str]  # titles; empty when kind == "execute"
    rationale: str
    raw_output: str


class TriageError(RuntimeError):
    """Raised when the triage call fails or its output is unparseable."""


def triage_task(project: Project, task: Task) -> TriageDecision:
    """Run the CLI once with a triage prompt and parse the JSON decision."""
    adapter = ClaudeCodeAdapter(
        cli_path=resolve_cli_path(),
        cwd=project.local_path or ".",
        prompt=_build_prompt(project, task),
        timeout=_TRIAGE_TIMEOUT,
    )
    texts: list[str] = []
    try:
        try:
            for event in adapter.iter_events():
                snippet = _extract_text(event.payload)
                if snippet:
                    texts.append(snippet)
            adapter.wait()
        except Exception as exc:  # noqa: BLE001 - always surface as TriageError
            logger.exception("triage adapter crashed for task_id=%s", task.id)
            raise TriageError(f"adapter_exception: {exc}") from exc
    finally:
        adapter.close()

    if (adapter.outcome or "cli_ok") != "cli_ok":
        raise TriageError(f"adapter_outcome={adapter.outcome}")

    raw = "\n".join(texts).strip()
    return _build_decision(_parse_decision(raw), raw)


def _build_prompt(project: Project, task: Task) -> str:
    return (
        f"You are a {_PROMPT_MARKER}. Decide if this task should be\n"
        "executed directly or split into subtasks.\n\n"
        f"# Task\nTitle: {task.title}\n"
        f"Description: {task.description or '(none)'}\n"
        f"Project kind: {project.kind}\nProject path: {project.local_path}\n\n"
        "# Instructions\n"
        "- Single cohesive change (one bug/feature/refactor) -> \"execute\".\n"
        "- Multiple independent changes landing in separate PRs ->\n"
        "  \"split\"; list subtask titles (short, imperative, in English).\n"
        "- Do NOT modify any files. Your only output is the JSON below.\n\n"
        "# Response format (JSON only, in a ```json fence)\n"
        "{\"decision\": \"execute\"|\"split\", \"subtasks\": [\"title\", ...],"
        " \"rationale\": \"one sentence\"}\n"
    )


def _extract_text(payload: dict[str, Any]) -> str:
    """Pull free text out of an ``assistant`` or ``result`` stream-json event."""
    if not isinstance(payload, dict):
        return ""
    for key in ("result", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), list):
        return "\n".join(
            item["text"] for item in message["content"]
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


def _parse_decision(raw: str) -> dict[str, Any]:
    """Locate a JSON object in ``raw`` and parse it, or raise ``TriageError``."""
    if not raw:
        raise TriageError("empty output")
    match = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if match:
        candidate = match.group(1)
    else:
        start = raw.find("{")
        if start < 0:
            raise TriageError("no JSON object in output")
        depth, end = 0, -1
        for i in range(start, len(raw)):
            if raw[i] == "{":
                depth += 1
            elif raw[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end <= 0:
            raise TriageError("unbalanced JSON braces")
        candidate = raw[start:end]
    try:
        parsed = json.loads(candidate)
    except ValueError as exc:
        raise TriageError(f"json parse error: {exc}") from exc
    if not isinstance(parsed, dict):
        raise TriageError("JSON root is not an object")
    return parsed


def _build_decision(data: dict[str, Any], raw_output: str) -> TriageDecision:
    decision = data.get("decision")
    if decision not in ("execute", "split"):
        raise TriageError(f"invalid decision: {decision!r}")
    raw_subtasks = data.get("subtasks", [])
    if not isinstance(raw_subtasks, list) or not all(isinstance(x, str) for x in raw_subtasks):
        raise TriageError("subtasks must be a list of strings")
    subtasks = [s.strip() for s in raw_subtasks if s and s.strip()]
    if (decision == "execute") == bool(subtasks):
        raise TriageError(f"subtasks/decision mismatch: {decision} with {len(subtasks)}")
    rationale = data.get("rationale", "")
    if not isinstance(rationale, str):
        raise TriageError("rationale must be a string")
    return TriageDecision(
        kind=decision, subtasks=subtasks, rationale=rationale, raw_output=raw_output,
    )


__all__ = ["TriageDecision", "TriageError", "triage_task"]
