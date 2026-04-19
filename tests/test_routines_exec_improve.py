"""Tests for PR-C4 — ``_exec_improve()`` and routine wiring.

Covers:
  - ``_exec_improve`` error paths (missing ``project_id``, unknown
    project, invalid ``improvement_type``).
  - Happy path for each of the three improvement types creates a
    ``pendiente`` task with ``source='routine:improve:<type>'``,
    ``project_id`` resolved, and a description that embeds the
    project name + directory and the template keywords.
  - ``_execute_routine`` routes ``action='improve'`` into
    ``_exec_improve`` and records ``last_status='ok'`` on success,
    ``'error'`` on failure (no task created in the latter case).

Run: pytest tests/test_routines_exec_improve.py -v
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "niwa-app" / "backend"
DB_DIR = ROOT_DIR / "niwa-app" / "db"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ─────────────────────── helpers (mirror PR-C3 test style) ───────────────────────

def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript((DB_DIR / "schema.sql").read_text(encoding="utf-8"))


def _apply_migration(conn: sqlite3.Connection, filename: str) -> None:
    import re as _re
    sql = (DB_DIR / "migrations" / filename).read_text(encoding="utf-8")
    lines = []
    for line in sql.split("\n"):
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        if " --" in line:
            line = line[: line.index(" --")]
        lines.append(line)
    for stmt in "\n".join(lines).split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        if _re.match(
            r"(BEGIN|COMMIT|END|ROLLBACK)(\s+(TRANSACTION|WORK))?\s*$",
            stmt, _re.IGNORECASE,
        ):
            continue
        m = _re.match(
            r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
            stmt, _re.IGNORECASE,
        )
        if m:
            table, column = m.group(1), m.group(2)
            existing = {
                r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column in existing:
                continue
        conn.execute(stmt)


def _fresh_db(tmp_path: Path) -> Path:
    db = tmp_path / "t.db"
    c = sqlite3.connect(db)
    _apply_schema(c)
    _apply_migration(c, "003_deployments.sql")
    _apply_migration(c, "016_routines_improve.sql")
    c.commit()
    c.close()
    return db


def _conn_fn_for(db_path: Path):
    def _f():
        cc = sqlite3.connect(db_path)
        cc.row_factory = sqlite3.Row
        return cc
    return _f


def _seed_project(
    db_path: Path,
    *,
    name: str = "acme-site",
    directory: str = "/srv/projects/acme",
) -> str:
    pid = str(uuid.uuid4())
    c = sqlite3.connect(db_path)
    c.execute(
        "INSERT INTO projects (id, slug, name, area, directory, created_at, updated_at) "
        "VALUES (?, ?, ?, 'proyecto', ?, ?, ?)",
        (pid, f"proj-{pid[:6]}", name, directory,
         "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    c.commit()
    c.close()
    return pid


def _fresh_scheduler_module():
    import importlib
    import scheduler
    importlib.reload(scheduler)
    return scheduler


# ─────────────────────── _exec_improve error paths ───────────────────────

def test_exec_improve_missing_project_id(tmp_path):
    db = _fresh_db(tmp_path)
    scheduler = _fresh_scheduler_module()
    conn_fn = _conn_fn_for(db)

    result, success = scheduler._exec_improve({}, "stability", conn_fn)
    assert success is False
    assert result.startswith("[error]")
    assert "project_id" in result

    c = sqlite3.connect(db)
    n = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    c.close()
    assert n == 0


def test_exec_improve_unknown_project(tmp_path):
    db = _fresh_db(tmp_path)
    scheduler = _fresh_scheduler_module()
    conn_fn = _conn_fn_for(db)

    ghost = "does-not-exist-" + uuid.uuid4().hex[:6]
    result, success = scheduler._exec_improve(
        {"project_id": ghost}, "functional", conn_fn,
    )
    assert success is False
    assert result.startswith("[error]")
    assert ghost in result

    c = sqlite3.connect(db)
    n = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    c.close()
    assert n == 0


def test_exec_improve_invalid_improvement_type(tmp_path):
    db = _fresh_db(tmp_path)
    scheduler = _fresh_scheduler_module()
    conn_fn = _conn_fn_for(db)
    pid = _seed_project(db)

    with pytest.raises(ValueError):
        scheduler._exec_improve({"project_id": pid}, "nonsense", conn_fn)


# ─────────────────────── _exec_improve happy paths ───────────────────────

def _assert_improve_task(
    db_path: Path,
    *,
    improvement_type: str,
    project_id: str,
    project_name: str,
    project_directory: str,
    template_keywords: list[str],
) -> None:
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT * FROM tasks WHERE source=?",
        (f"routine:improve:{improvement_type}",),
    ).fetchall()
    c.close()
    assert len(rows) == 1, f"expected 1 task, got {len(rows)}"
    row = rows[0]
    assert row["project_id"] == project_id
    assert row["area"] == "sistema"
    assert row["status"] == "pendiente"
    desc = row["description"] or ""
    assert project_name in desc
    assert project_directory in desc
    for kw in template_keywords:
        assert kw in desc, f"missing template keyword {kw!r} in description"


def test_exec_improve_functional_creates_task(tmp_path):
    db = _fresh_db(tmp_path)
    scheduler = _fresh_scheduler_module()
    conn_fn = _conn_fn_for(db)
    pid = _seed_project(db, name="my-shop", directory="/var/niwa/my-shop")

    result, success = scheduler._exec_improve(
        {"project_id": pid}, "functional", conn_fn,
    )
    assert success is True
    assert result.startswith("Task created:")

    _assert_improve_task(
        db,
        improvement_type="functional",
        project_id=pid,
        project_name="my-shop",
        project_directory="/var/niwa/my-shop",
        template_keywords=["functional improvement"],
    )


def test_exec_improve_stability_creates_task(tmp_path):
    db = _fresh_db(tmp_path)
    scheduler = _fresh_scheduler_module()
    conn_fn = _conn_fn_for(db)
    pid = _seed_project(db, name="api-gw", directory="/var/niwa/api-gw")

    result, success = scheduler._exec_improve(
        {"project_id": pid}, "stability", conn_fn,
    )
    assert success is True
    assert result.startswith("Task created:")

    _assert_improve_task(
        db,
        improvement_type="stability",
        project_id=pid,
        project_name="api-gw",
        project_directory="/var/niwa/api-gw",
        template_keywords=["pytest"],
    )


def test_exec_improve_security_creates_task(tmp_path):
    db = _fresh_db(tmp_path)
    scheduler = _fresh_scheduler_module()
    conn_fn = _conn_fn_for(db)
    pid = _seed_project(db, name="billing", directory="/var/niwa/billing")

    result, success = scheduler._exec_improve(
        {"project_id": pid}, "security", conn_fn,
    )
    assert success is True
    assert result.startswith("Task created:")

    _assert_improve_task(
        db,
        improvement_type="security",
        project_id=pid,
        project_name="billing",
        project_directory="/var/niwa/billing",
        template_keywords=["pip-audit"],
    )


# ─────────────────────── _execute_routine integration ───────────────────────

def _insert_improve_routine(
    conn_fn,
    *,
    routine_id: str,
    improvement_type: str,
    project_id: str | None,
) -> None:
    config = {"project_id": project_id} if project_id else {}
    with conn_fn() as conn:
        conn.execute(
            "INSERT INTO routines (id, name, enabled, schedule, tz, action, "
            "action_config, improvement_type, notify_channel, notify_config, "
            "consecutive_errors, created_at, updated_at) VALUES "
            "(?, ?, 1, '*/10 * * * *', 'UTC', 'improve', ?, ?, 'none', '{}', "
            "0, '2026-01-01T00:00:00', '2026-01-01T00:00:00')",
            (routine_id, f"r-{routine_id}", json.dumps(config), improvement_type),
        )
        conn.commit()


def test_execute_routine_improve_happy_path(tmp_path):
    db = _fresh_db(tmp_path)
    scheduler = _fresh_scheduler_module()
    conn_fn = _conn_fn_for(db)
    pid = _seed_project(db)
    _insert_improve_routine(
        conn_fn,
        routine_id="imp-stab-1",
        improvement_type="stability",
        project_id=pid,
    )

    sched = scheduler.SchedulerThread(conn_fn, tmp_path)
    with conn_fn() as conn:
        routine = dict(
            conn.execute(
                "SELECT * FROM routines WHERE id=?", ("imp-stab-1",),
            ).fetchone()
        )
    sched._execute_routine(routine)

    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    r = c.execute(
        "SELECT last_status, last_error FROM routines WHERE id=?",
        ("imp-stab-1",),
    ).fetchone()
    n_tasks = c.execute(
        "SELECT COUNT(*) FROM tasks WHERE source='routine:improve:stability'"
    ).fetchone()[0]
    c.close()
    assert r["last_status"] == "ok", r["last_error"]
    assert n_tasks == 1


def test_execute_routine_improve_bad_project_marks_error(tmp_path):
    db = _fresh_db(tmp_path)
    scheduler = _fresh_scheduler_module()
    conn_fn = _conn_fn_for(db)
    _insert_improve_routine(
        conn_fn,
        routine_id="imp-sec-bad",
        improvement_type="security",
        project_id="ghost-pid",
    )

    sched = scheduler.SchedulerThread(conn_fn, tmp_path)
    with conn_fn() as conn:
        routine = dict(
            conn.execute(
                "SELECT * FROM routines WHERE id=?", ("imp-sec-bad",),
            ).fetchone()
        )
    sched._execute_routine(routine)

    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    r = c.execute(
        "SELECT last_status, last_error FROM routines WHERE id=?",
        ("imp-sec-bad",),
    ).fetchone()
    n_tasks = c.execute(
        "SELECT COUNT(*) FROM tasks WHERE source LIKE 'routine:improve:%'"
    ).fetchone()[0]
    c.close()
    assert r["last_status"] == "error"
    assert r["last_error"] and "ghost-pid" in r["last_error"]
    assert n_tasks == 0
