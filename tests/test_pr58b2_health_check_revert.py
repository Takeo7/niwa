"""Tests for PR-58b2 — health-check post-update + auto-revert +
update log exposed in /api/version.

Pins the contract of the auto-revert so a future refactor can't
silently regress the "recover or tell me loud" promise:

  * health-check OK → ``success=True, reverted=False``.
  * health-check fails, revert ok → ``success=False, reverted=True``.
  * health-check fails, revert also fails → ``success=False,
    reverted=False``, loud error in manifest.
  * update-log.json is written after every attempt (including
    aborted short-circuits).
  * /api/version surfaces ``last_update`` from the log.

Run: pytest tests/test_pr58b2_health_check_revert.py -v
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
from urllib.error import HTTPError

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
BIN_DIR = os.path.join(ROOT_DIR, "bin")
for p in (BACKEND_DIR, BIN_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import update_engine  # noqa: E402


class FakeRunner:
    def __init__(self) -> None:
        self.responses: list[tuple[list[str], SimpleNamespace]] = []
        self.calls: list[list[str]] = []

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


def _clean_runner() -> FakeRunner:
    r = FakeRunner()
    r.on(["git", "status", "--porcelain"], stdout="")
    r.on(["git", "rev-parse", "--abbrev-ref", "HEAD"], stdout="v0.2\n")
    r.on(["git", "rev-parse", "HEAD"], stdout="a" * 40 + "\n")
    r.on(["git", "pull", "origin", "v0.2"], stdout="updated\n")
    r.on(["git", "reset", "--hard"], returncode=0)
    r.on(["docker", "compose"], returncode=0)
    r.on(["systemctl", "restart"], returncode=0)
    return r


def _install(tmp_path: Path) -> dict:
    install_dir = tmp_path / ".niwa"
    (install_dir / "bin").mkdir(parents=True)
    (install_dir / "bin" / "task-executor.py").write_text("# old\n")
    (install_dir / "servers" / "tasks-mcp").mkdir(parents=True)
    (install_dir / "servers" / "tasks-mcp" / "server.py").write_text("# old\n")
    (install_dir / "data").mkdir()
    (install_dir / "docker-compose.yml").write_text("version: '3'\n")
    (install_dir / "secrets").mkdir()
    (install_dir / "secrets" / "mcp.env").write_text("NIWA_APP_PORT=19099\n")
    repo_dir = tmp_path / "repo"
    (repo_dir / "bin").mkdir(parents=True)
    (repo_dir / "bin" / "task-executor.py").write_text("# new\n")
    (repo_dir / "servers" / "tasks-mcp").mkdir(parents=True)
    (repo_dir / "servers" / "tasks-mcp" / "server.py").write_text("# new\n")
    return {"install_dir": install_dir, "repo_dir": repo_dir}


# ── Health-check OK → normal success ────────────────────────────────


def test_health_check_ok_marks_success_and_no_revert(tmp_path):
    inst = _install(tmp_path)
    r = _clean_runner()
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: "/tmp/bkp.sqlite3",
        health_check_fn=lambda ctx: True,
    )
    assert manifest["success"] is True
    assert manifest["reverted"] is False
    assert manifest["health_check_ok"] is True


# ── Health-check fails, revert runs ────────────────────────────────


def test_health_check_fail_triggers_revert(tmp_path):
    inst = _install(tmp_path)
    r = _clean_runner()
    # First health-check (post-update) fails; post-revert succeeds.
    health_calls = []

    def _health(ctx):
        health_calls.append(len(health_calls) + 1)
        # Attempt 1 = post-update → fail. Attempt 2 = post-revert → ok.
        return len(health_calls) > 1

    # Create a real backup file so _restore_db doesn't fail.
    bkp = tmp_path / "bkp.sqlite3"
    bkp.write_text("fake-backup")

    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: str(bkp),
        health_check_fn=_health,
    )
    assert manifest["success"] is False
    assert manifest["reverted"] is True
    # Revert ran git reset --hard <before_commit>.
    assert any(
        c[:3] == ["git", "reset", "--hard"] for c in r.calls
    ), r.calls


def test_health_check_fail_and_revert_also_fails_leaves_loud_error(tmp_path):
    inst = _install(tmp_path)
    r = _clean_runner()
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: None,  # no backup → restore_db skipped
        health_check_fn=lambda ctx: False,  # always fails
    )
    assert manifest["success"] is False
    assert manifest["reverted"] is False
    # Operator-facing message must mention manual intervention.
    joined = " ".join(manifest["errors"])
    assert "manual" in joined.lower() or "intervención" in joined.lower()


# ── update-log.json is written even on short-circuits ───────────────


def test_update_log_records_dirty_abort(tmp_path):
    inst = _install(tmp_path)
    r = FakeRunner()
    r.on(["git", "status", "--porcelain"], stdout=" M setup.py\n")
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: "should-not-run",
        health_check_fn=lambda ctx: True,
    )
    log_path = inst["install_dir"] / "data" / "update-log.json"
    assert log_path.exists(), "short-circuit must still write the log"
    entries = json.loads(log_path.read_text())
    assert len(entries) == 1
    assert entries[0]["success"] is False
    assert any("cambios locales" in e for e in entries[0]["errors"])


def test_update_log_keeps_at_most_20_entries(tmp_path):
    inst = _install(tmp_path)
    log_path = inst["install_dir"] / "data" / "update-log.json"
    # Seed 25 old entries.
    log_path.write_text(json.dumps([{"i": i} for i in range(25)]))
    r = _clean_runner()
    update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: None,
        health_check_fn=lambda ctx: True,
    )
    entries = json.loads(log_path.read_text())
    assert len(entries) == 20, "log must retain only the latest 20"
    assert entries[-1].get("success") is True  # new entry is at the end


def test_update_log_tolerates_corrupt_existing_file(tmp_path):
    inst = _install(tmp_path)
    log_path = inst["install_dir"] / "data" / "update-log.json"
    log_path.write_text("{not valid json")
    r = _clean_runner()
    update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: None,
        health_check_fn=lambda ctx: True,
    )
    # Log was rebuilt from scratch; parsing must now succeed.
    entries = json.loads(log_path.read_text())
    assert len(entries) == 1


# ── /api/version surfaces the last entry ────────────────────────────


def _free_port():
    import socket as _s
    with _s.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def app_server(tmp_path, monkeypatch):
    db_path = str(tmp_path / "niwa.sqlite3")
    niwa_home = tmp_path / "home"
    (niwa_home / "data").mkdir(parents=True)
    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_APP_HOST", "127.0.0.1")
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))

    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    c = sqlite3.connect(db_path)
    c.executescript(schema_sql)
    c.commit()
    c.close()

    # Fresh module each fixture (review P1): reusing ``sys.modules['app']``
    # between tests pins module-level state (cached DB_PATH, globals,
    # _REMOTE_COMMIT_CACHE) that poisons the next run. Drop it so each
    # test gets a clean app import with its own tmp DB.
    monkeypatch.delitem(sys.modules, "app", raising=False)
    import app  # type: ignore
    app.DB_PATH = Path(db_path)

    port = _free_port()
    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
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


def test_api_version_exposes_last_update_entry(app_server):
    """When the engine has written an entry, /api/version surfaces
    it so the UI can render a "last update: ok / reverted / failed"
    banner without parsing the log itself."""
    log_path = app_server["niwa_home"] / "data" / "update-log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps([{
        "timestamp": "20260417-120000",
        "success": True,
        "reverted": False,
        "branch": "v0.2",
        "before_commit": "a" * 40,
        "after_commit": "b" * 40,
        "backup_path": "/tmp/whatever.sqlite3",
        "errors": [],
        "warnings": [],
        "duration_seconds": 42.0,
    }]))

    req = Request(f"{app_server['base']}/api/version")
    with urlopen(req, timeout=5) as r:
        out = json.loads(r.read())
    assert "last_update" in out
    assert out["last_update"]["success"] is True
    assert out["last_update"]["branch"] == "v0.2"
    assert out["last_update"]["after_commit"].startswith("bbbb")


def test_api_version_last_update_none_when_no_log(app_server):
    req = Request(f"{app_server['base']}/api/version")
    with urlopen(req, timeout=5) as r:
        out = json.loads(r.read())
    assert "last_update" in out
    assert out["last_update"] is None
