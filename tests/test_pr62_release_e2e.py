"""E2E tests for the release contract (PR-62).

The unit tests of PR-58..PR-61 each pin one piece. These E2E scenarios
chain them in the order an operator actually runs them in production,
so a regression can't hide between two passing unit tests.

Scenarios:

  1. install → create data → update → data intact.
  2. update → health fails → auto-revert → data intact (pre-update).
  3. update (with data) → niwa restore --from=<backup> → data == pre-update.
  4. reinstall same-mode (no --rotate-secrets) → secrets preserved.
  5. ``/api/version`` después de un update real surfaces last_update.

Runner/backup/health_check son inyectados para no depender de
docker/systemctl/network. La DB SÍ es real — ahí es donde queremos
blindar la fidelidad del round-trip.

Run: pytest tests/test_pr62_release_e2e.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request, urlopen

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
BIN_DIR = os.path.join(ROOT_DIR, "bin")
for p in (BACKEND_DIR, BIN_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import update_engine  # noqa: E402


# ── Shared helpers ──────────────────────────────────────────────────


class FakeRunner:
    def __init__(self):
        self.responses = []
        self.calls = []

    def on(self, prefix, *, returncode=0, stdout="", stderr=""):
        self.responses.append((prefix, SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr,
        )))

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        for prefix, resp in self.responses:
            if args[:len(prefix)] == prefix:
                return resp
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _clean_runner():
    r = FakeRunner()
    r.on(["git", "status", "--porcelain"], stdout="")
    r.on(["git", "rev-parse", "--abbrev-ref", "HEAD"], stdout="v0.2\n")
    r.on(["git", "rev-parse", "HEAD"], stdout="a" * 40 + "\n")
    r.on(["git", "pull", "origin", "v0.2"], stdout="updated\n")
    r.on(["git", "reset", "--hard"], returncode=0)
    r.on(["git", "checkout"], returncode=0)
    r.on(["docker", "compose"], returncode=0)
    r.on(["systemctl", "restart"], returncode=0)
    return r


def _install(tmp_path: Path) -> dict:
    install_dir = tmp_path / ".niwa"
    (install_dir / "bin").mkdir(parents=True)
    (install_dir / "bin" / "task-executor.py").write_text("# v0\n")
    (install_dir / "servers" / "tasks-mcp").mkdir(parents=True)
    (install_dir / "servers" / "tasks-mcp" / "server.py").write_text("# v0\n")
    (install_dir / "data").mkdir()
    (install_dir / "docker-compose.yml").write_text("version: '3'\n")
    (install_dir / "secrets").mkdir()
    (install_dir / "secrets" / "mcp.env").write_text("NIWA_APP_PORT=19099\n")
    repo_dir = tmp_path / "repo"
    (repo_dir / "bin").mkdir(parents=True)
    (repo_dir / "bin" / "task-executor.py").write_text("# v1\n")
    (repo_dir / "servers" / "tasks-mcp").mkdir(parents=True)
    (repo_dir / "servers" / "tasks-mcp" / "server.py").write_text("# v1\n")
    return {"install_dir": install_dir, "repo_dir": repo_dir}


def _seed_real_db(install_dir: Path) -> Path:
    """Create a SQLite DB with representative data so the round-trip
    assertions have something to check."""
    db_path = install_dir / "data" / "niwa.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE tasks (id TEXT PRIMARY KEY, project_id TEXT, title TEXT);
    """)
    conn.execute("INSERT INTO projects VALUES ('p1', 'alpha')")
    conn.execute("INSERT INTO projects VALUES ('p2', 'beta')")
    conn.execute("INSERT INTO tasks VALUES ('t1', 'p1', 'one')")
    conn.execute("INSERT INTO tasks VALUES ('t2', 'p1', 'two')")
    conn.execute("INSERT INTO tasks VALUES ('t3', 'p2', 'three')")
    conn.commit()
    conn.close()
    return db_path


def _read_state(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    projects = sorted(conn.execute("SELECT id, name FROM projects").fetchall())
    tasks = sorted(conn.execute(
        "SELECT id, project_id, title FROM tasks"
    ).fetchall())
    conn.close()
    return {"projects": projects, "tasks": tasks}


# ── E2E 1: install → data → update → data intact ───────────────────


def test_e2e_update_preserves_existing_data(tmp_path, monkeypatch):
    inst = _install(tmp_path)
    db_path = _seed_real_db(inst["install_dir"])
    before = _read_state(db_path)
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))

    r = _clean_runner()
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=lambda ctx: True,
        timestamp="20260417-e2e-1",
    )
    assert manifest["success"] is True, manifest
    # Data survives.
    after = _read_state(db_path)
    assert after == before
    # Backup file was created.
    assert Path(manifest["backup_path"]).exists()
    # Executor + MCP got updated in place.
    assert (inst["install_dir"] / "bin" / "task-executor.py").read_text() == "# v1\n"


# ── E2E 2: update → health fails → auto-revert → data pre-update ───


def test_e2e_failed_update_auto_reverts_data(tmp_path, monkeypatch):
    inst = _install(tmp_path)
    db_path = _seed_real_db(inst["install_dir"])
    before = _read_state(db_path)
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))

    # Simulate migration dirtying the DB mid-update — we just mutate
    # the live DB between the backup and the health-check to emulate
    # "schema migrated, data moved, health-check fails".
    mutated = {"done": False}

    def _health(ctx):
        # First call = post-update health-check: simulate the update
        # having mutated the DB mid-migration. Returns False to
        # trigger the auto-revert.
        # Second call = post-revert health-check: DB is already
        # restored from backup, no more mutation. We return True so
        # the engine records ``reverted=True``.
        if not mutated["done"]:
            conn = sqlite3.connect(str(db_path))
            conn.execute("DELETE FROM tasks WHERE id='t1'")
            conn.execute("INSERT INTO tasks VALUES ('t-new', 'p1', 'inserted-by-fail')")
            conn.commit()
            conn.close()
            mutated["done"] = True
            return False
        return True

    r = _clean_runner()
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=_health,
        timestamp="20260417-e2e-2",
    )
    # Health failed → auto-revert runs → recovery health-check ok.
    assert manifest["success"] is False, manifest
    assert manifest["reverted"] is True
    after = _read_state(db_path)
    assert after == before, (
        "auto-revert must restore the DB to its pre-update state"
    )


# ── E2E 3: backup + niwa restore round-trip ─────────────────────────


def test_e2e_restore_from_backup_round_trip(tmp_path, monkeypatch):
    inst = _install(tmp_path)
    db_path = _seed_real_db(inst["install_dir"])
    before = _read_state(db_path)
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))

    # Use the engine's own backup fn to be faithful.
    from types import SimpleNamespace as NS
    mock_ctx = NS(install_dir=inst["install_dir"], timestamp="20260417-bkp-3")
    backup_path = update_engine._default_backup(mock_ctx)  # type: ignore
    assert backup_path

    # Mutate the "live" DB to simulate drift.
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM tasks")
    conn.execute("INSERT INTO tasks VALUES ('wrong', 'p1', 'should-go-away')")
    conn.commit()
    conn.close()

    # Seed the update-log so restore finds the entry.
    log = inst["install_dir"] / "data" / "update-log.json"
    log.write_text(json.dumps([{
        "timestamp": "20260417-bkp-3",
        "success": True,
        "reverted": False,
        "branch": "v0.2",
        "before_commit": "b" * 40,
        "after_commit": "c" * 40,
        "backup_path": backup_path,
        "errors": [], "warnings": [],
        "duration_seconds": 10.0,
    }]))

    r = _clean_runner()
    manifest = update_engine.perform_restore(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        backup_path=backup_path,
        runner=r, printer=lambda *a, **k: None,
        db_only=True,  # skip the git checkout dance
        health_check_fn=lambda ctx: True,
    )
    assert manifest["success"] is True
    assert _read_state(db_path) == before


# ── E2E 4: reinstall same-mode preserves secrets ────────────────────


def test_e2e_reinstall_preserves_secrets(tmp_path, monkeypatch):
    """Load setup.py and invoke ``build_quick_config`` twice: the
    second call (with an existing mcp.env on disk) must keep the
    tokens + password from the first run."""
    import importlib.util
    setup_py = Path(ROOT_DIR, "setup.py")
    spec = importlib.util.spec_from_file_location("niwa_setup_e2e", str(setup_py))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "detect_docker",
                        lambda: {"available": True, "version": "fake"})
    monkeypatch.setattr(mod, "detect_socket_path",
                        lambda: "/var/run/docker.sock")

    niwa_home = tmp_path / ".niwa"
    args1 = SimpleNamespace(
        mode="core", bind="localhost", dir=str(niwa_home),
        instance=None, admin_user=None, admin_password=None,
        public_url=None, rotate_secrets=False, force=False,
    )
    cfg1 = mod.build_quick_config(args1)
    # Persist the secrets as the real installer would.
    (niwa_home / "secrets").mkdir(parents=True, exist_ok=True)
    (niwa_home / "secrets" / "mcp.env").write_text(
        f'NIWA_LOCAL_TOKEN="{cfg1.tokens["NIWA_LOCAL_TOKEN"]}"\n'
        f'NIWA_REMOTE_TOKEN="{cfg1.tokens["NIWA_REMOTE_TOKEN"]}"\n'
        f'MCP_GATEWAY_AUTH_TOKEN="{cfg1.tokens["MCP_GATEWAY_AUTH_TOKEN"]}"\n'
        f'NIWA_APP_USERNAME="{cfg1.username}"\n'
        f'NIWA_APP_PASSWORD="{cfg1.password}"\n'
        f'NIWA_APP_SESSION_SECRET="{cfg1.tokens["NIWA_APP_SESSION_SECRET"]}"\n'
    )

    args2 = SimpleNamespace(**args1.__dict__)
    cfg2 = mod.build_quick_config(args2)
    assert cfg2.tokens["NIWA_LOCAL_TOKEN"] == cfg1.tokens["NIWA_LOCAL_TOKEN"]
    assert cfg2.password == cfg1.password
    assert cfg2.tokens["NIWA_APP_SESSION_SECRET"] == cfg1.tokens["NIWA_APP_SESSION_SECRET"]

    # And rotating DOES change them (guard against inverting the fix).
    args3 = SimpleNamespace(**{**args1.__dict__, "rotate_secrets": True})
    cfg3 = mod.build_quick_config(args3)
    assert cfg3.tokens["NIWA_LOCAL_TOKEN"] != cfg1.tokens["NIWA_LOCAL_TOKEN"]
    assert cfg3.password != cfg1.password


# ── E2E 5: /api/version surfaces last_update after a real run ──────


@pytest.fixture
def app_server(tmp_path, monkeypatch):
    db_path = str(tmp_path / "niwa.sqlite3")
    niwa_home = tmp_path / "home"
    (niwa_home / "data").mkdir(parents=True)
    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_APP_HOST", "127.0.0.1")
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))
    monkeypatch.delitem(sys.modules, "app", raising=False)
    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    c = sqlite3.connect(db_path)
    c.executescript(schema_sql)
    c.commit()
    c.close()
    import app
    app.DB_PATH = Path(db_path)

    import socket as _s
    with _s.socket() as s:
        s.bind(("", 0))
        port = s.getsockname()[1]
    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urlopen(f"{base}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    yield {"base": base, "niwa_home": niwa_home}
    srv.shutdown()
    srv.server_close()


def test_e2e_version_endpoint_reflects_engine_run(app_server, tmp_path):
    inst = _install(tmp_path / "i")
    # Point the engine log at the ``NIWA_HOME`` the app is reading.
    engine_inst = app_server["niwa_home"]
    (engine_inst / "bin").mkdir(exist_ok=True)
    (engine_inst / "bin" / "task-executor.py").write_text("# placeholder\n")
    (engine_inst / "servers" / "tasks-mcp").mkdir(parents=True, exist_ok=True)
    (engine_inst / "servers" / "tasks-mcp" / "server.py").write_text("# placeholder\n")
    (engine_inst / "docker-compose.yml").write_text("version: '3'\n")
    (engine_inst / "secrets").mkdir(exist_ok=True)
    (engine_inst / "secrets" / "mcp.env").write_text("NIWA_APP_PORT=19099\n")

    r = _clean_runner()
    manifest = update_engine.perform_update(
        install_dir=engine_inst, repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=lambda ctx: True,
        timestamp="20260417-e2e-5",
    )
    assert manifest["success"] is True

    with urlopen(f"{app_server['base']}/api/version", timeout=5) as resp:
        data = json.loads(resp.read())
    assert "last_update" in data
    lu = data["last_update"]
    assert lu is not None
    assert lu["timestamp"] == "20260417-e2e-5"
    assert lu["success"] is True
