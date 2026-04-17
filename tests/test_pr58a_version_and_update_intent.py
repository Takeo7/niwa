"""Tests for PR-58a — enriched /api/version + action-intent /api/system/update
+ repo-dirty guard in CLI update + decision docs.

Run: pytest tests/test_pr58a_version_and_update_intent.py -v
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _free_port():
    import socket as _s
    with _s.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _req(base, path, *, method="GET", body=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{base}{path}", data=data, headers=h, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"raw": raw.decode("utf-8", errors="ignore")}


@pytest.fixture
def app_server(tmp_path, monkeypatch):
    import sqlite3 as _sq
    db_path = str(tmp_path / "niwa.sqlite3")
    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_APP_HOST", "127.0.0.1")
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))

    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    _c = _sq.connect(db_path)
    _c.executescript(schema_sql)
    _c.commit()
    _c.close()

    if "app" in sys.modules:
        import app
        app.DB_PATH = Path(db_path)
    else:
        import app

    port = _free_port()
    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urlopen(f"{base}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    yield {"base": base, "app": app, "db": db_path, "tmp": tmp_path}
    srv.shutdown()
    srv.server_close()


# ── /api/version enriched ────────────────────────────────────────────


def test_version_endpoint_returns_enriched_shape(app_server, monkeypatch):
    """All PR-58a fields present, even when there's no repo to probe.
    The endpoint must not crash on a fresh install without a git
    checkout — just return ``None`` for repo fields."""
    import app as app_mod
    monkeypatch.setattr(app_mod, "_discover_repo_dir", lambda: None)
    status, out = _req(app_server["base"], "/api/version")
    assert status == 200
    # Mandatory keys — future breakage of this contract should be loud.
    for key in (
        "version", "name", "branch", "commit", "commit_short",
        "latest_remote_commit", "needs_update", "schema_version",
        "repo_dirty", "last_backup_path", "last_backup_at", "needs_restart",
    ):
        assert key in out, f"missing {key} in /api/version response"
    assert out["branch"] is None
    assert out["commit"] is None
    assert out["needs_update"] is False
    assert out["repo_dirty"] is False


def test_version_endpoint_with_mocked_repo(app_server, monkeypatch):
    """Happy path: all fields populated from ``_git`` calls. We patch
    the helpers directly to avoid depending on a real .git state."""
    import app as app_mod
    fake_repo = app_server["tmp"] / "fake-repo"
    fake_repo.mkdir()
    monkeypatch.setattr(app_mod, "_discover_repo_dir", lambda: fake_repo)

    def _fake_git(repo, *args, timeout=10):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "v0.2"
        if args[:2] == ("rev-parse", "HEAD"):
            return "abcdef1234567890" + "0" * 24
        if args[:2] == ("status", "--porcelain"):
            return ""  # clean
        return None

    monkeypatch.setattr(app_mod, "_git", _fake_git)
    monkeypatch.setattr(
        app_mod, "_latest_remote_commit", lambda repo, branch, ttl=60.0: "f" * 40,
    )

    status, out = _req(app_server["base"], "/api/version")
    assert status == 200
    assert out["branch"] == "v0.2"
    assert out["commit"].startswith("abcdef")
    assert out["commit_short"] == "abcdef123456"
    assert out["latest_remote_commit"] == "f" * 40
    assert out["needs_update"] is True
    assert out["repo_dirty"] is False


def test_version_detects_dirty_repo(app_server, monkeypatch):
    import app as app_mod
    fake_repo = app_server["tmp"] / "fake-repo"
    fake_repo.mkdir()
    monkeypatch.setattr(app_mod, "_discover_repo_dir", lambda: fake_repo)

    def _fake_git(repo, *args, timeout=10):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "v0.2"
        if args[:2] == ("rev-parse", "HEAD"):
            return "a" * 40
        if args[:2] == ("status", "--porcelain"):
            return " M some-file.py"  # dirty marker
        return None

    monkeypatch.setattr(app_mod, "_git", _fake_git)
    monkeypatch.setattr(
        app_mod, "_latest_remote_commit", lambda *a, **kw: "a" * 40,
    )

    status, out = _req(app_server["base"], "/api/version")
    assert status == 200
    assert out["repo_dirty"] is True


def test_version_includes_schema_version_key(app_server):
    """Test the KEY exists. The value can be null on a fresh
    schema.sql-only DB (no migrations applied), or an int on a real
    install that ran the migration chain. The front-end must handle
    both."""
    status, out = _req(app_server["base"], "/api/version")
    assert status == 200
    assert "schema_version" in out
    val = out["schema_version"]
    assert val is None or isinstance(val, int)


# ── /api/system/update is now an action intent ───────────────────────


def test_system_update_returns_action_intent_not_execution(app_server, monkeypatch):
    """The endpoint MUST NOT execute anything. It returns
    ``action_required='run_cli'`` with the command the operator
    should run. Prevents the privilege-escalation path that would
    need Docker socket access from the container."""
    import app as app_mod
    # Guard: even patched pseudo-git must not be reached via the
    # update handler. We'd see ``_run_update`` calls if the code
    # regressed.
    monkeypatch.setattr(app_mod, "_discover_repo_dir", lambda: None)
    status, out = _req(
        app_server["base"], "/api/system/update", method="POST", body={},
    )
    assert status == 200
    assert out["ok"] is False
    assert out["action_required"] == "run_cli"
    assert out["command"] == "niwa update"
    assert "message" in out
    # The message must tell the operator where to run the command.
    msg = out["message"].lower()
    assert "niwa update" in msg
    assert "host" in msg


def test_system_update_intent_includes_branch_and_commits(app_server, monkeypatch):
    import app as app_mod
    fake_repo = app_server["tmp"] / "fake-repo"
    fake_repo.mkdir()
    monkeypatch.setattr(app_mod, "_discover_repo_dir", lambda: fake_repo)

    def _fake_git(repo, *args, timeout=10):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "v0.2"
        if args[:2] == ("rev-parse", "HEAD"):
            return "b" * 40
        if args[:2] == ("status", "--porcelain"):
            return ""
        return None

    monkeypatch.setattr(app_mod, "_git", _fake_git)
    monkeypatch.setattr(
        app_mod, "_latest_remote_commit", lambda *a, **kw: "c" * 40,
    )
    status, out = _req(
        app_server["base"], "/api/system/update", method="POST", body={},
    )
    assert status == 200
    assert out["branch"] == "v0.2"
    assert out["current_commit"].startswith("bbbb")
    assert out["current_commit_short"] == "bbbbbbbbbbbb"
    assert out["latest_remote_commit"].startswith("cccc")
    assert out["needs_update"] is True


# ── CLI repo-dirty guard (subprocess ``python3 setup.py update``) ────


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """A minimal NIWA_HOME + git-initialised repo copy so we can run
    ``setup.py update`` end-to-end against local state."""
    niwa_home = tmp_path / ".niwa"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "data").mkdir()
    (niwa_home / "bin").mkdir()
    (niwa_home / "secrets" / "mcp.env").write_text("")
    (niwa_home / "bin" / "task-executor.py").write_text("# placeholder\n")

    repo = niwa_home / "repo"
    repo.mkdir()
    # Make it a valid git repo pointing at the real setup.py.
    subprocess.run(["git", "init", "-q", "-b", "v0.2"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "gpg.format", "openpgp"], cwd=str(repo), check=True)
    # Copy a minimal setup.py so ``_find_install_dir``/``cmd_update``
    # resolve the install. We don't need to fully exercise setup.py —
    # the guard runs before anything else.
    import shutil as _sh
    _sh.copy(os.path.join(ROOT_DIR, "setup.py"), repo / "setup.py")
    (repo / "README.md").write_text("seed\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "seed"],
        cwd=str(repo), check=True,
    )
    return {"niwa_home": niwa_home, "repo": repo}


def test_cli_update_aborts_on_repo_dirty(fake_install, monkeypatch):
    """Running ``niwa update`` on a repo with uncommitted changes
    aborts with exit 1 and an actionable message (no silent
    ``Continuing with current code``)."""
    repo = fake_install["repo"]
    # Make the repo dirty.
    (repo / "README.md").write_text("dirty\n")

    env = os.environ.copy()
    env["NIWA_HOME"] = str(fake_install["niwa_home"])
    r = subprocess.run(
        [sys.executable, str(repo / "setup.py"), "update",
         "--dir", str(fake_install["niwa_home"])],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert r.returncode == 1
    combined = r.stdout + r.stderr
    assert "cambios locales" in combined.lower() or "dirty" in combined.lower() \
        or "uncommitted" in combined.lower(), combined
    # Must mention at least one recovery action.
    assert any(
        hint in combined for hint in ("git stash", "git reset", "git checkout")
    ), f"expected recovery hint, got: {combined}"


def test_cli_update_does_not_hardcode_main(fake_install):
    """Regression guard: the call is ``git pull origin <current_branch>``,
    not ``origin main``. We pin this by grepping the source — the
    behavioural test would require a real remote to pull from."""
    setup_source = Path(ROOT_DIR, "setup.py").read_text()
    # Find the cmd_update function and make sure there's no
    # hardcoded ``origin main`` inside its body.
    import re
    # Extract from ``def cmd_update`` to the next ``def cmd_``/``def main``.
    m = re.search(
        r"def cmd_update\(.*?\n(def cmd_[a-z_]+\(|def main\(|$)",
        setup_source, re.DOTALL,
    )
    assert m, "cmd_update not found"
    body = setup_source[m.start():m.end()]
    assert '"origin", "main"' not in body, (
        "cmd_update still hardcodes ``git pull origin main``"
    )


# ── Decision doc pinned ──────────────────────────────────────────────


def test_decisions_log_documents_ui_does_not_update():
    """Guard: if someone reintroduces UI-side update execution, the
    decisions log must be updated alongside. The string check is
    intentional — a refactor that moves the reasoning to another
    file should also update this test."""
    path = Path(ROOT_DIR, "docs", "DECISIONS-LOG.md")
    body = path.read_text()
    assert "PR-58a" in body
    assert "la UI no ejecuta update" in body.lower() or \
           "ui no ejecuta update" in body.lower()
