"""Tests for PR final 2 — enhanced post-update smoke.

Pineado:

  * ``_read_schema_version`` → returns MAX(version) or None (no DB /
    no table).
  * ``_app_container_is_up`` → parses ``docker compose ps --format
    json`` robustly; returns False on any docker failure.
  * ``_default_health_check`` combina 3 signals:
      - /health OK
      - schema_version check (solo si before era int)
      - docker compose ps app en state 'running'
  * Regla del user: before=int requiere after>=before (revert si no).
    before=None NO es revert automático (fresh install).
  * ``perform_update`` captura before_schema_version antes del pull.

Red de red-team pinned:

  * schema_version retrocede → revert.
  * schema_version salta de None → int → OK (fresh install).
  * schema_version antes=int, después=None → revert (migración rota).
  * docker ps fail → revert.

Run: pytest tests/test_pr_final2_post_update_smoke.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
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


def _ctx(install_dir, runner=None):
    """Minimal _Ctx for helper-level tests."""
    return update_engine._Ctx(  # type: ignore
        install_dir=install_dir,
        repo_dir=install_dir.parent / "repo",
        printer=lambda *a, **k: None,
        runner=runner or FakeRunner(),
        timestamp="20260417-test",
        backup_fn=lambda ctx: None,
        health_check_fn=lambda ctx: True,
    )


# ── _read_schema_version ─────────────────────────────────────────────


def test_schema_version_none_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("NIWA_DB_PATH", str(tmp_path / "nope.sqlite3"))
    assert update_engine._read_schema_version(_ctx(tmp_path)) is None


def test_schema_version_none_when_table_missing(tmp_path, monkeypatch):
    db = tmp_path / "niwa.sqlite3"
    sqlite3.connect(str(db)).close()
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    assert update_engine._read_schema_version(_ctx(tmp_path)) is None


def test_schema_version_returns_max(tmp_path, monkeypatch):
    db = tmp_path / "niwa.sqlite3"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE schema_version (version INTEGER)")
    c.execute("INSERT INTO schema_version VALUES (7), (14), (3)")
    c.commit()
    c.close()
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    assert update_engine._read_schema_version(_ctx(tmp_path)) == 14


# ── _app_container_is_up ─────────────────────────────────────────────


def test_container_check_true_when_ps_json_reports_running(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout=json.dumps({
        "Service": "app", "State": "running",
    }))
    assert update_engine._app_container_is_up(_ctx(tmp_path, r)) is True


def test_container_check_false_when_not_running(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout=json.dumps({
        "Service": "app", "State": "exited",
    }))
    assert update_engine._app_container_is_up(_ctx(tmp_path, r)) is False


def test_container_check_false_when_ps_fails(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], returncode=1, stderr="daemon unreachable")
    assert update_engine._app_container_is_up(_ctx(tmp_path, r)) is False


def test_container_check_true_when_no_compose_file(tmp_path):
    """Sin docker-compose.yml (bare-metal dev), no hay container
    que comprobar — returns True para no bloquear el flow."""
    r = FakeRunner()
    assert update_engine._app_container_is_up(_ctx(tmp_path, r)) is True


def test_container_check_handles_multiline_ndjson(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout="\n".join([
        json.dumps({"Service": "mcp", "State": "exited"}),
        json.dumps({"Service": "app", "State": "running"}),
    ]))
    assert update_engine._app_container_is_up(_ctx(tmp_path, r)) is True


# ── _default_health_check: schema_version rule ──────────────────────


def _make_live_db(tmp_path: Path, version: int | None) -> Path:
    db = tmp_path / "niwa.sqlite3"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE schema_version (version INTEGER)")
    if version is not None:
        c.execute("INSERT INTO schema_version VALUES (?)", (version,))
    c.commit()
    c.close()
    return db


def _mock_http_ok(monkeypatch):
    """Short-circuit the urlopen retry loop so the test runs in ms."""
    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", lambda *a, **kw: _Resp())


def test_health_check_ok_when_schema_advances(tmp_path, monkeypatch):
    db = _make_live_db(tmp_path, 14)
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    _mock_http_ok(monkeypatch)
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout=json.dumps({
        "Service": "app", "State": "running",
    }))
    ctx = _ctx(tmp_path, r)
    ctx.manifest["before_schema_version"] = 12  # baseline
    # Live DB shows 14 > 12 → OK.
    assert update_engine._default_health_check(ctx) is True


def test_health_check_fails_when_schema_goes_backwards(tmp_path, monkeypatch):
    """Guard: migration supuestamente aplicó, pero la DB retrocedió.
    Rollback silencioso — debe revertir."""
    db = _make_live_db(tmp_path, 10)
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    _mock_http_ok(monkeypatch)
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout=json.dumps({
        "Service": "app", "State": "running",
    }))
    ctx = _ctx(tmp_path, r)
    ctx.manifest["before_schema_version"] = 14
    assert update_engine._default_health_check(ctx) is False


def test_health_check_fails_when_schema_becomes_none_from_int(tmp_path, monkeypatch):
    """Antes había schema_version=N, después la query no devuelve
    nada — migración explotó, tabla corrupta, DB ilegible."""
    db = _make_live_db(tmp_path, None)  # table empty
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    _mock_http_ok(monkeypatch)
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout=json.dumps({
        "Service": "app", "State": "running",
    }))
    ctx = _ctx(tmp_path, r)
    ctx.manifest["before_schema_version"] = 12
    assert update_engine._default_health_check(ctx) is False


def test_health_check_ok_when_before_is_none_and_after_int(tmp_path, monkeypatch):
    """Fresh install (first update) — no había baseline. Ver la
    schema aparece por primera vez no debe contar como revert."""
    db = _make_live_db(tmp_path, 14)
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    _mock_http_ok(monkeypatch)
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout=json.dumps({
        "Service": "app", "State": "running",
    }))
    ctx = _ctx(tmp_path, r)
    ctx.manifest["before_schema_version"] = None
    assert update_engine._default_health_check(ctx) is True


def test_health_check_ok_when_before_and_after_both_none(tmp_path, monkeypatch):
    """Ambos None = no sabemos nada sobre schema. Solo validamos
    /health + docker. No bloquear."""
    db = _make_live_db(tmp_path, None)
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    _mock_http_ok(monkeypatch)
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout=json.dumps({
        "Service": "app", "State": "running",
    }))
    ctx = _ctx(tmp_path, r)
    ctx.manifest["before_schema_version"] = None
    assert update_engine._default_health_check(ctx) is True


def test_health_check_fails_when_container_not_running(tmp_path, monkeypatch):
    """Siguiendo la cascada: /health respondió (podría ser un thread
    que sobrevivió), pero el container está exited → revert."""
    db = _make_live_db(tmp_path, 14)
    monkeypatch.setenv("NIWA_DB_PATH", str(db))
    _mock_http_ok(monkeypatch)
    (tmp_path / "docker-compose.yml").write_text("x")
    r = FakeRunner()
    r.on(["docker", "compose", "-f"], stdout=json.dumps({
        "Service": "app", "State": "exited",
    }))
    ctx = _ctx(tmp_path, r)
    ctx.manifest["before_schema_version"] = 14
    assert update_engine._default_health_check(ctx) is False


# ── perform_update captura before_schema_version ────────────────────


def test_perform_update_captures_schema_baseline(tmp_path, monkeypatch):
    """Sanity: el flujo principal mete ``before_schema_version`` en
    el manifest antes del pull, para que el health-check tenga
    baseline."""
    # Install dir layout mínimo.
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

    # Seed a DB with schema_version to be read as baseline.
    db = install_dir / "data" / "niwa.sqlite3"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE schema_version (version INTEGER)")
    c.execute("INSERT INTO schema_version VALUES (9)")
    c.commit()
    c.close()
    monkeypatch.setenv("NIWA_DB_PATH", str(db))

    r = FakeRunner()
    r.on(["git", "status", "--porcelain"], stdout="")
    r.on(["git", "rev-parse", "--abbrev-ref"], stdout="v0.2\n")
    r.on(["git", "rev-parse", "HEAD"], stdout="a" * 40 + "\n")
    r.on(["git", "pull"], stdout="updated\n")
    r.on(["docker", "compose"], returncode=0)
    r.on(["systemctl", "restart"], returncode=0)

    manifest = update_engine.perform_update(
        install_dir=install_dir, repo_dir=repo_dir,
        runner=r, printer=lambda *a, **k: None,
        backup_fn=lambda ctx: None,
        health_check_fn=lambda ctx: True,
    )
    assert manifest["before_schema_version"] == 9, manifest
