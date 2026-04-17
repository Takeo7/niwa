"""Tests for PR-58b1 — ``bin/update_engine.perform_update``.

The engine is the shared implementation of ``niwa update`` that PR-58b1
extracts out of ``setup.py``. Tests run entirely in-process with:

  - a fake ``runner`` substituting subprocess.run (so no git/docker/systemd
    is actually invoked),
  - a fake ``backup_fn`` or the real one over a tmp sqlite,
  - a captured printer.

The contract we pin:

  * dirty repo → ``success=False``, no pull.
  * detached HEAD → ``success=False``, no pull.
  * backup failure → ``success=False``, no pull (red de seguridad atomic).
  * git pull failure → ``success=False``, after_commit stays None.
  * happy path → manifest has branch/before/after/backup/components,
    ``success=True``.
  * rebuild/restart failures are warnings, not errors; update still
    counts as success.

Run: pytest tests/test_pr58b1_update_engine.py -v
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT_DIR, "bin")
if BIN_DIR not in sys.path:
    sys.path.insert(0, BIN_DIR)

import update_engine  # noqa: E402


# ── FakeRunner: simulates subprocess.run for git/docker/systemctl ────


class FakeRunner:
    """Minimal subprocess.run replacement.

    Configure per-command responses. The ``calls`` log records every
    invocation so tests can pin the order (dirty-guard BEFORE pull,
    backup BEFORE pull, etc.).
    """

    def __init__(self) -> None:
        self.responses: list[tuple[list[str], SimpleNamespace]] = []
        self.calls: list[list[str]] = []

    def on(self, cmd_prefix: list[str], *, returncode: int = 0,
           stdout: str = "", stderr: str = "") -> None:
        self.responses.append((cmd_prefix, SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr,
        )))

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        for prefix, resp in self.responses:
            if args[:len(prefix)] == prefix:
                return resp
        # Default: succeed silently — tests that care pin the response.
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _clean_repo_runner() -> FakeRunner:
    r = FakeRunner()
    r.on(["git", "status", "--porcelain"], stdout="")
    r.on(["git", "rev-parse", "--abbrev-ref", "HEAD"], stdout="v0.2\n")
    # rev-parse HEAD called before and after pull.
    r.on(["git", "rev-parse", "HEAD"], stdout="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n")
    r.on(["git", "pull", "origin", "v0.2"], stdout="Already up to date.\n")
    return r


def _install(tmp_path: Path) -> dict:
    install_dir = tmp_path / ".niwa"
    (install_dir / "bin").mkdir(parents=True)
    (install_dir / "bin" / "task-executor.py").write_text("# old\n")
    (install_dir / "servers" / "tasks-mcp").mkdir(parents=True)
    (install_dir / "servers" / "tasks-mcp" / "server.py").write_text("# old\n")
    (install_dir / "data").mkdir()
    (install_dir / "data" / "niwa.sqlite3").write_text("")  # empty — will skip backup
    (install_dir / "docker-compose.yml").write_text("version: '3'\n")
    repo_dir = tmp_path / "repo"
    (repo_dir / "bin").mkdir(parents=True)
    (repo_dir / "bin" / "task-executor.py").write_text("# new\n")
    (repo_dir / "servers" / "tasks-mcp").mkdir(parents=True)
    (repo_dir / "servers" / "tasks-mcp" / "server.py").write_text("# new\n")
    return {"install_dir": install_dir, "repo_dir": repo_dir}


# ── Dirty repo short-circuit ─────────────────────────────────────────


def test_dirty_repo_aborts_before_pull(tmp_path):
    inst = _install(tmp_path)
    r = FakeRunner()
    # Non-empty porcelain → dirty.
    r.on(["git", "status", "--porcelain"], stdout=" M setup.py\n")
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: (_ for _ in ()).throw(
            AssertionError("backup_fn must NOT run when dirty")
        ),
    )
    assert manifest["success"] is False
    assert any("cambios locales" in e for e in manifest["errors"])
    # pull must never have been attempted.
    assert not any(c[:2] == ["git", "pull"] for c in r.calls)


# ── Detached HEAD short-circuit ──────────────────────────────────────


def test_detached_head_aborts(tmp_path):
    inst = _install(tmp_path)
    r = FakeRunner()
    r.on(["git", "status", "--porcelain"], stdout="")
    r.on(["git", "rev-parse", "--abbrev-ref", "HEAD"], stdout="HEAD\n")
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: (_ for _ in ()).throw(
            AssertionError("backup_fn must NOT run when detached")
        ),
    )
    assert manifest["success"] is False
    assert any("detached" in e.lower() or "rama actual" in e.lower()
               for e in manifest["errors"])


# ── Backup failure short-circuits BEFORE pull ────────────────────────


def test_backup_failure_aborts_before_pull(tmp_path):
    inst = _install(tmp_path)
    r = _clean_repo_runner()

    def _boom(ctx):
        raise RuntimeError("disk full")

    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=_boom,
    )
    assert manifest["success"] is False
    assert any("Backup falló" in e for e in manifest["errors"])
    # pull must never have been attempted — red de seguridad.
    assert not any(c[:2] == ["git", "pull"] for c in r.calls)


# ── Pull failure aborts, no file copies ──────────────────────────────


def test_pull_failure_records_error_and_skips_copies(tmp_path):
    inst = _install(tmp_path)
    r = FakeRunner()
    r.on(["git", "status", "--porcelain"], stdout="")
    r.on(["git", "rev-parse", "--abbrev-ref", "HEAD"], stdout="v0.2\n")
    r.on(["git", "rev-parse", "HEAD"], stdout="a" * 40 + "\n")
    r.on(["git", "pull", "origin", "v0.2"], returncode=1, stderr="nope")
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: None,
    )
    assert manifest["success"] is False
    assert any("pull" in e.lower() for e in manifest["errors"])
    # Files weren't touched because we bailed before the copy step.
    new_exec = (inst["install_dir"] / "bin" / "task-executor.py").read_text()
    assert new_exec == "# old\n"


# ── Happy path: everything succeeds ──────────────────────────────────


def test_happy_path_populates_full_manifest(tmp_path):
    inst = _install(tmp_path)
    r = _clean_repo_runner()
    r.on(["docker", "compose"], returncode=0)
    r.on(["systemctl", "restart"], returncode=0)

    backup_calls = []

    def _fake_backup(ctx):
        backup_calls.append(str(ctx.install_dir))
        return str(ctx.install_dir / "data" / "backups" / "niwa-X.sqlite3")

    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=_fake_backup,
        health_check_fn=lambda ctx: True,
        timestamp="20260417-120000",
    )
    assert manifest["success"] is True
    assert manifest["branch"] == "v0.2"
    assert manifest["before_commit"].startswith("a")
    assert manifest["after_commit"].startswith("a")
    assert manifest["backup_path"].endswith("niwa-X.sqlite3")
    # Executor was copied (install dir content matches repo).
    assert (inst["install_dir"] / "bin" / "task-executor.py").read_text() == "# new\n"
    assert (inst["install_dir"] / "servers" / "tasks-mcp" / "server.py").read_text() == "# new\n"
    # Components updated list is not empty and has expected entries.
    comps = manifest["components_updated"]
    assert any(c.startswith("backup:") for c in comps)
    assert "executor" in comps
    assert any(c.startswith("mcp:") for c in comps)
    assert len(manifest["errors"]) == 0


def test_build_failure_is_warning_not_error(tmp_path):
    """Container rebuild errors degrade to warnings — the code is
    pulled and copied successfully, the worst case is the operator
    must re-run ``docker compose build`` by hand."""
    inst = _install(tmp_path)
    r = _clean_repo_runner()
    r.on(["docker", "compose"], returncode=2, stderr="build failed")
    r.on(["systemctl", "restart"], returncode=0)

    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: None,
        health_check_fn=lambda ctx: True,
    )
    # success True because pull + copy ran; rebuild is best-effort.
    assert manifest["success"] is True
    assert any("build" in w.lower() for w in manifest["warnings"])


def test_systemctl_restart_failure_sets_needs_restart(tmp_path):
    inst = _install(tmp_path)
    r = _clean_repo_runner()
    r.on(["docker", "compose"], returncode=0)
    r.on(["systemctl", "restart"], returncode=5, stderr="permission denied")

    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: None,
        health_check_fn=lambda ctx: True,
    )
    assert manifest["success"] is True
    assert manifest["needs_restart"] is True
    assert any("systemctl" in w.lower() for w in manifest["warnings"])


# ── Real backup file is created ──────────────────────────────────────


def test_default_backup_writes_a_real_sqlite_file(tmp_path, monkeypatch):
    """Sanity test of the default backup function against a real
    SQLite db. Guards against regressing to a plaintext copy or a
    busted connection pair."""
    db = tmp_path / "data" / "niwa.sqlite3"
    db.parent.mkdir()
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()

    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    inst = _install(tmp_path / "inst")

    r = _clean_repo_runner()
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=lambda ctx: True,
        timestamp="20260417-130000",
    )
    assert manifest["success"] is True
    bkp = Path(manifest["backup_path"])
    assert bkp.exists()
    # Restored DB holds the row we inserted.
    rc = sqlite3.connect(str(bkp))
    val = rc.execute("SELECT x FROM t").fetchone()[0]
    rc.close()
    assert val == 42


# ── Ordering invariants ──────────────────────────────────────────────


def test_default_backup_rotates_old_snapshots(tmp_path, monkeypatch):
    """Rotation invariant: backups older than 14 days are pruned,
    the fresh one is kept no matter its timestamp in the filename.
    """
    import time as _t

    db = tmp_path / "data" / "niwa.sqlite3"
    db.parent.mkdir()
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()

    backups_dir = db.parent / "backups"
    backups_dir.mkdir()
    # Seed one "recent" (8 days old) and one "old" (30 days old) backup.
    recent = backups_dir / "niwa-recent.sqlite3"
    old = backups_dir / "niwa-old.sqlite3"
    recent.write_text("recent")
    old.write_text("old")
    now = _t.time()
    os.utime(recent, (now - 8 * 86400, now - 8 * 86400))
    os.utime(old, (now - 30 * 86400, now - 30 * 86400))

    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    inst = _install(tmp_path / "inst")
    r = _clean_repo_runner()
    manifest = update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=lambda ctx: True,
        timestamp="20260417-140000",
    )
    assert manifest["success"] is True
    assert recent.exists(), "8-day-old backup should be kept"
    assert not old.exists(), "30-day-old backup should be pruned"
    assert Path(manifest["backup_path"]).exists(), "fresh backup must exist"


def test_backup_runs_before_pull(tmp_path):
    """Hard pin: backup happens BEFORE git pull. A broken ordering
    means an update could fail halfway with no restore point."""
    inst = _install(tmp_path)
    r = _clean_repo_runner()
    r.on(["docker", "compose"], returncode=0)
    r.on(["systemctl", "restart"], returncode=0)
    order = []

    def _fake_backup(ctx):
        order.append("backup")
        return "/tmp/niwa-X.sqlite3"

    def _wrapped_runner(args, **kwargs):
        if args[:3] == ["git", "pull", "origin"]:
            order.append("pull")
        return r(args, **kwargs)

    update_engine.perform_update(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        runner=_wrapped_runner, printer=lambda *a, **k: None,
        backup_fn=_fake_backup,
        health_check_fn=lambda ctx: True,
    )
    assert order == ["backup", "pull"], order
