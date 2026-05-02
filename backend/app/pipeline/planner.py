"""Task planning service with deterministic and Claude Code modes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.adapters.claude_code import ClaudeCodeAdapter, resolve_cli_path, resolve_timeout
from app.config import load_settings
from app.triage import _extract_final_text, _parse_triage_json


@dataclass(frozen=True)
class PlannerResult:
    summary: str
    steps: list[str]
    risks: list[str]
    acceptance_criteria: list[str]
    planner: str
    raw_json: str


def plan_task(task: Any, project: Any) -> PlannerResult:
    mode = load_settings().pipeline_planner_mode
    if mode == "claude-code":
        try:
            return _claude_plan(task, project)
        except Exception:
            return _fake_plan(task)
    return _fake_plan(task)


def _fake_plan(task: Any) -> PlannerResult:
    payload = {
        "summary": f"Execute task: {task.title}",
        "steps": [
            "Inspect the assigned task and attached context.",
            "Apply the smallest code or content change that satisfies the task.",
            "Run verification and finalize only if evidence passes.",
        ],
        "risks": [],
        "acceptance_criteria": ["Verification passes."],
    }
    return PlannerResult(
        summary=payload["summary"],
        steps=payload["steps"],
        risks=payload["risks"],
        acceptance_criteria=payload["acceptance_criteria"],
        planner="fake-json",
        raw_json=json.dumps(payload, sort_keys=True),
    )


def _claude_plan(task: Any, project: Any) -> PlannerResult:
    parsed = _call_claude_json(_planner_prompt(task, project), project.local_path)
    summary = _required_str(parsed, "summary")
    steps = _str_list(parsed, "steps", required=True)
    risks = _str_list(parsed, "risks")
    criteria = _str_list(parsed, "acceptance_criteria", required=True)
    return PlannerResult(
        summary=summary,
        steps=steps,
        risks=risks,
        acceptance_criteria=criteria,
        planner="claude-code",
        raw_json=json.dumps(parsed, sort_keys=True),
    )


def _call_claude_json(prompt: str, cwd: str) -> dict[str, Any]:
    adapter = ClaudeCodeAdapter(
        cli_path=resolve_cli_path(),
        cwd=cwd,
        prompt=prompt,
        timeout=resolve_timeout(),
    )
    try:
        events = list(adapter.iter_events())
        adapter.wait()
        if adapter.outcome != "cli_ok" or adapter.exit_code != 0:
            raise RuntimeError("planner adapter failed")
        text = _extract_final_text(events)
        if not text:
            raise RuntimeError("planner produced no text")
        return _parse_triage_json(text)
    finally:
        adapter.close()


def _planner_prompt(task: Any, project: Any) -> str:
    return f"""You are Niwa's planner. Return JSON only in a ```json fence`.
Task: {task.title}
Description: {getattr(task, "description", "") or "(none)"}
Project kind: {project.kind}

Schema:
{{"summary":"...", "steps":["..."], "risks":["..."], "acceptance_criteria":["..."]}}
"""


def _required_str(parsed: dict[str, Any], key: str) -> str:
    value = parsed.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _str_list(parsed: dict[str, Any], key: str, *, required: bool = False) -> list[str]:
    value = parsed.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    result = [item.strip() for item in value if item.strip()]
    if required and not result:
        raise ValueError(f"{key} must not be empty")
    return result
