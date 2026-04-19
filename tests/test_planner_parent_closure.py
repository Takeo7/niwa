"""Tests for PR-B4b — planner parent closure + child counts + decompose flag.

PR-B4a (merged) lets the planner create children with ``parent_task_id``
and moves the parent to ``bloqueada``. PR-B4b closes the loop:

  1. When the last child transitions to ``hecha``, the parent closes
     automatically (``bloqueada → hecha``). Works from both the
     backend ``update_task`` path (UI-driven) and the executor
     ``_finish_task`` path (autonomous runs).
  2. ``fetch_tasks`` / ``get_task`` expose ``child_count_total`` and
     ``child_count_done`` so the UI can render a badge.
  3. ``create_task`` accepts ``decompose`` so the TaskForm checkbox
     can opt a task into the planner tier.

Run: pytest tests/test_planner_parent_closure.py -v
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
BIN_DIR = REPO_ROOT / "bin"
DB_DIR = REPO_ROOT / "niwa-app" / "db"
for p in (BACKEND_DIR, BIN_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ────────────────────────── backend fixtures ──────────────────────────


@pytest.fixture()
def tmp_db(monkeypatch):
    """Fresh SQLite DB with schema, wired into tasks_service + tasks_helpers."""
    fd, path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)
    monkeypatch.delenv("NIWA_DEPLOY_ON_TASK_SUCCESS", raising=False)
    try:
        with sqlite3.connect(path) as conn:
            conn.executescript((DB_DIR / "schema.sql").read_text())
            conn.execute(
                "INSERT INTO projects (id, slug, name, area, "
                "description, active, created_at, updated_at, "
                "directory, url) VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("proj-1", "p", "P", "proyecto", "", 1,
                 "2026-04-19T00:00:00Z", "2026-04-19T00:00:00Z",
                 "/tmp/niwa-fixture-dir", ""),
            )
            conn.commit()

        sys.modules.pop("tasks_service", None)
        sys.modules.pop("tasks_helpers", None)
        import tasks_helpers  # noqa: E402
        import tasks_service  # noqa: E402

        def _db_conn():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            return c

        def _now_iso():
            return "2026-04-19T00:00:00Z"

        delegations_path = Path(path).parent / "delegations.json"
        tasks_helpers._make_deps(_db_conn, _now_iso, delegations_path)
        tasks_service._make_deps(_db_conn, _now_iso, Path(path).parent)

        # Stub hosting.deploy_project so auto-deploy never fires during
        # these tests — this PR is about parent closure, not deploy.
        def _noop_deploy(project_id, slug="", directory=""):
            return {"url": "", "slug": "", "directory": "", "status": "ok"}
        monkeypatch.setattr(
            tasks_service.hosting, "deploy_project", _noop_deploy,
        )

        yield tasks_service, tasks_helpers, path
    finally:
        os.unlink(path)


def _insert_task(path, *, task_id, status, parent_task_id=None,
                 project_id="proj-1", decompose=0, title="t"):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, area, project_id, status, "
            "priority, source, parent_task_id, decompose, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, title, "proyecto", project_id, status,
             "media", "niwa-app", parent_task_id, decompose,
             "2026-04-19T00:00:00Z", "2026-04-19T00:00:00Z"),
        )
        conn.commit()


# ────────────────────────── close_parent helper ─────────────────────────


class TestCloseParentHelper:
    """``tasks_helpers.close_parent_if_children_done`` is a pure SQL
    helper that both the backend and the executor invoke. It must:

      - Close the parent (``bloqueada → hecha``) only when **all**
        children are in a terminal state (``hecha``/``archivada``).
      - Be idempotent: re-running on an already-closed parent is a
        no-op.
      - Refuse to transition from non-``bloqueada`` statuses (e.g. a
        parent the user manually moved to ``pendiente``). This
        prevents the helper from overriding manual operator actions.
    """

    def test_closes_parent_when_all_children_done(self, tmp_db):
        _, tasks_helpers, path = tmp_db
        _insert_task(path, task_id="parent",  status="bloqueada")
        _insert_task(path, task_id="c1", status="hecha",
                     parent_task_id="parent")
        _insert_task(path, task_id="c2", status="hecha",
                     parent_task_id="parent")

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            closed = tasks_helpers.close_parent_if_children_done(
                conn, "parent", "2026-04-19T01:00:00Z",
            )
            conn.commit()
            row = conn.execute(
                "SELECT status, completed_at FROM tasks WHERE id='parent'"
            ).fetchone()
            events = conn.execute(
                "SELECT type, payload_json FROM task_events "
                "WHERE task_id='parent'"
            ).fetchall()

        assert closed is True
        assert row["status"] == "hecha"
        assert row["completed_at"] == "2026-04-19T01:00:00Z"
        types = {e["type"] for e in events}
        # Must record at least a status change; tests consumers of
        # the timeline (UI) rely on ``status_changed`` events.
        assert "status_changed" in types or "completed" in types
        # The source must be traceable so we can tell closure-driven
        # completions apart from manual ones in the timeline.
        payloads = [json.loads(e["payload_json"] or "{}") for e in events]
        combined = json.dumps(payloads)
        assert "planner_parent_closure" in combined

    def test_archivada_child_counts_as_terminal(self, tmp_db):
        _, tasks_helpers, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="hecha",
                     parent_task_id="parent")
        _insert_task(path, task_id="c2", status="archivada",
                     parent_task_id="parent")

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            closed = tasks_helpers.close_parent_if_children_done(
                conn, "parent", "2026-04-19T01:00:00Z",
            )
            conn.commit()
            status = conn.execute(
                "SELECT status FROM tasks WHERE id='parent'"
            ).fetchone()["status"]

        assert closed is True
        assert status == "hecha"

    def test_stays_bloqueada_when_child_pending(self, tmp_db):
        _, tasks_helpers, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="hecha",
                     parent_task_id="parent")
        _insert_task(path, task_id="c2", status="pendiente",
                     parent_task_id="parent")

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            closed = tasks_helpers.close_parent_if_children_done(
                conn, "parent", "2026-04-19T01:00:00Z",
            )
            conn.commit()
            status = conn.execute(
                "SELECT status FROM tasks WHERE id='parent'"
            ).fetchone()["status"]

        assert closed is False
        assert status == "bloqueada"

    def test_refuses_to_close_non_bloqueada_parent(self, tmp_db):
        """A parent the operator moved back to ``pendiente`` (manual
        intervention) must not be silently closed when its children
        happen to finish. Only ``bloqueada → hecha`` is allowed."""
        _, tasks_helpers, path = tmp_db
        _insert_task(path, task_id="parent", status="pendiente")
        _insert_task(path, task_id="c1", status="hecha",
                     parent_task_id="parent")

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            closed = tasks_helpers.close_parent_if_children_done(
                conn, "parent", "2026-04-19T01:00:00Z",
            )
            conn.commit()
            status = conn.execute(
                "SELECT status FROM tasks WHERE id='parent'"
            ).fetchone()["status"]

        assert closed is False
        assert status == "pendiente"

    def test_idempotent_on_already_hecha_parent(self, tmp_db):
        _, tasks_helpers, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="hecha",
                     parent_task_id="parent")

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            tasks_helpers.close_parent_if_children_done(
                conn, "parent", "2026-04-19T01:00:00Z",
            )
            conn.commit()
            # Second call on the now-hecha parent must be a no-op.
            closed2 = tasks_helpers.close_parent_if_children_done(
                conn, "parent", "2026-04-19T02:00:00Z",
            )
            conn.commit()

        assert closed2 is False

    def test_noop_for_parent_without_children(self, tmp_db):
        """A parent with zero children would otherwise satisfy "all
        children terminal" vacuously. That would close every
        ``bloqueada`` task in the DB whose id somebody happened to
        pass in. Require ``child_count > 0`` explicitly."""
        _, tasks_helpers, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            closed = tasks_helpers.close_parent_if_children_done(
                conn, "parent", "2026-04-19T01:00:00Z",
            )
            conn.commit()
            status = conn.execute(
                "SELECT status FROM tasks WHERE id='parent'"
            ).fetchone()["status"]

        assert closed is False
        assert status == "bloqueada"


# ────────────────────────── update_task wiring ──────────────────────────


class TestUpdateTaskWiresClosure:
    """When the UI (or any caller of ``tasks_service.update_task``)
    moves a child to ``hecha``, the parent must close once all
    siblings are terminal."""

    def test_last_child_to_hecha_closes_parent(self, tmp_db):
        tasks_service, _, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="hecha",
                     parent_task_id="parent")
        _insert_task(path, task_id="c2", status="en_progreso",
                     parent_task_id="parent")

        tasks_service.update_task("c2", {"status": "hecha"})

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            status = conn.execute(
                "SELECT status FROM tasks WHERE id='parent'"
            ).fetchone()["status"]
        assert status == "hecha"

    def test_non_last_child_keeps_parent_bloqueada(self, tmp_db):
        tasks_service, _, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="en_progreso",
                     parent_task_id="parent")
        _insert_task(path, task_id="c2", status="pendiente",
                     parent_task_id="parent")

        tasks_service.update_task("c1", {"status": "hecha"})

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            status = conn.execute(
                "SELECT status FROM tasks WHERE id='parent'"
            ).fetchone()["status"]
        assert status == "bloqueada"

    def test_closing_parent_does_not_reinvoke_autodeploy(
        self, tmp_db, monkeypatch,
    ):
        """The child's ``hecha`` transition already fires autodeploy
        for the project. The parent closure that follows must NOT
        re-deploy the same project — it's pure bookkeeping."""
        tasks_service, _, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="en_progreso",
                     parent_task_id="parent")

        calls = []

        def _spy(project_id, slug="", directory=""):
            calls.append(project_id)
            return {"url": "", "slug": "", "directory": "", "status": "ok"}

        monkeypatch.setattr(tasks_service.hosting, "deploy_project", _spy)

        tasks_service.update_task("c1", {"status": "hecha"})

        # Exactly one deploy (for the child's transition to hecha).
        # The parent closing must not trigger a second deploy.
        assert calls == ["proj-1"], (
            f"expected one deploy for child c1; got {calls!r}"
        )

    def test_status_change_not_to_hecha_does_not_close_parent(
        self, tmp_db,
    ):
        tasks_service, _, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="pendiente",
                     parent_task_id="parent")

        tasks_service.update_task("c1", {"status": "en_progreso"})

        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            status = conn.execute(
                "SELECT status FROM tasks WHERE id='parent'"
            ).fetchone()["status"]
        assert status == "bloqueada"


# ────────────────────────── child-count exposure ─────────────────────────


class TestChildCountInListAndDetail:
    """The UI renders a badge ``↳ N/M`` based on these counters. The
    API must include them in both the list and detail responses."""

    def test_fetch_tasks_exposes_child_counters(self, tmp_db):
        tasks_service, _, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="hecha",
                     parent_task_id="parent")
        _insert_task(path, task_id="c2", status="hecha",
                     parent_task_id="parent")
        _insert_task(path, task_id="c3", status="pendiente",
                     parent_task_id="parent")

        rows = tasks_service.fetch_tasks(include_done=True)
        parent = next(r for r in rows if r["id"] == "parent")
        assert parent["child_count_total"] == 3
        assert parent["child_count_done"] == 2

    def test_get_task_exposes_child_counters(self, tmp_db):
        tasks_service, _, path = tmp_db
        _insert_task(path, task_id="parent", status="bloqueada")
        _insert_task(path, task_id="c1", status="hecha",
                     parent_task_id="parent")
        _insert_task(path, task_id="c2", status="pendiente",
                     parent_task_id="parent")

        parent = tasks_service.get_task("parent")
        assert parent is not None
        assert parent["child_count_total"] == 2
        assert parent["child_count_done"] == 1

    def test_task_without_children_has_zero_counters(self, tmp_db):
        tasks_service, _, path = tmp_db
        _insert_task(path, task_id="solo", status="pendiente")

        # List form
        rows = tasks_service.fetch_tasks(include_done=True)
        solo_row = next(r for r in rows if r["id"] == "solo")
        assert solo_row["child_count_total"] == 0
        assert solo_row["child_count_done"] == 0

        # Detail form
        solo_detail = tasks_service.get_task("solo")
        assert solo_detail is not None
        assert solo_detail["child_count_total"] == 0
        assert solo_detail["child_count_done"] == 0


# ────────────────────────── decompose on create ─────────────────────────


class TestCreateTaskAcceptsDecompose:
    """The TaskForm checkbox posts ``decompose: 1`` to ``POST /api/tasks``.
    ``tasks_service.create_task`` must persist it; absent field must
    default to 0 to match the schema."""

    def test_create_task_persists_decompose_flag(self, tmp_db):
        tasks_service, _, path = tmp_db
        task_id = tasks_service.create_task({
            "title": "complex feature",
            "description": "...",
            "decompose": 1,
        })
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT decompose FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        assert row["decompose"] == 1

    def test_create_task_decompose_defaults_to_zero(self, tmp_db):
        tasks_service, _, path = tmp_db
        task_id = tasks_service.create_task({"title": "simple"})
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT decompose FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        assert row["decompose"] == 0

    def test_create_task_coerces_truthy_values(self, tmp_db):
        """The form sends ``1``/``0``; some callers (API clients) may
        send ``true``/``false``. Coerce anything truthy to 1."""
        tasks_service, _, path = tmp_db
        task_id = tasks_service.create_task({
            "title": "truthy",
            "decompose": True,
        })
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT decompose FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        assert row["decompose"] == 1


# ────────────────────────── executor wiring ──────────────────────────


def _load_executor(tmp_path, monkeypatch):
    """Load task-executor.py pointed at a fresh SQLite DB."""
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    db_path = niwa_home / "data" / "niwa.sqlite3"
    (niwa_home / "data").mkdir()
    (niwa_home / "secrets" / "mcp.env").write_text(
        f"NIWA_DB_PATH={db_path}\n"
    )
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))

    schema_sql = (DB_DIR / "schema.sql").read_text()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()

    spec = importlib.util.spec_from_file_location(
        f"task_executor_{uuid.uuid4().hex}",
        str(BIN_DIR / "task-executor.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, str(db_path)


class TestExecutorClosesParentOnFinish:
    """When the executor marks the LAST child ``hecha`` via
    ``_finish_task``, it must close the parent too. The executor does
    not go through ``tasks_service.update_task``; it writes directly
    to SQLite. The hook therefore has to live inside ``_finish_task``
    itself."""

    def _seed(self, db_path, *, parent_status="bloqueada",
              children_statuses=("pendiente",)):
        parent_id = f"parent-{uuid.uuid4().hex[:8]}"
        now = "2026-04-19T00:00:00Z"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO tasks (id, title, area, status, priority, "
                "source, created_at, updated_at) VALUES "
                "(?,?,?,?,?,?,?,?)",
                (parent_id, "parent", "proyecto", parent_status,
                 "media", "niwa-app", now, now),
            )
            children = []
            for i, s in enumerate(children_statuses):
                cid = f"c-{uuid.uuid4().hex[:8]}"
                conn.execute(
                    "INSERT INTO tasks (id, title, area, status, "
                    "priority, source, parent_task_id, "
                    "created_at, updated_at) VALUES "
                    "(?,?,?,?,?,?,?,?,?)",
                    (cid, f"child {i}", "proyecto", s, "media",
                     "planner", parent_id, now, now),
                )
                children.append(cid)
            conn.commit()
        return parent_id, children

    def test_finish_task_last_child_hecha_closes_parent(
        self, tmp_path, monkeypatch,
    ):
        mod, db_path = _load_executor(tmp_path, monkeypatch)
        parent_id, children = self._seed(
            db_path,
            children_statuses=("hecha", "en_progreso"),
        )
        last_child = children[1]

        mod._finish_task(last_child, "hecha", "child output")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            p = conn.execute(
                "SELECT status, completed_at FROM tasks WHERE id=?",
                (parent_id,),
            ).fetchone()
        assert p["status"] == "hecha"
        assert p["completed_at"] is not None

    def test_finish_task_non_last_child_keeps_parent_bloqueada(
        self, tmp_path, monkeypatch,
    ):
        mod, db_path = _load_executor(tmp_path, monkeypatch)
        parent_id, children = self._seed(
            db_path,
            children_statuses=("en_progreso", "pendiente"),
        )

        mod._finish_task(children[0], "hecha", "child output")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            p = conn.execute(
                "SELECT status FROM tasks WHERE id=?", (parent_id,),
            ).fetchone()
        assert p["status"] == "bloqueada"

    def test_finish_task_child_bloqueada_does_not_close_parent(
        self, tmp_path, monkeypatch,
    ):
        """A child failing (``bloqueada``) must NOT close the parent —
        the parent should stay blocked until the failure is resolved."""
        mod, db_path = _load_executor(tmp_path, monkeypatch)
        parent_id, children = self._seed(
            db_path,
            children_statuses=("en_progreso",),
        )

        mod._finish_task(children[0], "bloqueada", "failure")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            p = conn.execute(
                "SELECT status FROM tasks WHERE id=?", (parent_id,),
            ).fetchone()
        assert p["status"] == "bloqueada"

    def test_finish_task_no_parent_is_noop_for_closure(
        self, tmp_path, monkeypatch,
    ):
        """Tasks without ``parent_task_id`` never trigger the closure
        helper. This also prevents the helper from being invoked for
        every non-child task completion (performance + correctness)."""
        mod, db_path = _load_executor(tmp_path, monkeypatch)
        now = "2026-04-19T00:00:00Z"
        orphan_id = f"orphan-{uuid.uuid4().hex[:8]}"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO tasks (id, title, area, status, priority, "
                "source, created_at, updated_at) VALUES "
                "(?,?,?,?,?,?,?,?)",
                (orphan_id, "orphan", "proyecto", "en_progreso",
                 "media", "niwa-app", now, now),
            )
            conn.commit()

        # Must not raise even though there is no parent.
        mod._finish_task(orphan_id, "hecha", "output")

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            status = conn.execute(
                "SELECT status FROM tasks WHERE id=?", (orphan_id,),
            ).fetchone()["status"]
        assert status == "hecha"
