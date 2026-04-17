"""Tests for PR-50 — GitHub PAT injection into the v0.2 executor subprocess env.

Covers:
  - `_prepare_backend_env` adds GITHUB_TOKEN/GH_TOKEN/GIT_ASKPASS when
    a PAT is persisted.
  - No GitHub env vars are added when the PAT is absent.
  - The ASKPASS script on disk answers ``Username`` with x-access-token
    and ``Password`` with $GITHUB_TOKEN — the actual GitHub auth contract.
  - A broken ``github_client`` import or failing ``get_pat`` does not
    block execution (the failure is swallowed and the base env is
    returned).

The executor module is imported as a script module — we insert
``bin/`` into sys.path with a renamed name to avoid the hyphen.

Run: pytest tests/test_executor_github_pat_injection.py -v
"""
import os
import sys
import importlib
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
BIN_DIR = os.path.join(ROOT_DIR, "bin")
for p in (BACKEND_DIR, BIN_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_executor():
    """Load bin/task-executor.py as a module named ``task_executor``."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "task_executor", os.path.join(BIN_DIR, "task-executor.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def executor(tmp_path, monkeypatch):
    """Bootstraps a minimal fake NIWA_HOME so the executor module can
    import — it refuses to load without one."""
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "secrets" / "mcp.env").write_text("")
    monkeypatch.setenv("NIWA_HOME", str(niwa_home))
    return _load_executor()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Fresh SQLite DB with only the schema for github_tokens."""
    import sqlite3 as _sq
    db_path = str(tmp_path / "niwa.sqlite3")
    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_SESSION_SECRET", "test-pr50-secret")
    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    c = _sq.connect(db_path)
    c.executescript(schema_sql)
    c.commit()
    c.close()
    return db_path


def test_prepare_env_includes_github_token_when_pat_stored(executor, tmp_db, monkeypatch):
    """Happy path: a PAT is persisted → extra env includes GITHUB_TOKEN,
    GH_TOKEN (gh CLI alias), GIT_TERMINAL_PROMPT=0 and GIT_ASKPASS."""
    import github_client as gh
    # Short-circuit the GitHub API validation for the test.
    monkeypatch.setattr(
        gh, "_api_get",
        lambda path, token, timeout=10.0: (200, {"login": "takeo7"}, {}),
    )
    gh.set_pat("ghp_pr50_test")

    profile = {"slug": "claude_code"}
    # Without Anthropic creds the function still returns the github bits.
    env = executor._prepare_backend_env(profile)
    assert env["GITHUB_TOKEN"] == "ghp_pr50_test"
    assert env["GH_TOKEN"] == "ghp_pr50_test"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"]
    assert os.path.exists(env["GIT_ASKPASS"])
    # The script must be executable and owned-readable only — PAT-adjacent
    # code, keep perms tight.
    st = os.stat(env["GIT_ASKPASS"])
    assert st.st_mode & 0o777 == 0o700


def test_prepare_env_without_pat_is_noop(executor, tmp_db):
    """No PAT persisted → no GitHub env vars leak into the subprocess."""
    profile = {"slug": "claude_code"}
    env = executor._prepare_backend_env(profile)
    assert "GITHUB_TOKEN" not in env
    assert "GH_TOKEN" not in env
    assert "GIT_ASKPASS" not in env


def test_askpass_script_answers_username_and_password(executor, tmp_db, monkeypatch):
    """End-to-end contract: the ASKPASS script is what Git actually calls
    when it needs credentials. Verify it prints the exact username GitHub
    expects (``x-access-token``) and the ``$GITHUB_TOKEN`` as the password."""
    import github_client as gh
    monkeypatch.setattr(
        gh, "_api_get",
        lambda path, token, timeout=10.0: (200, {"login": "takeo7"}, {}),
    )
    gh.set_pat("ghp_askpass_test")
    script = executor._ensure_git_askpass_script()
    assert script and os.path.exists(script)

    # Git calls ``GIT_ASKPASS "Username for 'https://github.com': "``.
    # The helper inspects the single argv[1] and decides what to emit.
    result_user = subprocess.run(
        [script, "Username for 'https://github.com': "],
        capture_output=True,
        text=True,
        env={**os.environ, "GITHUB_TOKEN": "ghp_askpass_test"},
    )
    assert result_user.returncode == 0
    assert result_user.stdout == "x-access-token"

    result_pass = subprocess.run(
        [script, "Password for 'https://x-access-token@github.com': "],
        capture_output=True,
        text=True,
        env={**os.environ, "GITHUB_TOKEN": "ghp_askpass_test"},
    )
    assert result_pass.returncode == 0
    assert result_pass.stdout == "ghp_askpass_test"

    # Unknown prompt → empty string (git will then retry or fail, not
    # leak the PAT to an unintended prompt).
    result_other = subprocess.run(
        [script, "something else"],
        capture_output=True,
        text=True,
        env={**os.environ, "GITHUB_TOKEN": "ghp_askpass_test"},
    )
    assert result_other.returncode == 0
    assert result_other.stdout == ""


def test_prepare_env_swallows_github_client_failure(executor, tmp_db, monkeypatch):
    """A broken github_client must NOT block task execution — e.g. the
    DB could be locked or the module import could fail in an unusual
    environment. The executor returns its base env, nothing more."""
    import github_client as gh
    monkeypatch.setattr(
        gh, "get_pat", lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    profile = {"slug": "claude_code"}
    env = executor._prepare_backend_env(profile)
    # The call returned without raising — that's the main contract.
    assert isinstance(env, dict)
    # And the GitHub bits are not there.
    assert "GITHUB_TOKEN" not in env
