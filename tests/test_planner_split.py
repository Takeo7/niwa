"""Tests for PR-B4a — planner tier creates subtasks in DB.

Covers:
  - ``_should_run_planner`` trigger: ``decompose`` flag and description
    threshold.
  - ``_parse_planner_output`` accepts a valid ``<SUBTASKS>...</SUBTASKS>``
    JSON block and rejects malformed output.
  - ``_try_planner_split`` inserts N rows with correct ``parent_task_id``
    and marks the parent ``bloqueada`` when the planner returns valid
    subtasks.
  - When the planner output is malformed, ``_try_planner_split`` signals
    "not handled" so the caller falls through to the executor path
    without leaving the parent in a bad state.

Run: pytest tests/test_planner_split.py -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT_DIR, "bin")
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
for p in (BIN_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_executor(tmp_path, monkeypatch):
    """Load task-executor.py pointed at a fresh sqlite DB in ``tmp_path``."""
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    db_path = niwa_home / "data" / "niwa.sqlite3"
    (niwa_home / "data").mkdir()
    (niwa_home / "secrets" / "mcp.env").write_text(
        f"NIWA_DB_PATH={db_path}\n"
        f"NIWA_LLM_COMMAND_PLANNER=/usr/bin/true\n"
    )
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))

    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()

    spec = importlib.util.spec_from_file_location(
        f"task_executor_{uuid.uuid4().hex}",
        os.path.join(BIN_DIR, "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, str(db_path)


def _seed_parent_task(db_path: str, *, decompose: int = 1,
                      description: str = "", project_id: str | None = None):
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    now = "2026-04-19T00:00:00Z"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO tasks (id, title, description, area, project_id, "
        "status, priority, urgent, source, created_at, updated_at, "
        "decompose) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (task_id, "parent task", description, "proyecto", project_id,
         "en_progreso", "media", 0, "niwa-app", now, now, decompose),
    )
    conn.commit()
    conn.close()
    return task_id


# ── _should_run_planner trigger ──────────────────────────────────────


def test_should_run_planner_decompose_flag(tmp_path, monkeypatch):
    mod, _ = _load_executor(tmp_path, monkeypatch)
    task = {"decompose": 1, "description": "short"}
    assert mod._should_run_planner(task) is True


def test_should_run_planner_description_over_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("NIWA_PLANNER_DESCRIPTION_THRESHOLD", "10")
    mod, _ = _load_executor(tmp_path, monkeypatch)
    task = {"decompose": 0, "description": "x" * 50}
    assert mod._should_run_planner(task) is True


def test_should_run_planner_neither_trigger(tmp_path, monkeypatch):
    mod, _ = _load_executor(tmp_path, monkeypatch)
    task = {"decompose": 0, "description": "short"}
    assert mod._should_run_planner(task) is False


def test_should_run_planner_null_description(tmp_path, monkeypatch):
    mod, _ = _load_executor(tmp_path, monkeypatch)
    task = {"decompose": 0, "description": None}
    assert mod._should_run_planner(task) is False


# ── _parse_planner_output ────────────────────────────────────────────


def test_parse_planner_output_valid_block(tmp_path, monkeypatch):
    mod, _ = _load_executor(tmp_path, monkeypatch)
    payload = [
        {"title": "child A", "description": "do A"},
        {"title": "child B", "description": "do B", "priority": "alta"},
    ]
    text = (
        "Thinking...\n<SUBTASKS>\n"
        + json.dumps(payload)
        + "\n</SUBTASKS>\nDone."
    )
    subs = mod._parse_planner_output(text)
    assert subs is not None
    assert len(subs) == 2
    assert subs[0]["title"] == "child A"
    assert subs[1]["priority"] == "alta"


def test_parse_planner_output_missing_markers(tmp_path, monkeypatch):
    mod, _ = _load_executor(tmp_path, monkeypatch)
    assert mod._parse_planner_output("no markers here") is None


def test_parse_planner_output_invalid_json(tmp_path, monkeypatch):
    mod, _ = _load_executor(tmp_path, monkeypatch)
    text = "<SUBTASKS>\n{not json}\n</SUBTASKS>"
    assert mod._parse_planner_output(text) is None


def test_parse_planner_output_missing_title(tmp_path, monkeypatch):
    mod, _ = _load_executor(tmp_path, monkeypatch)
    # Each item must have a non-empty ``title`` at minimum.
    text = (
        "<SUBTASKS>\n"
        + json.dumps([{"description": "no title"}])
        + "\n</SUBTASKS>"
    )
    assert mod._parse_planner_output(text) is None


def test_parse_planner_output_empty_list(tmp_path, monkeypatch):
    mod, _ = _load_executor(tmp_path, monkeypatch)
    text = "<SUBTASKS>\n[]\n</SUBTASKS>"
    # Empty list = "no split decision" = None so caller falls through.
    assert mod._parse_planner_output(text) is None


# ── _try_planner_split integration ───────────────────────────────────


def _fake_heartbeat_output(output: str):
    def _fn(task_id, prompt, cwd, llm_cmd, timeout):
        return True, output
    return _fn


def test_try_planner_split_creates_children_rows(tmp_path, monkeypatch):
    mod, db_path = _load_executor(tmp_path, monkeypatch)
    parent_id = _seed_parent_task(db_path, decompose=1, description="x")

    subs_json = json.dumps([
        {"title": "step 1", "description": "do step 1"},
        {"title": "step 2", "description": "do step 2"},
        {"title": "step 3", "description": "do step 3"},
    ])
    output = f"SPLIT_INTO_SUBTASKS\n<SUBTASKS>\n{subs_json}\n</SUBTASKS>"

    # Re-read the parent row so we pass a sqlite3.Row-like mapping.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    parent_row = conn.execute(
        "SELECT * FROM tasks WHERE id=?", (parent_id,)
    ).fetchone()
    conn.close()

    with patch.object(mod, "_run_with_heartbeat",
                      _fake_heartbeat_output(output)):
        handled, result = mod._try_planner_split(parent_row)

    assert handled is True
    assert "3" in result

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    children = conn.execute(
        "SELECT id, title, parent_task_id, status, project_id "
        "FROM tasks WHERE parent_task_id=?",
        (parent_id,),
    ).fetchall()
    parent = conn.execute(
        "SELECT status FROM tasks WHERE id=?", (parent_id,)
    ).fetchone()
    conn.close()

    assert len(children) == 3
    assert {c["title"] for c in children} == {"step 1", "step 2", "step 3"}
    assert all(c["parent_task_id"] == parent_id for c in children)
    assert all(c["status"] == "pendiente" for c in children)
    assert parent["status"] == "bloqueada"


def test_try_planner_split_malformed_output_falls_through(tmp_path, monkeypatch):
    mod, db_path = _load_executor(tmp_path, monkeypatch)
    parent_id = _seed_parent_task(db_path, decompose=1, description="x")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    parent_row = conn.execute(
        "SELECT * FROM tasks WHERE id=?", (parent_id,)
    ).fetchone()
    conn.close()

    with patch.object(mod, "_run_with_heartbeat",
                      _fake_heartbeat_output("garbage no markers")):
        handled, _ = mod._try_planner_split(parent_row)

    assert handled is False

    # No children, parent still en_progreso (caller will continue to
    # the executor path).
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    children = conn.execute(
        "SELECT id FROM tasks WHERE parent_task_id=?", (parent_id,),
    ).fetchall()
    parent = conn.execute(
        "SELECT status FROM tasks WHERE id=?", (parent_id,)
    ).fetchone()
    conn.close()

    assert len(children) == 0
    assert parent["status"] == "en_progreso"


def test_try_planner_split_planner_run_fails(tmp_path, monkeypatch):
    """If the planner subprocess itself fails, no children are created."""
    mod, db_path = _load_executor(tmp_path, monkeypatch)
    parent_id = _seed_parent_task(db_path, decompose=1, description="x")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    parent_row = conn.execute(
        "SELECT * FROM tasks WHERE id=?", (parent_id,)
    ).fetchone()
    conn.close()

    def _fail(task_id, prompt, cwd, llm_cmd, timeout):
        return False, "timeout or crash"

    with patch.object(mod, "_run_with_heartbeat", _fail):
        handled, _ = mod._try_planner_split(parent_row)

    assert handled is False

    conn = sqlite3.connect(db_path)
    children = conn.execute(
        "SELECT id FROM tasks WHERE parent_task_id=?", (parent_id,),
    ).fetchall()
    conn.close()
    assert len(children) == 0
