"""Tests for Bug 32 fix — executor routes clarification to waiting_input.

When the adapter signals ``__NIWA_CLARIFICATION__\\n<text>`` in the
output (instead of a regular text), ``_handle_task_result`` must:

  1. Call ``_finish_task(task_id, "waiting_input", claude_text)`` —
     NOT ``_finish_task(..., "hecha")``.
  2. Record a ``comment`` event with the Claude text so the UI can
     show what was asked.
  3. Return ``(True, 0)`` so the task counts as handled (no retry,
     no increment of failure counter).

Run: pytest tests/test_task_executor_clarification.py -v
"""
from __future__ import annotations

import importlib.util
import os
import sys
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT_DIR, "bin")
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
for p in (BIN_DIR, BACKEND_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def executor(tmp_path, monkeypatch):
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "secrets" / "mcp.env").write_text(
        "NIWA_DB_PATH=/tmp/nope.sqlite3\n"
    )
    (niwa_home / "data").mkdir()
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))

    spec = importlib.util.spec_from_file_location(
        "task_executor_clarification",
        os.path.join(BIN_DIR, "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_task_row():
    return {"id": str(uuid.uuid4()), "source": "niwa-app",
            "project_id": None, "title": "T"}


# ── sentinel → waiting_input ────────────────────────────────────────


def test_clarification_sentinel_routes_to_waiting_input(executor):
    mod = executor
    task_row = _fake_task_row()
    sentinel = mod._CLARIFICATION_SENTINEL
    claude_text = "¿Qué tipo de proyecto? Node.js / Python?"
    output = sentinel + claude_text

    finish_calls = []

    def _fake_finish(task_id, status, out):
        finish_calls.append((task_id, status, out))

    events = []

    def _fake_record_event(task_id, kind, payload):
        events.append((task_id, kind, payload))

    with patch.object(mod, "_finish_task", _fake_finish), \
         patch.object(mod, "_record_event", _fake_record_event):
        done, delta = mod._handle_task_result(
            task_row["id"], True, output, False, task_row,
        )

    assert done is True
    assert delta == 0  # neither success nor failure for retry counter
    assert len(finish_calls) == 1
    assert finish_calls[0][1] == "waiting_input"
    # El texto guardado es la respuesta de Claude SIN el sentinel.
    assert finish_calls[0][2] == claude_text
    # Se registra un evento visible con la pregunta.
    comments = [e for e in events if e[1] == "comment"]
    assert comments, "clarification event must be recorded"
    msg = comments[0][2]["message"]
    assert claude_text in msg


# ── happy path still works: plain output → hecha ────────────────────


def test_plain_success_output_still_marks_hecha(executor):
    """Guard regression: un output normal (sin sentinel) sigue yendo
    a ``hecha`` como siempre."""
    mod = executor
    task_row = _fake_task_row()

    finish_calls = []
    with patch.object(
        mod, "_finish_task",
        lambda tid, st, out: finish_calls.append((tid, st, out)),
    ), patch.object(mod, "_record_event", lambda *a, **k: None):
        done, delta = mod._handle_task_result(
            task_row["id"], True, "Trabajo completado OK",
            False, task_row,
        )

    assert done is True
    assert delta == -1  # success → reset retry counter
    assert finish_calls[0][1] == "hecha"
    assert finish_calls[0][2] == "Trabajo completado OK"


# ── failure path preserved ─────────────────────────────────────────


def test_failure_path_unchanged(executor):
    """Guard: una tarea que falla NO debe colarse como clarification
    ni hecha — sigue el flow de retry/bloqueada."""
    mod = executor
    task_row = _fake_task_row()

    finish_calls = []
    retry_called = []

    def _fake_execute(row, retry_prompt=""):
        retry_called.append(retry_prompt)
        return False, "[retry also failed]"

    with patch.object(
        mod, "_finish_task",
        lambda tid, st, out: finish_calls.append((tid, st, out)),
    ), patch.object(mod, "_record_event", lambda *a, **k: None), \
       patch.object(mod, "_execute_task", _fake_execute), \
       patch.object(mod, "_build_retry_prompt", lambda *a, **k: "RETRY"), \
       patch.object(mod, "_resolve_project_dir", lambda *a, **k: None):
        done, delta = mod._handle_task_result(
            task_row["id"], False, "[attempt 1 error]",
            False, task_row,
        )

    # Con source != chat y was_retry=False, el executor intenta retry;
    # si falla → bloqueada.
    assert done is False
    assert delta == 1  # failure counter increments
    assert retry_called == ["RETRY"]
    assert finish_calls[-1][1] == "bloqueada"
