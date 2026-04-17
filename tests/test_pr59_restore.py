"""Tests for PR-59 — ``update_engine.perform_restore`` (backup +
rollback de código).

Contrato pineado:

  * backup path inexistente → success=False, abort inmediato, sin
    tocar DB ni código.
  * manifest entry encontrado + db_only=False → git checkout al
    commit + restore de DB → ambos true.
  * manifest entry ausente + db_only=False → warning "no sé a qué
    commit revertir" pero DB se restaura igual (degradación
    explícita).
  * db_only=True → nunca toca el código aunque haya entry.
  * git checkout fail → warning, DB se restaura igual, success=True
    si la DB llegó a quedar restaurada.
  * Round-trip real: update(install→backup) → restore(backup) →
    datos del estado inicial reaparecen.

Run: pytest tests/test_pr59_restore.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(ROOT_DIR, "bin")
if BIN_DIR not in sys.path:
    sys.path.insert(0, BIN_DIR)

import update_engine  # noqa: E402


class FakeRunner:
    def __init__(self) -> None:
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


def _install(tmp_path: Path) -> dict:
    install_dir = tmp_path / ".niwa"
    (install_dir / "bin").mkdir(parents=True)
    (install_dir / "bin" / "task-executor.py").write_text("# current\n")
    (install_dir / "servers" / "tasks-mcp").mkdir(parents=True)
    (install_dir / "servers" / "tasks-mcp" / "server.py").write_text("# current\n")
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


def _seed_log(install_dir: Path, backup_path: str, before_commit: str):
    log = install_dir / "data" / "update-log.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps([{
        "timestamp": "20260417-100000",
        "success": True,
        "reverted": False,
        "branch": "v0.2",
        "before_commit": before_commit,
        "after_commit": "a" * 40,
        "backup_path": backup_path,
        "errors": [],
        "warnings": [],
        "duration_seconds": 10.0,
    }]))


# ── Short-circuits ───────────────────────────────────────────────────


def test_restore_backup_missing_aborts(tmp_path):
    inst = _install(tmp_path)
    r = FakeRunner()
    manifest = update_engine.perform_restore(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        backup_path=str(tmp_path / "nope.sqlite3"),
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=lambda ctx: True,
    )
    assert manifest["success"] is False
    assert manifest["db_restored"] is False
    assert manifest["code_restored"] is False
    assert any("no encontrado" in e.lower() for e in manifest["errors"])
    # No git commands were issued for a missing backup.
    assert not any(c[:2] == ["git", "checkout"] for c in r.calls)


# ── Happy path: entry found, full restore ───────────────────────────


def test_restore_with_manifest_entry_rolls_back_code_and_db(tmp_path):
    inst = _install(tmp_path)
    # Create a real backup file.
    backup = tmp_path / "bkp" / "niwa-X.sqlite3"
    backup.parent.mkdir()
    # Use sqlite3 to make a proper DB so _restore_db can copy it.
    c = sqlite3.connect(str(backup))
    c.execute("CREATE TABLE t(x)")
    c.execute("INSERT INTO t VALUES (99)")
    c.commit()
    c.close()
    # Plant the update-log pointing at this backup.
    before = "b" * 40
    _seed_log(inst["install_dir"], str(backup), before)

    r = FakeRunner()
    r.on(["git", "checkout"], returncode=0)
    r.on(["docker", "compose"], returncode=0)

    manifest = update_engine.perform_restore(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        backup_path=str(backup),
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=lambda ctx: True,
    )
    assert manifest["success"] is True
    assert manifest["db_restored"] is True
    assert manifest["code_restored"] is True
    assert manifest["target_commit"] == before
    assert manifest["manifest_entry_found"] is True
    # git checkout was called with the expected commit.
    assert any(
        c[:3] == ["git", "checkout", before] for c in r.calls
    ), r.calls
    # DB actually replaced.
    dst_db = inst["install_dir"] / "data" / "niwa.sqlite3"
    assert dst_db.exists()


# ── Degradation: no manifest entry ──────────────────────────────────


def test_restore_without_manifest_entry_still_restores_db(tmp_path):
    inst = _install(tmp_path)
    backup = tmp_path / "bkp.sqlite3"
    c = sqlite3.connect(str(backup))
    c.execute("CREATE TABLE t(x)")
    c.commit()
    c.close()
    # No log seeded → no entry for this backup.

    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)

    manifest = update_engine.perform_restore(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        backup_path=str(backup),
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=lambda ctx: True,
    )
    assert manifest["success"] is True
    assert manifest["db_restored"] is True
    assert manifest["code_restored"] is False
    assert manifest["manifest_entry_found"] is False
    # Warning explains the degradation.
    assert any("no encuentro" in w.lower() or "no sé" in w.lower()
               for w in manifest["warnings"])
    # No git checkout attempted.
    assert not any(c[:2] == ["git", "checkout"] for c in r.calls)


# ── db_only skip ────────────────────────────────────────────────────


def test_restore_db_only_skips_code_even_with_entry(tmp_path):
    inst = _install(tmp_path)
    backup = tmp_path / "bkp.sqlite3"
    c = sqlite3.connect(str(backup))
    c.execute("CREATE TABLE t(x)")
    c.commit()
    c.close()
    _seed_log(inst["install_dir"], str(backup), "c" * 40)

    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)

    manifest = update_engine.perform_restore(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        backup_path=str(backup),
        runner=r, printer=lambda *a, **k: None,
        db_only=True,
        health_check_fn=lambda ctx: True,
    )
    assert manifest["success"] is True
    assert manifest["db_restored"] is True
    assert manifest["code_restored"] is False
    # db_only pinea: NO git checkout aunque la entry existiera.
    assert not any(c[:2] == ["git", "checkout"] for c in r.calls)


# ── Partial failure: code checkout fails, DB still gets restored ────


def test_restore_code_checkout_fail_is_warning_db_still_restored(tmp_path):
    inst = _install(tmp_path)
    backup = tmp_path / "bkp.sqlite3"
    c = sqlite3.connect(str(backup))
    c.execute("CREATE TABLE t(x)")
    c.commit()
    c.close()
    _seed_log(inst["install_dir"], str(backup), "d" * 40)

    r = FakeRunner()
    r.on(["git", "checkout"], returncode=1, stderr="cannot checkout")
    r.on(["docker", "compose"], returncode=0)

    manifest = update_engine.perform_restore(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        backup_path=str(backup),
        runner=r, printer=lambda *a, **k: None,
        health_check_fn=lambda ctx: True,
    )
    assert manifest["db_restored"] is True
    assert manifest["code_restored"] is False  # checkout failed
    assert manifest["success"] is True  # DB ok is enough to call it a success
    assert any("checkout" in w.lower() for w in manifest["warnings"])


# ── Round-trip real: backup → restore ──────────────────────────────


def test_full_round_trip_backup_then_restore_preserves_data(tmp_path, monkeypatch):
    """Pinea el contrato operativo: backup + restore sobre un DB real
    devuelve exactamente los mismos datos. Pillaría una regresión en
    _default_backup o _restore_db que rompiera la fidelidad."""
    inst = _install(tmp_path)
    db_path = inst["install_dir"] / "data" / "niwa.sqlite3"
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))

    # Seed an initial DB state we can detect.
    c = sqlite3.connect(str(db_path))
    c.execute("CREATE TABLE projects (id TEXT, name TEXT)")
    c.execute("INSERT INTO projects VALUES ('p1', 'before-update')")
    c.commit()
    c.close()

    # Snapshot the initial state via the engine's default backup fn.
    # (This mirrors what perform_update does pre-pull.)
    from types import SimpleNamespace as NS
    mock_ctx = NS(install_dir=inst["install_dir"], timestamp="20260417-150000")
    backup_path = update_engine._default_backup(mock_ctx)  # type: ignore
    assert backup_path and Path(backup_path).exists()

    # Mutate the "live" DB — simulates the update applying changes.
    c = sqlite3.connect(str(db_path))
    c.execute("UPDATE projects SET name='after-update' WHERE id='p1'")
    c.execute("INSERT INTO projects VALUES ('p2', 'post-update-row')")
    c.commit()
    c.close()

    # Seed the update log so restore finds the entry.
    _seed_log(inst["install_dir"], backup_path, "e" * 40)

    # Run restore — db_only so we don't worry about git.
    r = FakeRunner()
    r.on(["docker", "compose"], returncode=0)
    manifest = update_engine.perform_restore(
        install_dir=inst["install_dir"], repo_dir=inst["repo_dir"],
        backup_path=backup_path,
        runner=r, printer=lambda *a, **k: None,
        db_only=True,
        health_check_fn=lambda ctx: True,
    )
    assert manifest["success"] is True

    # Verify we see the pre-update state.
    c = sqlite3.connect(str(db_path))
    rows = c.execute("SELECT id, name FROM projects ORDER BY id").fetchall()
    c.close()
    assert rows == [("p1", "before-update")], rows
