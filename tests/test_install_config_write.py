"""Tests for FIX-20260420 PR-A — ``setup._write_install_config``.

The installer writes ``<install_dir>/.install-config.json`` so the
updater can read the authoritative systemd scope instead of guessing.
Regression guards (from codex review on this PR):

  - ``executor_enabled=False`` must produce ``scope=none`` regardless
    of platform. Reporting ``scope=launchd`` on macOS when no launchd
    agent was installed is exactly the class of "confident lie" this
    FIX exists to kill.
  - A filesystem failure on the final write must NOT abort the install
    — the updater tolerates a missing file and falls back to probing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: E402 — module under test


def _fake_cfg(niwa_home: Path, *, executor_enabled: bool) -> SimpleNamespace:
    """Minimum cfg shape ``_write_install_config`` reads from."""
    return SimpleNamespace(
        niwa_home=niwa_home,
        executor_enabled=executor_enabled,
        db_path=niwa_home / "data" / "niwa.sqlite3",
    )


def _read_config(niwa_home: Path) -> dict:
    return json.loads((niwa_home / ".install-config.json").read_text())


def test_executor_disabled_writes_scope_none_on_linux_root(tmp_path, monkeypatch):
    niwa_home = tmp_path / ".niwa"
    niwa_home.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)
    setup._write_install_config(_fake_cfg(niwa_home, executor_enabled=False))
    assert _read_config(niwa_home)["systemd_scope"] == "none"


def test_executor_disabled_writes_scope_none_on_darwin(tmp_path, monkeypatch):
    # The codex review catch: without executor_enabled the installer
    # NEVER registers a launchd agent, so the config must not claim
    # ``scope=launchd``.
    niwa_home = tmp_path / ".niwa"
    niwa_home.mkdir()
    monkeypatch.setattr(sys, "platform", "darwin")
    setup._write_install_config(_fake_cfg(niwa_home, executor_enabled=False))
    assert _read_config(niwa_home)["systemd_scope"] == "none"


def test_executor_enabled_darwin_writes_launchd(tmp_path, monkeypatch):
    niwa_home = tmp_path / ".niwa"
    niwa_home.mkdir()
    monkeypatch.setattr(sys, "platform", "darwin")
    setup._write_install_config(_fake_cfg(niwa_home, executor_enabled=True))
    assert _read_config(niwa_home)["systemd_scope"] == "launchd"


def test_executor_enabled_linux_root_writes_system(tmp_path, monkeypatch):
    niwa_home = tmp_path / ".niwa"
    niwa_home.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "getuid", lambda: 0, raising=False)
    setup._write_install_config(_fake_cfg(niwa_home, executor_enabled=True))
    assert _read_config(niwa_home)["systemd_scope"] == "system"


def test_executor_enabled_linux_nonroot_writes_user(tmp_path, monkeypatch):
    niwa_home = tmp_path / ".niwa"
    niwa_home.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    setup._write_install_config(_fake_cfg(niwa_home, executor_enabled=True))
    assert _read_config(niwa_home)["systemd_scope"] == "user"


def test_write_failure_does_not_abort_install(tmp_path, monkeypatch):
    # Simulate a full disk / read-only FS on the final write. The
    # installer survived 14 previous steps — an exception here must
    # degrade to a warning, not propagate.
    niwa_home = tmp_path / ".niwa"
    niwa_home.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)

    original_write_text = Path.write_text

    def _boom(self, *args, **kwargs):
        if self.name == ".install-config.json":
            raise OSError("No space left on device")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _boom)
    # Must not raise.
    setup._write_install_config(_fake_cfg(niwa_home, executor_enabled=True))
    # File was not created — the updater will fall back to probing.
    assert not (niwa_home / ".install-config.json").exists()


def test_written_config_has_expected_keys(tmp_path, monkeypatch):
    niwa_home = tmp_path / ".niwa"
    niwa_home.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(os, "getuid", lambda: 1000, raising=False)
    setup._write_install_config(_fake_cfg(niwa_home, executor_enabled=True))
    config = _read_config(niwa_home)
    assert {"install_version", "install_timestamp", "systemd_scope",
            "systemd_units", "compose_file", "db_path",
            "install_dir", "repo_path"} <= set(config)
    assert config["systemd_units"] == {
        "executor": "niwa-executor.service",
        "hosting": "niwa-hosting.service",
    }
    assert config["compose_file"] == str(niwa_home / "docker-compose.yml")
    assert config["install_dir"] == str(niwa_home)
