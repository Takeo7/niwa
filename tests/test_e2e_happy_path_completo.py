"""E2E happy path smoke test (PR-D1, Hito D) — wires the post-install
happy path from ``docs/MVP-ROADMAP.md §1``: install-state DB +
setup-token Claude mock → task with ``autonomy_mode=dangerous`` +
``decompose=1`` → planner creates 3 children → children close without
approval → auto-deploy fires → parent closes → ``product_healthcheck``
strikes to 3 → ``improve:stability`` adds a follow-up task. All
adapters faked; no executor loop, no HTTP server, no Caddy reload."""
from __future__ import annotations

import glob
import importlib
import importlib.util
import re
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.error import URLError

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
BIN_DIR = REPO_ROOT / "bin"
DB_DIR = REPO_ROOT / "niwa-app" / "db"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"

for _p in (BACKEND_DIR, BIN_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _apply_sql_idempotent(conn: sqlite3.Connection, sql: str) -> None:
    """Mirror ``app.py._apply_sql_idempotent`` — skip ADD COLUMN when the
    column already exists, ignore explicit BEGIN/COMMIT, strip
    comment-only lines."""
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
        if re.match(
            r"(BEGIN|COMMIT|END|ROLLBACK)(\s+(TRANSACTION|WORK))?\s*$",
            stmt, re.IGNORECASE,
        ):
            continue
        m = re.match(
            r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
            stmt, re.IGNORECASE,
        )
        if m:
            table, column = m.group(1), m.group(2)
            existing = {
                r[1] for r in conn.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()
            }
            if column in existing:
                continue
        conn.execute(stmt)
    conn.commit()


_FIXED_NOW = "2026-04-19T00:00:00+00:00"


def _now_iso_fixed() -> str:
    return _FIXED_NOW


@pytest.fixture
def fresh_niwa(tmp_path, monkeypatch):
    """Post-install state: tmp ``NIWA_HOME`` + schema + every migration
    + admin creds in env. Does NOT run ``setup.py``."""
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "data").mkdir()
    (niwa_home / "logs").mkdir()
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    db_path = niwa_home / "data" / "niwa.sqlite3"

    monkeypatch.setenv("NIWA_APP_USERNAME", "admin")
    monkeypatch.setenv("NIWA_APP_PASSWORD", "test-admin-pw")
    monkeypatch.setenv("NIWA_APP_SESSION_SECRET", "test-secret-not-real")
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))
    monkeypatch.setenv("NIWA_PROJECTS_ROOT", str(projects_root))
    monkeypatch.setenv("YUME_BASE", str(niwa_home))
    # Keep auto-deploy default (on); _DeploySpy intercepts the real call.
    monkeypatch.delenv("NIWA_DEPLOY_ON_TASK_SUCCESS", raising=False)

    # bin/task-executor.py's _resolve_install_dir requires mcp.env.
    (niwa_home / "secrets" / "mcp.env").write_text(
        f"NIWA_DB_PATH={db_path}\n"
        f"NIWA_PROJECTS_ROOT={projects_root}\n",
    )

    with sqlite3.connect(str(db_path)) as conn:
        _apply_sql_idempotent(
            conn, (DB_DIR / "schema.sql").read_text(encoding="utf-8"),
        )
        for mig in sorted(glob.glob(str(DB_DIR / "migrations" / "*.sql"))):
            _apply_sql_idempotent(conn, Path(mig).read_text(encoding="utf-8"))

    # Snapshot+restore sys.modules so re-imported modules with our
    # tmp-path bindings don't leak into later tests (caused
    # order-dependent failures in test_hosting_* during development).
    _dirty = ("tasks_service", "tasks_helpers", "hosting", "scheduler",
              "capability_service", "task_executor_d1")
    _snapshot = {k: sys.modules.get(k) for k in _dirty}

    try:
        yield {
            "home": niwa_home,
            "db_path": db_path,
            "projects_root": projects_root,
        }
    finally:
        for k, v in _snapshot.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _db_conn_fn(db_path: Path):
    def _f():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA foreign_keys=ON")
        except sqlite3.OperationalError:
            pass
        return c
    return _f


class _DeploySpy:
    """Stand-in for ``hosting.deploy_project``; records calls, no I/O."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, project_id, slug="", directory=""):
        self.calls.append((project_id, slug, directory))
        return {
            "url": f"http://localhost:8880/{slug or project_id}/",
            "slug": slug or "auto",
            "directory": directory or "",
            "status": "active",
        }


def _always_fails(url, timeout=5):
    raise URLError("connection refused (stub)")


def test_happy_path_completo(fresh_niwa, monkeypatch):
    """Happy path MVP end-to-end; each ``--- Phase N ---`` marker below
    mirrors a step of ``docs/MVP-ROADMAP.md §1``."""
    db_path = fresh_niwa["db_path"]
    projects_root = fresh_niwa["projects_root"]
    conn_fn = _db_conn_fn(db_path)

    # --- Phase 1: install-state sanity check ---
    with conn_fn() as c:
        tables = {
            r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    for required in ("projects", "tasks", "deployments",
                     "routines", "oauth_tokens"):
        assert required in tables, f"fresh install missing table: {required}"

    # --- Phase 2: setup-token Claude mock persisted ---
    # PR-A6's AuthPanel persists subscription tokens in oauth_tokens.
    with conn_fn() as c:
        c.execute(
            "INSERT INTO oauth_tokens (provider, access_token, "
            "refresh_token, expires_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("claude_subscription", "fake-setup-token-abc", "",
             None, _FIXED_NOW, _FIXED_NOW),
        )
        c.commit()
    monkeypatch.setenv(
        "NIWA_LLM_COMMAND_CLAUDE",
        f"python3 {FIXTURES_DIR / 'fake_claude.py'} "
        f"-p --output-format stream-json",
    )
    monkeypatch.setenv(
        "NIWA_LLM_COMMAND_PLANNER",
        f"python3 {FIXTURES_DIR / 'fake_planner.py'}",
    )

    with conn_fn() as c:
        token_row = c.execute(
            "SELECT provider, access_token FROM oauth_tokens "
            "WHERE provider='claude_subscription'"
        ).fetchone()
    assert token_row is not None
    assert token_row["access_token"].startswith("fake-setup-token")

    # --- Phase 3: project (autonomy_mode=dangerous) + parent task ---
    # ``autonomy_mode='dangerous'`` bypasses the approval gate
    # (capability_service:416). ``decompose=1`` opts the task into the
    # planner tier at executor pickup time.
    project_id = "proj-e2e-d1"
    project_dir = projects_root / "hello-world"
    project_dir.mkdir()
    with conn_fn() as c:
        c.execute(
            "INSERT INTO projects (id, slug, name, area, description,"
            " active, created_at, updated_at, directory, autonomy_mode)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (project_id, "hello-world", "Hello World", "proyecto",
             "E2E smoke project", 1, _FIXED_NOW, _FIXED_NOW,
             str(project_dir), "dangerous"),
        )
        c.commit()

    # Re-import service modules so _make_deps binds to this fixture's
    # conn_fn/now_iso, not whatever a previous test left wired.
    for name in ("tasks_service", "tasks_helpers", "hosting"):
        sys.modules.pop(name, None)
    import hosting  # noqa: F401
    import tasks_helpers
    import tasks_service
    tasks_helpers._make_deps(
        conn_fn, _now_iso_fixed, db_path.parent / "delegations.json",
    )
    tasks_service._make_deps(conn_fn, _now_iso_fixed, db_path.parent)

    parent_id = tasks_service.create_task({
        "title": "Build a hello world in Python with tests",
        "description": "Happy path MVP smoke — hello world with tests.",
        "project_id": project_id,
        "decompose": True,
        "area": "proyecto",
    })
    with conn_fn() as c:
        parent_row = c.execute(
            "SELECT decompose, project_id, status "
            "FROM tasks WHERE id=?", (parent_id,),
        ).fetchone()
    assert parent_row is not None
    assert parent_row["decompose"] == 1
    assert parent_row["project_id"] == project_id
    assert parent_row["status"] == "pendiente"

    # Autonomy flag reachable from the approval-gate code path
    # (capability_service.py:138-148 merges projects.autonomy_mode).
    import capability_service
    with conn_fn() as c:
        profile = capability_service.get_effective_profile(project_id, c)
    assert profile["autonomy_mode"] == "dangerous"

    # --- Phase 4: planner tier — subprocess → parse → create_subtasks ---
    planner_proc = subprocess.run(
        ["python3", str(FIXTURES_DIR / "fake_planner.py")],
        input="decompose: build hello world",
        capture_output=True, text=True, timeout=5, check=True,
    )
    planner_output = planner_proc.stdout
    assert "<SUBTASKS>" in planner_output
    assert "</SUBTASKS>" in planner_output

    spec = importlib.util.spec_from_file_location(
        "task_executor_d1", str(BIN_DIR / "task-executor.py"),
    )
    te_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(te_mod)

    # close_parent_if_children_done only fires on parent.status=bloqueada
    # — mirror what _handle_task_result does after a planner split.
    tasks_service.update_task(parent_id, {"status": "en_progreso"})
    tasks_service.update_task(parent_id, {"status": "bloqueada"})

    assert te_mod._should_run_planner({
        "id": parent_id,
        "parent_task_id": None,
        "decompose": 1,
        "description": "short",
    }) is True
    subs = te_mod._parse_planner_output(planner_output)
    assert subs is not None
    assert len(subs) == 3
    count = te_mod._create_subtasks(
        {"id": parent_id, "project_id": project_id}, subs,
    )
    assert count == 3

    with conn_fn() as c:
        children = [
            dict(r) for r in c.execute(
                "SELECT id, status, project_id, parent_task_id, source "
                "FROM tasks WHERE parent_task_id=? ORDER BY created_at",
                (parent_id,),
            ).fetchall()
        ]
    assert len(children) == 3
    for child in children:
        assert child["parent_task_id"] == parent_id
        assert child["project_id"] == project_id
        assert child["status"] == "pendiente"
        assert child["source"] == "planner"

    # --- Phase 5 + 6: children execute w/o approval, auto-deploy fires ---
    # Patch after tasks_service import so _maybe_autodeploy resolves
    # tasks_service.hosting.deploy_project to the spy.
    spy = _DeploySpy()
    monkeypatch.setattr(tasks_service.hosting, "deploy_project", spy)

    for child in children:
        tasks_service.update_task(child["id"], {"status": "en_progreso"})
        tasks_service.update_task(child["id"], {"status": "hecha"})

    # Auto-deploy fires once per child's transition to hecha (PR-C1).
    assert len(spy.calls) == len(children), (
        f"auto-deploy expected {len(children)} calls, got {len(spy.calls)}"
    )
    for call in spy.calls:
        assert call[0] == project_id

    # Parent closed automatically by close_parent_if_children_done (PR-B4b).
    with conn_fn() as c:
        parent_after = c.execute(
            "SELECT status, completed_at FROM tasks WHERE id=?",
            (parent_id,),
        ).fetchone()
    assert parent_after["status"] == "hecha"
    assert parent_after["completed_at"] is not None

    # --- Phase 7: product_healthcheck — 3 strikes creates fix task ---
    deploy_id = str(uuid.uuid4())
    with conn_fn() as c:
        c.execute(
            "INSERT INTO deployments (id, project_id, slug, directory, "
            "url, status, deployed_at, updated_at) VALUES "
            "(?,?,?,?,?,?,?,?)",
            (deploy_id, project_id, "hello-world", str(project_dir),
             "http://stub.invalid/", "active", _FIXED_NOW, _FIXED_NOW),
        )
        c.commit()

    sys.modules.pop("scheduler", None)
    import scheduler
    importlib.reload(scheduler)

    for _ in range(3):
        scheduler.check_deployments_health(
            conn_fn, opener=_always_fails, timeout_seconds=1,
        )

    with conn_fn() as c:
        cf = c.execute(
            "SELECT consecutive_failures FROM deployments WHERE id=?",
            (deploy_id,),
        ).fetchone()["consecutive_failures"]
        hc_tasks = c.execute(
            "SELECT id, source, project_id, status FROM tasks "
            "WHERE source='routine:product_healthcheck'"
        ).fetchall()
    assert cf == 3, f"expected strikes=3, got {cf}"
    assert len(hc_tasks) == 1, (
        f"expected 1 healthcheck fix task, got {len(hc_tasks)}"
    )
    assert hc_tasks[0]["project_id"] == project_id
    assert hc_tasks[0]["status"] == "pendiente"

    # --- Phase 8: improve:stability — routine creates follow-up task ---
    msg, success = scheduler._exec_improve(
        {"project_id": project_id}, "stability", conn_fn,
    )
    assert success is True, f"improve:stability failed: {msg}"
    assert "Task created:" in msg

    with conn_fn() as c:
        improve_tasks = c.execute(
            "SELECT id, source, project_id, status, description "
            "FROM tasks WHERE source='routine:improve:stability'"
        ).fetchall()
    assert len(improve_tasks) == 1, (
        f"expected 1 improve:stability task, got {len(improve_tasks)}"
    )
    t = improve_tasks[0]
    assert t["project_id"] == project_id
    assert t["status"] == "pendiente"
    # Template substitution landed (scheduler.py:428-433).
    assert "pytest/vitest" in t["description"]
    assert str(project_dir) in t["description"]
