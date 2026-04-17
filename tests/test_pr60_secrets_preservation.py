"""Tests for PR-60 — preserve secrets by default on reinstall + opt-in
rotation via ``--rotate-secrets``.

Contract pineado:

  * Fresh install → tokens + admin password + session secret generated.
  * Reinstall same-mode (default) → ALL preserved:
      - NIWA_LOCAL_TOKEN
      - NIWA_REMOTE_TOKEN
      - MCP_GATEWAY_AUTH_TOKEN
      - NIWA_APP_USERNAME
      - NIWA_APP_PASSWORD
      - NIWA_APP_SESSION_SECRET
  * Reinstall with ``--rotate-secrets`` → ALL regenerated.
  * Explicit ``--admin-password`` always wins (overrides both).

``_load_existing_mcp_env`` is the hinge. Tests call
``build_quick_config`` directly with a stub args namespace so we
don't have to run the whole installer pipeline.

Run: pytest tests/test_pr60_secrets_preservation.py -v
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETUP_PY = Path(ROOT_DIR, "setup.py")


@pytest.fixture
def setup_module(tmp_path, monkeypatch):
    """Load ``setup.py`` as a module and stub the Docker detection so
    tests don't depend on a real Docker install."""
    import importlib.util
    monkeypatch.setenv("NIWA_HOME", str(tmp_path / "niwa-home"))
    spec = importlib.util.spec_from_file_location("niwa_setup", str(SETUP_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # ``build_quick_config`` hard-fails if Docker isn't present. We
    # don't want these tests to require a docker daemon.
    monkeypatch.setattr(mod, "detect_docker",
                        lambda: {"available": True, "version": "fake"})
    monkeypatch.setattr(mod, "detect_socket_path",
                        lambda: "/var/run/docker.sock")
    return mod


def _args(**overrides):
    """Build a minimal argparse-like namespace for ``build_quick_config``."""
    defaults = dict(
        mode="core",
        bind="localhost",
        dir=None,
        instance=None,
        admin_user=None,
        admin_password=None,
        public_url=None,
        rotate_secrets=False,
        force=False,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


# ── Caracterización: install fresco genera secrets ──────────────────


def test_fresh_install_generates_new_secrets(setup_module, tmp_path):
    """Pin del comportamiento base: sin install previo, genera todo."""
    mod = setup_module
    args = _args(dir=str(tmp_path / "fresh"))
    cfg = mod.build_quick_config(args)
    assert cfg.tokens["NIWA_LOCAL_TOKEN"]
    assert cfg.tokens["NIWA_REMOTE_TOKEN"]
    assert cfg.tokens["MCP_GATEWAY_AUTH_TOKEN"] == cfg.tokens["NIWA_LOCAL_TOKEN"]
    assert cfg.tokens["NIWA_APP_SESSION_SECRET"]
    assert cfg.username == "niwa"
    assert cfg.password
    assert len(cfg.password) >= 12


# ── Reinstall default: preservar ────────────────────────────────────


def test_reinstall_same_mode_preserves_all_secrets_by_default(setup_module, tmp_path):
    mod = setup_module
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    existing_env = {
        "NIWA_LOCAL_TOKEN": "kept-local-xyz",
        "NIWA_REMOTE_TOKEN": "kept-remote-xyz",
        "MCP_GATEWAY_AUTH_TOKEN": "kept-gw-xyz",
        "NIWA_APP_USERNAME": "alice",
        "NIWA_APP_PASSWORD": "kept-admin-pw",
        "NIWA_APP_SESSION_SECRET": "kept-session-secret",
    }
    (niwa_home / "secrets" / "mcp.env").write_text(
        "\n".join(f'{k}="{v}"' for k, v in existing_env.items()) + "\n"
    )
    args = _args(dir=str(niwa_home))
    cfg = mod.build_quick_config(args)
    assert cfg.tokens["NIWA_LOCAL_TOKEN"] == "kept-local-xyz"
    assert cfg.tokens["NIWA_REMOTE_TOKEN"] == "kept-remote-xyz"
    assert cfg.tokens["MCP_GATEWAY_AUTH_TOKEN"] == "kept-gw-xyz"
    assert cfg.tokens["NIWA_APP_SESSION_SECRET"] == "kept-session-secret"
    assert cfg.username == "alice"
    assert cfg.password == "kept-admin-pw"


# ── Reinstall con --rotate-secrets: rota ────────────────────────────


def test_reinstall_with_rotate_flag_regenerates_everything(setup_module, tmp_path):
    mod = setup_module
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    existing_env = {
        "NIWA_LOCAL_TOKEN": "kept-local-xyz",
        "NIWA_APP_PASSWORD": "kept-admin-pw",
        "NIWA_APP_SESSION_SECRET": "kept-session-secret",
    }
    (niwa_home / "secrets" / "mcp.env").write_text(
        "\n".join(f'{k}="{v}"' for k, v in existing_env.items()) + "\n"
    )
    args = _args(dir=str(niwa_home), rotate_secrets=True)
    cfg = mod.build_quick_config(args)
    # All of these should be different from the persisted values.
    assert cfg.tokens["NIWA_LOCAL_TOKEN"] != "kept-local-xyz"
    assert cfg.tokens["NIWA_APP_SESSION_SECRET"] != "kept-session-secret"
    assert cfg.password != "kept-admin-pw"


# ── Explicit --admin-password wins over preservation ────────────────


def test_explicit_admin_password_overrides_preserved(setup_module, tmp_path):
    mod = setup_module
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "secrets" / "mcp.env").write_text(
        'NIWA_APP_PASSWORD="kept-admin-pw"\n'
    )
    args = _args(dir=str(niwa_home), admin_password="brand-new-pw")
    cfg = mod.build_quick_config(args)
    assert cfg.password == "brand-new-pw"


def test_explicit_admin_user_overrides_preserved(setup_module, tmp_path):
    mod = setup_module
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    (niwa_home / "secrets" / "mcp.env").write_text(
        'NIWA_APP_USERNAME="alice"\n'
    )
    args = _args(dir=str(niwa_home), admin_user="bob")
    cfg = mod.build_quick_config(args)
    assert cfg.username == "bob"


# ── _load_existing_mcp_env edge cases ───────────────────────────────


def test_load_existing_mcp_env_none_when_dir_missing(setup_module, tmp_path):
    mod = setup_module
    assert mod._load_existing_mcp_env(tmp_path / "no-install") is None


def test_load_existing_mcp_env_none_when_file_missing(setup_module, tmp_path):
    mod = setup_module
    (tmp_path / "secrets").mkdir()
    assert mod._load_existing_mcp_env(tmp_path) is None


def test_load_existing_mcp_env_returns_dict_when_present(setup_module, tmp_path):
    mod = setup_module
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "mcp.env").write_text(
        'NIWA_LOCAL_TOKEN="xyz"\nNIWA_APP_USERNAME="alice"\n'
    )
    env = mod._load_existing_mcp_env(tmp_path)
    assert env["NIWA_LOCAL_TOKEN"] == "xyz"
    assert env["NIWA_APP_USERNAME"] == "alice"


# ── Partial preservation: some keys missing in existing env ─────────


def test_reinstall_regenerates_missing_keys_but_keeps_present_ones(setup_module, tmp_path):
    """If the existing mcp.env is incomplete (e.g. older install with
    fewer fields), preserve what's there and generate what's missing."""
    mod = setup_module
    niwa_home = tmp_path / "niwa-home"
    (niwa_home / "secrets").mkdir(parents=True)
    # Only LOCAL and password persisted; remote + session_secret absent.
    (niwa_home / "secrets" / "mcp.env").write_text(
        'NIWA_LOCAL_TOKEN="only-local"\nNIWA_APP_PASSWORD="only-pw"\n'
    )
    args = _args(dir=str(niwa_home))
    cfg = mod.build_quick_config(args)
    assert cfg.tokens["NIWA_LOCAL_TOKEN"] == "only-local"
    assert cfg.password == "only-pw"
    # Generated because missing.
    assert cfg.tokens["NIWA_REMOTE_TOKEN"]
    assert cfg.tokens["NIWA_REMOTE_TOKEN"] != "only-local"
    assert cfg.tokens["NIWA_APP_SESSION_SECRET"]
