"""Tests for ``niwa-app/backend/tasks_service.get_task`` — PR-39
last_run field.

Feature 4 (docs/BUGS-FOUND.md:561): when a task fails, the UI
currently doesn't surface the error. The fix adds ``last_run`` to the
``GET /api/tasks/<id>`` response so the frontend can render a red
banner with ``error_code`` + backend display name without a second
fetch. The banner is suppressed if ``task.status == 'hecha'`` — if
the task completed, a fallback must have rescued it and alarming the
user would be misleading.

Shape contract:

    task.last_run = None
        | {id, status, outcome, error_code, finished_at,
           relation_type, backend_profile_slug,
           backend_profile_display_name}

Sensitive columns (``capability_snapshot_json``,
``budget_snapshot_json``, ``observed_usage_signals_json``) are
deliberately EXCLUDED by the SELECT whitelist — a future schema
addition won't silently leak because the query names columns
explicitly.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
DB_DIR = REPO_ROOT / "niwa-app" / "db"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        with sqlite3.connect(path) as conn:
            conn.executescript((DB_DIR / "schema.sql").read_text())
            conn.execute(
                "INSERT INTO projects (id, slug, name, area, "
                "description, active, created_at, updated_at) VALUES "
                "(?,?,?,?,?,?,?,?)",
                ("proj-1", "p", "P", "proyecto", "", 1,
                 "2026-04-01T00:00:00Z", "2026-04-01T00:00:00Z"),
            )
            conn.execute(
                "INSERT INTO backend_profiles "
                "(id, slug, display_name, backend_kind, runtime_kind, "
                " enabled, priority, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                ("bp-claude", "claude_code", "Claude Code",
                 "claude_code", "cli", 1, 10,
                 "2026-04-01T00:00:00Z", "2026-04-01T00:00:00Z"),
            )
            conn.commit()

        sys.modules.pop("tasks_service", None)
        import tasks_service  # noqa: E402

        def _db_conn():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c

        def _now_iso():
            return "2026-04-16T00:00:00Z"

        tasks_service._make_deps(_db_conn, _now_iso, Path(path).parent)
        yield tasks_service, path
    finally:
        os.unlink(path)


def _seed_task(path, task_id="t-1", status="pendiente"):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, area, status, priority, "
            "source, created_at, updated_at) VALUES "
            "(?,?,?,?,?,?,?,?)",
            (task_id, "Build a thing", "proyecto", status, "media",
             "niwa-app", "2026-04-16T00:00:00Z", "2026-04-16T00:00:00Z"),
        )
        conn.commit()


def _seed_run(path, *, run_id, task_id, outcome, status, error_code=None,
              finished_at="2026-04-16T00:01:00Z", created_at=None,
              relation_type=None, backend_profile_id="bp-claude"):
    with sqlite3.connect(path) as conn:
        # ``backend_runs`` has many NOT NULL columns; supply only what the
        # query reads. Others default in schema.sql.
        conn.execute(
            "INSERT INTO backend_runs "
            "(id, task_id, status, outcome, error_code, finished_at, "
            " relation_type, backend_profile_id, routing_decision_id, "
            " created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, task_id, status, outcome, error_code, finished_at,
             relation_type, backend_profile_id, "rd-1",
             created_at or finished_at, finished_at),
        )
        conn.commit()


class TestGetTaskLastRun:

    def test_none_when_task_has_no_runs(self, tmp_db):
        tasks_service, path = tmp_db
        _seed_task(path)
        task = tasks_service.get_task("t-1")
        assert task is not None
        assert task["last_run"] is None, (
            "A task that never ran must expose last_run=None so the "
            "frontend knows there's nothing to warn about."
        )

    def test_succeeded_run_exposes_outcome_no_error(self, tmp_db):
        tasks_service, path = tmp_db
        _seed_task(path, status="hecha")
        _seed_run(path, run_id="r-1", task_id="t-1",
                  outcome="success", status="succeeded")
        task = tasks_service.get_task("t-1")
        lr = task["last_run"]
        assert lr["outcome"] == "success"
        assert lr["error_code"] is None
        assert lr["backend_profile_slug"] == "claude_code", (
            "JOIN must expose the profile slug so the banner can "
            "say 'Claude Sonnet failed' instead of just a UUID."
        )
        assert lr["backend_profile_display_name"] == "Claude Code"

    def test_failed_run_exposes_error_code(self, tmp_db):
        tasks_service, path = tmp_db
        _seed_task(path, status="pendiente")
        _seed_run(path, run_id="r-1", task_id="t-1",
                  outcome="failure", status="failed",
                  error_code="auth_required")
        task = tasks_service.get_task("t-1")
        lr = task["last_run"]
        assert lr["outcome"] == "failure"
        assert lr["error_code"] == "auth_required"
        assert lr["id"] == "r-1"

    def test_returns_most_recent_of_multiple_runs(self, tmp_db):
        tasks_service, path = tmp_db
        _seed_task(path)
        _seed_run(path, run_id="r-old", task_id="t-1",
                  outcome="failure", status="failed",
                  error_code="timeout",
                  created_at="2026-04-16T00:00:00Z")
        _seed_run(path, run_id="r-new", task_id="t-1",
                  outcome="success", status="succeeded",
                  relation_type="fallback",
                  created_at="2026-04-16T00:05:00Z")
        task = tasks_service.get_task("t-1")
        assert task["last_run"]["id"] == "r-new", (
            "ORDER BY created_at DESC LIMIT 1 must return the last "
            "run, not the first — otherwise the banner keeps "
            "alarming about errors already rescued by a fallback."
        )
        assert task["last_run"]["relation_type"] == "fallback", (
            "relation_type is exposed so the frontend can label a "
            "fallback run differently (e.g. 'recovered by fallback' "
            "vs. 'initial attempt')."
        )

    def test_sensitive_snapshots_never_leak(self, tmp_db):
        tasks_service, path = tmp_db
        _seed_task(path)
        _seed_run(path, run_id="r-1", task_id="t-1",
                  outcome="failure", status="failed",
                  error_code="x")
        # Populate the snapshot columns with tell-tale strings. The
        # SELECT in get_task whitelists columns, so these must not
        # appear anywhere in the returned dict.
        with sqlite3.connect(path) as conn:
            conn.execute(
                "UPDATE backend_runs SET "
                "  capability_snapshot_json='SECRET_CAP', "
                "  budget_snapshot_json='SECRET_BUDGET', "
                "  observed_usage_signals_json='SECRET_USAGE' "
                "WHERE id='r-1'"
            )
            conn.commit()
        task = tasks_service.get_task("t-1")
        lr = task["last_run"]
        # Scan every string value for the markers.
        for v in lr.values():
            if isinstance(v, str):
                assert "SECRET_CAP" not in v
                assert "SECRET_BUDGET" not in v
                assert "SECRET_USAGE" not in v

    def test_runs_of_other_tasks_ignored(self, tmp_db):
        """If the query forgot the WHERE task_id=? filter, a neighbour
        task's run would leak through."""
        tasks_service, path = tmp_db
        _seed_task(path, task_id="t-1")
        _seed_task(path, task_id="t-2")
        _seed_run(path, run_id="r-for-other", task_id="t-2",
                  outcome="failure", status="failed", error_code="nope")
        task = tasks_service.get_task("t-1")
        assert task["last_run"] is None
