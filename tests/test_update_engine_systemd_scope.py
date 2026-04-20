"""Tests for FIX-20260420 PR-A — systemd scope detection + scope-aware
executor restart in ``bin/update_engine.py``.

See ``docs/plans/FIX-20260420-update-engine-reliability.md`` (closes
Bug 37: updater hardcoded system scope even when the installer wrote a
user-scope unit, then recommended a ``sudo systemctl`` command that
kept failing).

Pins:
 - ``.install-config.json`` with ``systemd_scope=user`` → runs
   ``systemctl --user restart``, no ``sudo``.
 - ``.install-config.json`` with ``systemd_scope=system`` → runs
   ``systemctl restart`` (no ``--user``).
 - Missing ``.install-config.json`` → falls back to probing
   ``systemctl --user is-active`` and records a warning so the
   operator sees they're on a legacy install.
 - On failure the manual-restart hint matches the detected scope.
"""
from __future__ import annotations

import json
import os
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
    """subprocess.run replacement — tests pin exact responses and
    every call is logged so ordering/arguments can be asserted."""

    def __init__(self) -> None:
        self.responses: list[tuple[list[str], SimpleNamespace]] = []
        self.calls: list[list[str]] = []

    def on(self, cmd_prefix, *, returncode=0, stdout="", stderr=""):
        self.responses.append((cmd_prefix, SimpleNamespace(
            returncode=returncode, stdout=stdout, stderr=stderr,
        )))

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        for prefix, resp in self.responses:
            if args[:len(prefix)] == prefix:
                return resp
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _make_ctx(tmp_path: Path, runner: FakeRunner) -> update_engine._Ctx:
    install_dir = tmp_path / ".niwa"
    install_dir.mkdir(parents=True)
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    ctx = update_engine._Ctx(
        install_dir=install_dir,
        repo_dir=repo_dir,
        printer=lambda *_a, **_k: None,
        runner=runner,
        timestamp="20260420-000000",
        backup_fn=lambda c: None,
        health_check_fn=lambda c: True,
    )
    ctx.manifest = {
        "errors": [],
        "warnings": [],
        "components_updated": [],
        "needs_restart": False,
    }
    return ctx


def _write_config(install_dir: Path, scope: str) -> None:
    (install_dir / ".install-config.json").write_text(json.dumps({
        "install_version": "0.1.0",
        "install_timestamp": "2026-04-20T00:00:00Z",
        "systemd_scope": scope,
        "systemd_units": {
            "executor": "niwa-executor.service",
            "hosting": "niwa-hosting.service",
        },
        "compose_file": str(install_dir / "docker-compose.yml"),
        "db_path": str(install_dir / "data" / "niwa.sqlite3"),
        "install_dir": str(install_dir),
        "repo_path": "/home/test/niwa",
    }))


# ── _load_install_config ────────────────────────────────────────────


def test_load_install_config_missing_returns_none(tmp_path):
    install_dir = tmp_path / ".niwa"
    install_dir.mkdir()
    assert update_engine._load_install_config(install_dir) is None


def test_load_install_config_malformed_returns_none(tmp_path):
    install_dir = tmp_path / ".niwa"
    install_dir.mkdir()
    (install_dir / ".install-config.json").write_text("{not json")
    assert update_engine._load_install_config(install_dir) is None


def test_load_install_config_roundtrip(tmp_path):
    install_dir = tmp_path / ".niwa"
    install_dir.mkdir()
    _write_config(install_dir, "user")
    cfg = update_engine._load_install_config(install_dir)
    assert cfg is not None
    assert cfg["systemd_scope"] == "user"
    assert cfg["systemd_units"]["executor"] == "niwa-executor.service"


# ── _detect_systemd_scope: config-driven ─────────────────────────────


@pytest.mark.parametrize("scope", ["user", "system", "launchd", "none"])
def test_detect_scope_honours_config(tmp_path, scope):
    r = FakeRunner()
    ctx = _make_ctx(tmp_path, r)
    _write_config(ctx.install_dir, scope)
    assert update_engine._detect_systemd_scope(ctx) == scope
    # Config answered — no probe needed, no warning.
    assert not any(c[:2] == ["systemctl", "--user"] for c in r.calls)
    assert ctx.manifest["warnings"] == []


def test_detect_scope_ignores_unknown_config_value(tmp_path):
    # Hand-edited nonsense value → fall through to probe (and warning).
    r = FakeRunner()
    r.on(["systemctl", "--user", "is-active"], returncode=0,
         stdout="active\n")
    ctx = _make_ctx(tmp_path, r)
    (ctx.install_dir / ".install-config.json").write_text(json.dumps({
        "systemd_scope": "hogwash",
    }))
    assert update_engine._detect_systemd_scope(ctx) == "user"
    assert any("install-config" in w.lower() for w in ctx.manifest["warnings"])


# ── _detect_systemd_scope: probe fallback ────────────────────────────


def test_detect_scope_missing_config_probe_active_is_user(tmp_path):
    r = FakeRunner()
    r.on(["systemctl", "--user", "is-active"], returncode=0,
         stdout="active\n")
    ctx = _make_ctx(tmp_path, r)
    assert update_engine._detect_systemd_scope(ctx) == "user"
    assert any("install-config" in w.lower() for w in ctx.manifest["warnings"])


def test_detect_scope_missing_config_probe_inactive_is_user(tmp_path):
    # Exit 3 = inactive/unknown. The --user bus still answered, which
    # is the signal we care about for "user scope is reachable".
    r = FakeRunner()
    r.on(["systemctl", "--user", "is-active"], returncode=3,
         stdout="inactive\n")
    ctx = _make_ctx(tmp_path, r)
    assert update_engine._detect_systemd_scope(ctx) == "user"


def test_detect_scope_missing_config_probe_no_bus_is_system(tmp_path):
    # Exit 1 = systemctl --user can't reach a user bus → system scope.
    r = FakeRunner()
    r.on(["systemctl", "--user", "is-active"], returncode=1,
         stderr="Failed to connect to bus\n")
    ctx = _make_ctx(tmp_path, r)
    assert update_engine._detect_systemd_scope(ctx) == "system"


def test_detect_scope_probe_oserror_falls_back_to_system(tmp_path):
    def boom(*_a, **_k):
        raise OSError("systemctl: not found")
    ctx = _make_ctx(tmp_path, boom)
    assert update_engine._detect_systemd_scope(ctx) == "system"


# ── _restart_executor: scope-aware command ───────────────────────────


def test_restart_executor_user_scope_no_sudo(tmp_path):
    r = FakeRunner()
    r.on(["systemctl", "--user", "restart", "niwa-executor.service"],
         returncode=0)
    ctx = _make_ctx(tmp_path, r)
    _write_config(ctx.install_dir, "user")
    update_engine._restart_executor(ctx)
    assert ["systemctl", "--user", "restart", "niwa-executor.service"] in r.calls
    assert not any(c and c[0] == "sudo" for c in r.calls)
    assert any("executor:niwa-executor.service" in c
               for c in ctx.manifest["components_updated"])
    assert ctx.manifest["needs_restart"] is False


def test_restart_executor_system_scope_no_user_flag(tmp_path):
    r = FakeRunner()
    r.on(["systemctl", "restart", "niwa-executor.service"], returncode=0)
    ctx = _make_ctx(tmp_path, r)
    _write_config(ctx.install_dir, "system")
    update_engine._restart_executor(ctx)
    assert ["systemctl", "restart", "niwa-executor.service"] in r.calls
    assert not any("--user" in c for c in r.calls)


def test_restart_executor_user_scope_failure_hint_drops_sudo(tmp_path):
    r = FakeRunner()
    r.on(["systemctl", "--user", "restart", "niwa-executor.service"],
         returncode=5, stderr="unit masked\n")
    ctx = _make_ctx(tmp_path, r)
    _write_config(ctx.install_dir, "user")
    update_engine._restart_executor(ctx)
    assert ctx.manifest["needs_restart"] is True
    joined = " | ".join(ctx.manifest["warnings"])
    assert "systemctl --user restart niwa-executor.service" in joined
    assert "sudo systemctl" not in joined


def test_restart_executor_system_scope_failure_hint_uses_sudo(tmp_path):
    r = FakeRunner()
    r.on(["systemctl", "restart", "niwa-executor.service"],
         returncode=5, stderr="unit masked\n")
    ctx = _make_ctx(tmp_path, r)
    _write_config(ctx.install_dir, "system")
    update_engine._restart_executor(ctx)
    assert ctx.manifest["needs_restart"] is True
    joined = " | ".join(ctx.manifest["warnings"])
    assert "sudo systemctl restart niwa-executor.service" in joined


def test_restart_executor_launchd_scope_skips_systemctl(tmp_path):
    r = FakeRunner()
    ctx = _make_ctx(tmp_path, r)
    _write_config(ctx.install_dir, "launchd")
    update_engine._restart_executor(ctx)
    assert ctx.manifest["needs_restart"] is True
    assert not any(c and c[0] == "systemctl" for c in r.calls)


def test_restart_executor_none_scope_is_noop(tmp_path):
    r = FakeRunner()
    ctx = _make_ctx(tmp_path, r)
    _write_config(ctx.install_dir, "none")
    update_engine._restart_executor(ctx)
    assert not any(c and c[0] == "systemctl" for c in r.calls)
    assert ctx.manifest["needs_restart"] is False
    assert ctx.manifest["components_updated"] == []


def test_restart_executor_missing_config_probes_then_runs_user(tmp_path):
    # No config → probe says user bus is reachable → restart runs
    # on --user, and the warning about the missing config surfaces.
    r = FakeRunner()
    r.on(["systemctl", "--user", "is-active", "niwa-executor.service"],
         returncode=0, stdout="active\n")
    r.on(["systemctl", "--user", "restart", "niwa-executor.service"],
         returncode=0)
    ctx = _make_ctx(tmp_path, r)
    update_engine._restart_executor(ctx)
    assert ["systemctl", "--user", "restart", "niwa-executor.service"] in r.calls
    assert any("install-config" in w.lower() for w in ctx.manifest["warnings"])
