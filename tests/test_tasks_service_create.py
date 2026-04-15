"""Tests for ``niwa-app/backend/tasks_service.create_task``.

Regression guard for the "network connection lost" bug observed on the
Niwa app UI after first install:

    POST /api/tasks with ``area: ""`` (the TaskForm default when the user
    doesn't pick an area in the dropdown) would hit a SQLite CHECK
    constraint violation on ``tasks.area IN ('personal','empresa',
    'proyecto','sistema')``. The uncaught ``IntegrityError`` propagates
    out of ``ThreadingHTTPServer.do_POST``, which closes the socket
    without writing a response → the browser reports it as "Failed to
    load resource: the network connection was lost".

The fix normalises empty/whitespace/unset CHECK-constrained string
fields to their schema defaults before the INSERT so the request
always succeeds on valid values instead of bleeding a 500 through a
closed socket.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
DB_DIR = REPO_ROOT / "niwa-app" / "db"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db():
    """Create a fresh SQLite DB with schema.sql applied and wire
    ``tasks_service._make_deps`` to it so the module-level ``_db_conn``
    / ``_now_iso`` injection matches what app.py does at import time."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    try:
        with sqlite3.connect(path) as conn:
            conn.executescript((DB_DIR / "schema.sql").read_text())
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, slug, name, area, "
                "description, active, created_at, updated_at) VALUES "
                "(?,?,?,?,?,?,?,?)",
                ("proj-default", "default", "Default", "proyecto",
                 "fixture", 1, "2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z"),
            )
            conn.commit()

        sys.modules.pop("tasks_service", None)
        import tasks_service  # noqa: E402

        def _db_conn():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c

        def _now_iso():
            return "2025-01-01T00:00:00Z"

        tasks_service._make_deps(_db_conn, _now_iso, Path(path).parent)
        yield tasks_service, path
    finally:
        os.unlink(path)


def _get_task(db_path, task_id):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM tasks WHERE id=?", (task_id,),
        ).fetchone()


class TestCreateTaskNormalisation:
    """Regression: empty strings for CHECK-constrained fields must not
    blow up the INSERT — they get coerced to schema defaults."""

    def test_empty_area_becomes_default(self, tmp_db):
        tasks_service, db_path = tmp_db
        task_id = tasks_service.create_task(
            {"title": "t1", "area": ""},
        )
        row = _get_task(db_path, task_id)
        assert row is not None
        assert row["area"] == "proyecto"

    def test_missing_area_becomes_default(self, tmp_db):
        tasks_service, db_path = tmp_db
        task_id = tasks_service.create_task({"title": "t2"})
        row = _get_task(db_path, task_id)
        assert row["area"] == "proyecto"

    def test_whitespace_area_becomes_default(self, tmp_db):
        tasks_service, db_path = tmp_db
        task_id = tasks_service.create_task(
            {"title": "t3", "area": "   "},
        )
        row = _get_task(db_path, task_id)
        assert row["area"] == "proyecto"

    def test_valid_area_is_preserved(self, tmp_db):
        tasks_service, db_path = tmp_db
        task_id = tasks_service.create_task(
            {"title": "t4", "area": "empresa"},
        )
        row = _get_task(db_path, task_id)
        assert row["area"] == "empresa"

    def test_empty_status_becomes_default(self, tmp_db):
        tasks_service, db_path = tmp_db
        task_id = tasks_service.create_task(
            {"title": "t5", "status": ""},
        )
        row = _get_task(db_path, task_id)
        assert row["status"] == "pendiente"

    def test_empty_priority_becomes_default(self, tmp_db):
        tasks_service, db_path = tmp_db
        task_id = tasks_service.create_task(
            {"title": "t6", "priority": ""},
        )
        row = _get_task(db_path, task_id)
        assert row["priority"] == "media"

    def test_empty_title_becomes_placeholder(self, tmp_db):
        tasks_service, db_path = tmp_db
        task_id = tasks_service.create_task({"title": ""})
        row = _get_task(db_path, task_id)
        # schema declares title NOT NULL, so we need *something*; match
        # the existing convention of "Nueva tarea" as the placeholder.
        assert row["title"] == "Nueva tarea"

    def test_ui_default_payload_succeeds(self, tmp_db):
        """Regression for the exact payload the TaskForm sends when the
        user hits "Crear tarea" without touching any dropdown.

        This is the payload shape that was blowing up the socket and
        surfacing as "network connection lost" in the browser.
        """
        tasks_service, db_path = tmp_db
        # Mirror the body that ``src/features/tasks/components/TaskForm.tsx``
        # sends in handleSubmit when the user just types a title.
        payload = {
            "title": "Primer test post-install",
            "description": "",
            "status": "pendiente",
            "priority": "media",
            "project_id": None,
            "due_at": None,
            "scheduled_for": None,
            "area": "",           # ← the offending empty string
            "urgent": 0,
        }
        # Before the fix this raised sqlite3.IntegrityError (CHECK).
        task_id = tasks_service.create_task(payload)
        assert task_id
        row = _get_task(db_path, task_id)
        assert row["area"] == "proyecto"
        assert row["status"] == "pendiente"

    def test_pre_fix_area_empty_still_fails_with_direct_insert(self, tmp_db):
        """Negative control: an INSERT that bypasses create_task's
        normalisation and writes ``area=''`` directly must still trip
        the CHECK constraint — this proves schema.sql's CHECK is active
        and that the fix's normalisation is what makes the happy path
        work, not a schema change."""
        _tasks_service, db_path = tmp_db
        with sqlite3.connect(db_path) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO tasks (id, title, area, status, priority, "
                    "urgent, assigned_to_yume, assigned_to_claude, "
                    "created_at, updated_at) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), "t", "", "pendiente", "media",
                     0, 0, 0, "2025-01-01", "2025-01-01"),
                )
