"""E2E happy-path tests for the task → auto-project → deploy contract
(PR-54).

The unit tests in PR-51 and PR-52 cover the building blocks
(``_auto_project_prepare``, ``_auto_project_finalize``, MCP delegation
to HTTP). These tests chain those blocks in the order they actually
run in production so a future refactor cannot break the contract
without a noisy failure.

Covers three outcomes for a task that arrives without a ``project_id``:

  1. **Claude writes files, never calls ``project_create`` MCP.**
     ``_auto_project_finalize`` must insert a new ``projects`` row and
     attach the task.
  2. **Claude calls ``project_create`` MCP (row is already in the DB
     when finalize runs) AND writes files.**
     Finalize must find the existing row, not duplicate it, and
     attach the task.
  3. **Claude calls ``project_create`` MCP but writes no files
     (the prompt was a false start, an error, etc.).**
     Finalize must delete the orphan row, detach any task that was
     already linked, and remove the empty directory (PR-52 policy).

Run: pytest tests/test_e2e_auto_project_happy_path.py -v
"""
import os
import sys
import sqlite3
import uuid
from pathlib import Path

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
BIN_DIR = os.path.join(ROOT_DIR, "bin")
for p in (BACKEND_DIR, BIN_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def executor(tmp_path, monkeypatch):
    """Load bin/task-executor.py in a tmp NIWA_HOME with a fresh DB."""
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    db_path = niwa_home / "data" / "niwa.sqlite3"
    db_path.parent.mkdir(exist_ok=True)
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    (niwa_home / "secrets" / "mcp.env").write_text(
        f"NIWA_DB_PATH={db_path}\n"
        f"NIWA_PROJECTS_ROOT={projects_root}\n",
    )
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))
    monkeypatch.setenv("NIWA_PROJECTS_ROOT", str(projects_root))

    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    c = sqlite3.connect(str(db_path))
    c.executescript(schema_sql)
    c.commit()
    c.close()

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "task_executor_e2e", os.path.join(BIN_DIR, "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {"mod": mod, "db": str(db_path), "root": projects_root}


def _seed_task(db: str, title: str = "Build a blog") -> str:
    task_id = str(uuid.uuid4())
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO tasks (id, title, status, priority, area, source, "
            "created_at, updated_at) VALUES (?, ?, 'en_progreso', 'media', "
            "'proyecto', 'user', ?, ?)",
            (task_id, title, now, now),
        )
        c.commit()
    return task_id


# ── Scenario 1: Claude writes files, never calls project_create ──


def test_e2e_happy_path_files_only(executor):
    """Task without project_id → prepare creates dir → Claude (simulated)
    writes a file → finalize inserts the project row + links the task."""
    mod = executor["mod"]
    task_id = _seed_task(executor["db"], title="Build a blog")

    task_dict = {"id": task_id, "title": "Build a blog", "project_id": None}
    ctx = mod._auto_project_prepare(task_dict)
    assert ctx is not None
    assert task_dict["project_directory"] == ctx["directory"]

    project_dir = Path(ctx["directory"])
    assert project_dir.is_dir()
    # Simulate Claude writing a real artifact.
    (project_dir / "index.md").write_text("# Hello")

    mod._auto_project_finalize(ctx, task_id)

    with sqlite3.connect(executor["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT * FROM projects WHERE directory=?", (str(project_dir),),
        ).fetchone()
        task = c.execute(
            "SELECT project_id FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
    assert row is not None
    assert row["directory"] == str(project_dir)
    assert row["slug"].startswith("build-a-blog-")
    assert task["project_id"] == row["id"]
    assert (project_dir / "index.md").exists()


# ── Scenario 2: Claude calls project_create MCP then writes files ──


def test_e2e_happy_path_mcp_create_then_files(executor):
    """Simulate Claude using the ``project_create`` MCP tool BEFORE
    finalize runs (typical when the prompt includes the MCP hint).
    Finalize must see the existing row, not duplicate it, and attach
    the task.
    """
    mod = executor["mod"]
    task_id = _seed_task(executor["db"], title="API service")

    task_dict = {"id": task_id, "title": "API service", "project_id": None}
    ctx = mod._auto_project_prepare(task_dict)
    project_dir = Path(ctx["directory"])

    # Simulate project_create MCP having inserted the row already.
    now = "2026-04-17T12:00:00Z"
    preexisting_id = f"proj-{uuid.uuid4().hex[:12]}"
    with sqlite3.connect(executor["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at, directory) VALUES (?, ?, 'API service', 'proyecto', "
            "1, ?, ?, ?)",
            (preexisting_id, ctx["slug"], now, now, str(project_dir)),
        )
        c.commit()

    # Claude writes files.
    (project_dir / "server.py").write_text("print('hi')\n")

    mod._auto_project_finalize(ctx, task_id)

    with sqlite3.connect(executor["db"]) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id FROM projects WHERE directory=?", (str(project_dir),),
        ).fetchall()
        task = c.execute(
            "SELECT project_id FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
    assert len(rows) == 1, "finalize must not duplicate the project row"
    assert rows[0]["id"] == preexisting_id
    assert task["project_id"] == preexisting_id


# ── Scenario 3: Claude calls project_create then writes nothing (orphan) ──


def test_e2e_orphan_cleanup_when_mcp_creates_but_no_files(executor):
    """If ``project_create`` MCP inserted a row but nothing got written
    (the task effectively did nothing useful), finalize's orphan
    cleanup must delete the row, detach any linked task, and remove
    the empty directory."""
    mod = executor["mod"]
    task_id = _seed_task(executor["db"], title="ghost task")

    task_dict = {"id": task_id, "title": "ghost task", "project_id": None}
    ctx = mod._auto_project_prepare(task_dict)
    project_dir = Path(ctx["directory"])

    # Simulate project_create MCP having inserted + linked the task
    # (the HTTP endpoint does this in one transaction when task_id is
    # passed — PR-52).
    now = "2026-04-17T12:00:00Z"
    orphan_id = f"proj-{uuid.uuid4().hex[:12]}"
    with sqlite3.connect(executor["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at, directory) VALUES (?, ?, 'ghost', 'proyecto', 1, "
            "?, ?, ?)",
            (orphan_id, ctx["slug"], now, now, str(project_dir)),
        )
        c.execute(
            "UPDATE tasks SET project_id=? WHERE id=?", (orphan_id, task_id),
        )
        c.commit()

    # No files written — dir stays empty.
    assert not any(project_dir.iterdir())

    mod._auto_project_finalize(ctx, task_id)

    with sqlite3.connect(executor["db"]) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT id FROM projects WHERE id=?", (orphan_id,),
        ).fetchone()
        task = c.execute(
            "SELECT project_id FROM tasks WHERE id=?", (task_id,),
        ).fetchone()
    assert row is None, "orphan project row must be deleted"
    assert task["project_id"] is None, "orphan-linked task must be detached"
    assert not project_dir.exists()


# ── Scenario 4: explicit project_id → no auto-magic ──


def test_e2e_explicit_project_id_skips_auto_prepare(executor):
    """Sanity: when the task already carries a project_id, the auto-
    project machinery must not fire at all."""
    mod = executor["mod"]
    # Seed a real project row so the FK doesn't matter for this
    # assertion.
    proj_id = f"proj-{uuid.uuid4().hex[:12]}"
    now = "2026-04-17T12:00:00Z"
    with sqlite3.connect(executor["db"]) as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, active, created_at, "
            "updated_at, directory) VALUES (?, 'existing', 'Existing', "
            "'proyecto', 1, ?, ?, '/tmp/does-not-matter-for-this-test')",
            (proj_id, now, now),
        )
        c.commit()
    task_id = _seed_task(executor["db"], title="attached task")
    # Attach after insert to avoid touching the INSERT signature.
    with sqlite3.connect(executor["db"]) as c:
        c.execute(
            "UPDATE tasks SET project_id=? WHERE id=?", (proj_id, task_id),
        )
        c.commit()

    task_dict = {"id": task_id, "title": "attached task", "project_id": proj_id}
    ctx = mod._auto_project_prepare(task_dict)
    assert ctx is None
    assert "project_directory" not in task_dict
