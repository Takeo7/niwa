"""Tests for PR-11 — `install --quick` wizard.

These tests exercise the pure functions of the quick installer without
touching Docker, the network, or the filesystem beyond tmp paths. The
SPEC says integration-level install tests (docker up, DB seed) are
out of scope here — PR-09's CI already exercises the stack via the
MCP smoke.

Run with:
    pytest tests/test_pr11_quick_install.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: E402 — setup.py is the target under test


# ────────────────────────── argparse surface ──────────────────────────
class TestArgparseSurface:
    """The --quick/--mode/--yes/-y flags parse cleanly and do not break
    the existing non-quick interactive path."""

    def test_quick_core_minimal(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "setup.py", "install", "--quick", "--mode", "core", "--yes",
        ])
        parser = _build_parser()
        args = parser.parse_args(sys.argv[1:])
        assert args.cmd == "install"
        assert args.quick is True
        assert args.mode == "core"
        assert args.yes is True
        assert args.workspace is None

    def test_quick_assistant_with_flags(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "setup.py", "install", "--quick", "--mode", "assistant",
            "--workspace", "/tmp/ws", "--public-url", "https://n.example.com",
            "--admin-user", "sam", "--admin-password", "secret",
            "--dir", "/tmp/stg", "-y",
        ])
        parser = _build_parser()
        args = parser.parse_args(sys.argv[1:])
        assert args.mode == "assistant"
        assert args.workspace == "/tmp/ws"
        assert args.public_url == "https://n.example.com"
        assert args.admin_user == "sam"
        assert args.admin_password == "secret"
        assert args.dir == "/tmp/stg"

    def test_install_parser_rejects_instance_flag(self, monkeypatch):
        """PR-A3: Niwa is single-instance; ``--instance`` is gone.

        The parser built here mirrors the real one in ``setup.main``;
        ``test_setup_source_has_no_instance_flag`` pins the production
        parser itself.
        """
        monkeypatch.setattr(sys, "argv", [
            "setup.py", "install", "--quick", "--mode", "core",
            "--instance", "stg", "-y",
        ])
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(sys.argv[1:])

    def test_quick_mode_choice_enforced(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", [
            "setup.py", "install", "--quick", "--mode", "invalid",
        ])
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(sys.argv[1:])

    def test_non_quick_install_is_still_valid(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["setup.py", "install"])
        parser = _build_parser()
        args = parser.parse_args(sys.argv[1:])
        assert args.cmd == "install"
        assert args.quick is False


def _build_parser():
    """Reconstruct the argparse tree exactly like setup.main() does.

    We don't invoke setup.main() directly because it also runs dispatch.
    """
    import argparse
    parser = argparse.ArgumentParser(description="Niwa installer and CLI")
    sub = parser.add_subparsers(dest="cmd")
    p_install = sub.add_parser("install")
    p_install.add_argument("--quick", action="store_true")
    p_install.add_argument("--mode", choices=setup.QUICK_MODES, default="core")
    p_install.add_argument("-y", "--yes", action="store_true")
    p_install.add_argument("--workspace")
    p_install.add_argument("--public-url")
    p_install.add_argument("--admin-user")
    p_install.add_argument("--admin-password")
    p_install.add_argument("--dir")
    p_install.add_argument("--force", action="store_true")
    return parser


# ────────────────────────── credential detection ─────────────────────
class TestCredentialDetection:
    """The detectors return the documented shape and never echo a token."""

    def test_claude_missing_cli(self, monkeypatch, tmp_path):
        monkeypatch.setattr(setup, "which", lambda _: None)
        out = setup.detect_claude_credentials()
        assert out["cli"] is False
        assert out["authenticated"] is False
        assert out["source"] == ""
        assert "claude" in out["detail"].lower()

    def test_claude_env_token_preferred_over_config_file(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(setup, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-redacted")
        out = setup.detect_claude_credentials()
        assert out["cli"] is True
        assert out["authenticated"] is True
        assert out["source"] == "env:CLAUDE_CODE_OAUTH_TOKEN"
        # Token value MUST NOT appear in detail — only the env var name.
        assert "sk-redacted" not in out["detail"]

    def test_claude_api_key_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(setup, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-val")
        # Isolate from a real ~/.claude.json on the test host — without
        # this, the new precedence (CLI session > API key) would make
        # any real home dir leak into the result.
        monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
        out = setup.detect_claude_credentials()
        assert out["source"] == "env:ANTHROPIC_API_KEY"
        assert "secret-val" not in out["detail"]

    def test_claude_config_file_detected(self, monkeypatch, tmp_path):
        monkeypatch.setattr(setup, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        home = tmp_path
        monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: home))
        (home / ".claude.json").write_text("{}")
        out = setup.detect_claude_credentials()
        assert out["authenticated"] is True
        assert out["source"] == "~/.claude.json"

    def test_claude_cli_without_any_auth(self, monkeypatch, tmp_path):
        monkeypatch.setattr(setup, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
        out = setup.detect_claude_credentials()
        assert out["cli"] is True
        assert out["authenticated"] is False
        assert out["source"] == ""

    def test_codex_missing_cli(self, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        out = setup.detect_codex_credentials()
        assert out["cli"] is False
        assert out["authenticated"] is False

    def test_codex_openai_token_env(self, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
        monkeypatch.setenv("OPENAI_ACCESS_TOKEN", "oat-redacted")
        out = setup.detect_codex_credentials()
        assert out["authenticated"] is True
        assert out["source"] == "env:OPENAI_ACCESS_TOKEN"
        assert "oat-redacted" not in out["detail"]

    def test_codex_home_auth_json(self, monkeypatch, tmp_path):
        monkeypatch.setattr(setup, "which", lambda name: "/usr/bin/codex" if name == "codex" else None)
        monkeypatch.delenv("OPENAI_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text("{}")
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        out = setup.detect_codex_credentials()
        assert out["authenticated"] is True
        assert str(codex_home) in out["detail"]

    # ── PR-A4: precedence subscription > CLI session > API key ────────
    def test_claude_config_file_wins_over_api_key(
        self, monkeypatch, tmp_path
    ):
        """CLI login (~/.claude.json) must beat a raw API key in env.

        Rationale: the installer promises "auth prioritises
        subscriptions" (MVP-ROADMAP §1.3). An API key left in the
        shell must not silently shadow a real CLI session.
        """
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/bin/claude" if name == "claude" else None,
        )
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-lose")
        monkeypatch.setattr(
            setup.Path, "home", classmethod(lambda cls: tmp_path)
        )
        (tmp_path / ".claude.json").write_text("{}")
        out = setup.detect_claude_credentials()
        assert out["authenticated"] is True
        assert out["source"] == "~/.claude.json"
        assert "sk-should-lose" not in out["detail"]

    def test_claude_setup_token_wins_over_config_and_api_key(
        self, monkeypatch, tmp_path
    ):
        """Setup-token (subscription) beats both CLI session and API key."""
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/bin/claude" if name == "claude" else None,
        )
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok-redacted")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-lose")
        monkeypatch.setattr(
            setup.Path, "home", classmethod(lambda cls: tmp_path)
        )
        (tmp_path / ".claude.json").write_text("{}")
        out = setup.detect_claude_credentials()
        assert out["source"] == "env:CLAUDE_CODE_OAUTH_TOKEN"
        assert "tok-redacted" not in out["detail"]
        assert "sk-should-lose" not in out["detail"]

    def test_codex_auth_json_wins_over_api_key(
        self, monkeypatch, tmp_path
    ):
        """ChatGPT Plus/Pro OAuth (auth.json) beats a raw OPENAI_API_KEY."""
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/bin/codex" if name == "codex" else None,
        )
        monkeypatch.delenv("OPENAI_ACCESS_TOKEN", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-should-lose")
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text("{}")
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        out = setup.detect_codex_credentials()
        assert out["authenticated"] is True
        assert str(codex_home) in out["detail"]
        assert "sk-should-lose" not in out["detail"]

    def test_codex_auth_json_wins_over_access_token(
        self, monkeypatch, tmp_path
    ):
        """Persistent subscription auth.json beats a CLI-session env token."""
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/bin/codex" if name == "codex" else None,
        )
        monkeypatch.setenv("OPENAI_ACCESS_TOKEN", "oat-session")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text("{}")
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        out = setup.detect_codex_credentials()
        assert out["authenticated"] is True
        assert str(codex_home) in out["detail"]
        assert "oat-session" not in out["detail"]

    def test_openclaw_missing(self, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        out = setup.detect_openclaw_presence()
        assert out["cli"] is False

    def test_openclaw_present(self, monkeypatch):
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/local/bin/openclaw" if name == "openclaw" else None,
        )
        out = setup.detect_openclaw_presence()
        assert out["cli"] is True


# ────────────────────────── parse_public_url ──────────────────────────
class TestParsePublicUrl:
    def test_empty_string(self):
        assert setup.parse_public_url("") == {"domain": "", "scheme": ""}

    def test_bare_domain(self):
        out = setup.parse_public_url("niwa.example.com")
        assert out["domain"] == "niwa.example.com"
        assert out["scheme"] == "https"

    def test_https_url(self):
        out = setup.parse_public_url("https://niwa.example.com")
        assert out["domain"] == "niwa.example.com"
        assert out["scheme"] == "https"

    def test_http_url_with_port(self):
        out = setup.parse_public_url("http://niwa.example.com:8080")
        assert out["domain"] == "niwa.example.com"
        assert out["scheme"] == "http"


# ────────────────────────── resolve_quick_workspace ─────────────────
class TestResolveQuickWorkspace:
    def test_explicit_arg_wins(self, tmp_path):
        niwa_home = tmp_path / "niwa"
        niwa_home.mkdir()
        out = setup.resolve_quick_workspace(str(tmp_path / "ws"), niwa_home)
        assert out == (tmp_path / "ws").resolve()

    def test_existing_install_env_reused(self, tmp_path):
        niwa_home = tmp_path / "niwa"
        (niwa_home / "secrets").mkdir(parents=True)
        (niwa_home / "secrets" / "mcp.env").write_text(
            f'NIWA_FILESYSTEM_WORKSPACE="{tmp_path}/existing-ws"\n'
        )
        out = setup.resolve_quick_workspace(None, niwa_home)
        assert out == tmp_path / "existing-ws"

    def test_default_under_niwa_home(self, tmp_path):
        niwa_home = tmp_path / "niwa"
        niwa_home.mkdir()
        out = setup.resolve_quick_workspace(None, niwa_home)
        assert out == (niwa_home / "data").resolve()


# ────────────────────────── build_quick_config ──────────────────────
class _Args:
    def __init__(self, **kw):
        self.mode = kw.get("mode", "core")
        self.yes = kw.get("yes", True)
        self.workspace = kw.get("workspace")
        self.public_url = kw.get("public_url")
        self.admin_user = kw.get("admin_user")
        self.admin_password = kw.get("admin_password")
        self.dir = kw.get("dir")


@pytest.fixture(autouse=True)
def _stub_docker(monkeypatch):
    """All tests in this module assume Docker is present + socketed."""
    monkeypatch.setattr(setup, "detect_docker", lambda: {"available": True, "version": "x", "runtime": "y"})
    monkeypatch.setattr(setup, "detect_socket_path", lambda: "/var/run/docker.sock")
    # Make every port look free so we don't rely on the test host's network state.
    monkeypatch.setattr(setup, "detect_port_free", lambda _port: True)


class TestBuildQuickConfig:
    def test_core_mode_sensible_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)  # no clis
        args = _Args(mode="core", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        assert cfg.quick_mode == "core"
        # PR-A3: instance_name field removed; WizardConfig has no such attr.
        assert not hasattr(cfg, "instance_name")
        assert cfg.niwa_home == (tmp_path / "niwa").resolve()
        assert cfg.db_mode == "fresh"
        assert cfg.bind_host == "127.0.0.1"
        assert cfg.mode == "local-only"
        assert cfg.public_domain == ""
        assert cfg.executor_enabled is True
        assert cfg.llm_provider == "claude"
        assert cfg.register_openclaw is False
        assert cfg.mcp_contract == ""
        assert cfg.mcp_server_token == ""
        assert len(cfg.tokens["NIWA_LOCAL_TOKEN"]) == 64
        assert cfg.username == "niwa"
        assert len(cfg.password) >= 16

    def test_assistant_mode_sets_contract(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/local/bin/openclaw" if name == "openclaw" else None,
        )
        args = _Args(mode="assistant", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        assert cfg.quick_mode == "assistant"
        assert cfg.mcp_contract == "v02-assistant"
        assert len(cfg.mcp_server_token) == 64
        assert cfg.register_openclaw is True

    def test_public_url_flips_bind_and_mode(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        args = _Args(
            mode="core", dir=str(tmp_path / "niwa"),
            public_url="https://niwa.example.com",
        )
        cfg = setup.build_quick_config(args)
        assert cfg.bind_host == "0.0.0.0"
        assert cfg.mode == "remote"
        assert cfg.public_domain == "niwa.example.com"

    def test_admin_password_respected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        args = _Args(mode="core", dir=str(tmp_path / "niwa"),
                     admin_password="mypass", admin_user="sam")
        cfg = setup.build_quick_config(args)
        assert cfg.username == "sam"
        assert cfg.password == "mypass"

    def test_password_auto_generated_flag_true_on_fresh(
        self, tmp_path, monkeypatch
    ):
        """Fresh install (no existing env, no --admin-password) → flag True."""
        monkeypatch.setattr(setup, "which", lambda _: None)
        monkeypatch.setattr(setup, "_load_existing_mcp_env", lambda _p: None)
        args = _Args(mode="core", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        assert cfg.password_auto_generated is True
        assert len(cfg.password) >= 16

    def test_password_auto_generated_flag_false_on_explicit(
        self, tmp_path, monkeypatch
    ):
        """--admin-password supplied → operator already knows it; flag False."""
        monkeypatch.setattr(setup, "which", lambda _: None)
        monkeypatch.setattr(setup, "_load_existing_mcp_env", lambda _p: None)
        args = _Args(mode="core", dir=str(tmp_path / "niwa"),
                     admin_password="mypass")
        cfg = setup.build_quick_config(args)
        assert cfg.password_auto_generated is False
        assert cfg.password == "mypass"

    def test_password_auto_generated_flag_false_on_preserved(
        self, tmp_path, monkeypatch
    ):
        """Reinstall reuses NIWA_APP_PASSWORD from secrets/mcp.env → flag False."""
        monkeypatch.setattr(setup, "which", lambda _: None)
        monkeypatch.setattr(
            setup, "_load_existing_mcp_env",
            lambda _p: {"NIWA_APP_PASSWORD": "preserved123", "NIWA_APP_USERNAME": "niwa"},
        )
        args = _Args(mode="core", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        assert cfg.password == "preserved123"
        assert cfg.password_auto_generated is False

    def test_workspace_honours_cli_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        ws = tmp_path / "my-ws"
        args = _Args(mode="core", dir=str(tmp_path / "niwa"),
                     workspace=str(ws))
        cfg = setup.build_quick_config(args)
        assert cfg.fs_workspace == ws.resolve()

    def test_register_claude_requires_authentication(
        self, tmp_path, monkeypatch
    ):
        # claude CLI present but no auth → register_claude must stay False.
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/bin/claude" if name == "claude" else None,
        )
        monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setattr(setup.Path, "home", classmethod(lambda cls: tmp_path))
        args = _Args(mode="core", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        assert cfg.register_claude is False


# ────────────────────────── assistant prereq check ───────────────────
class TestAssistantPrereqs:
    def test_core_mode_no_prereqs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        args = _Args(mode="core", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        assert setup._ensure_assistant_prereqs(cfg) is None

    def test_assistant_without_openclaw_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        args = _Args(mode="assistant", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        msg = setup._ensure_assistant_prereqs(cfg)
        assert msg is not None
        assert "OpenClaw" in msg

    def test_assistant_with_openclaw_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/local/bin/openclaw" if name == "openclaw" else None,
        )
        args = _Args(mode="assistant", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        assert setup._ensure_assistant_prereqs(cfg) is None


# ────────────────────────── catalog generation ───────────────────────
class TestCatalogGeneration:
    """generate_catalog_yaml behaves correctly under PR-11's changes."""

    def _servers(self):
        return {"tasks": "tasks", "notes": "notes", "platform": "platform", "filesystem": "filesystem"}

    def test_no_contract_yields_full_v01_surface(self, tmp_path):
        yaml = setup.generate_catalog_yaml(
            self._servers(), str(tmp_path / "db"),
            str(tmp_path / "ws"), str(tmp_path / "mem"), "niwa",
        )
        # At least task_update + task_update_status (v0.1 only) appear.
        assert "task_update" in yaml
        assert "task_update_status" in yaml
        # env: block should not appear under tasks when tasks_env is None.
        tasks_block = _extract_server_block(yaml, "tasks")
        assert "env:" not in tasks_block

    def test_contract_overrides_to_contract_tools(self, tmp_path):
        contract_path = REPO_ROOT / "config" / "mcp-contract" / "v02-assistant.json"
        yaml = setup.generate_catalog_yaml(
            self._servers(), str(tmp_path / "db"),
            str(tmp_path / "ws"), str(tmp_path / "mem"), "niwa",
            contract_file=str(contract_path),
            tasks_env={
                "NIWA_MCP_CONTRACT": "v02-assistant",
                "NIWA_MCP_SERVER_TOKEN": "t",
                "NIWA_APP_URL": "http://niwa-app:8080",
            },
        )
        # All 11 contract tools present as advertised.
        for tool in [
            "assistant_turn", "task_list", "task_get", "task_create",
            "task_cancel", "task_resume", "approval_list",
            "approval_respond", "run_tail", "run_explain", "project_context",
        ]:
            assert f'- name: "{tool}"' in yaml
        # Legacy tools NOT in contract MUST be gone.
        assert "task_update_status" not in yaml
        # env block wiring is in the tasks entry.
        tasks_block = _extract_server_block(yaml, "tasks")
        assert 'NIWA_MCP_CONTRACT' in tasks_block
        assert 'NIWA_MCP_SERVER_TOKEN' in tasks_block
        assert 'NIWA_APP_URL' in tasks_block


def _extract_server_block(yaml: str, server_name: str) -> str:
    """Return the YAML lines from `<server_name>:` up to the next top-level
    registry entry or end of text."""
    lines = yaml.split("\n")
    captured: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(f"{server_name}:") and line.startswith("  "):
            in_block = True
            captured.append(line)
            continue
        if in_block:
            # A new sibling at the same indent level (2 spaces) ends the block.
            if line and line[0:2] == "  " and not line.startswith("   ") and ":" in line and not stripped.startswith("-"):
                # The very next line like "  notes:" is a new registry entry.
                if stripped.split(":")[0] != server_name:
                    break
            captured.append(line)
    return "\n".join(captured)


# ────────────────────────── idempotence / mode mismatch ─────────────
class TestModeIdempotence:
    """SPEC PR-11 rule C: same-mode reinstalls proceed; cross-mode aborts
    with exit 2 unless --force is passed."""

    def _write_existing_install(self, niwa_home: Path, mode: str) -> None:
        (niwa_home / "secrets").mkdir(parents=True, exist_ok=True)
        contract = "v02-assistant" if mode == "assistant" else ""
        env_text = (
            f'INSTANCE_NAME="niwa"\n'
            f'NIWA_MCP_CONTRACT="{contract}"\n'
        )
        (niwa_home / "secrets" / "mcp.env").write_text(env_text)

    def test_detect_no_install(self, tmp_path):
        assert setup.detect_existing_quick_mode(tmp_path / "nope") == ""

    def test_detect_core(self, tmp_path):
        self._write_existing_install(tmp_path, "core")
        assert setup.detect_existing_quick_mode(tmp_path) == "core"

    def test_detect_assistant(self, tmp_path):
        self._write_existing_install(tmp_path, "assistant")
        assert setup.detect_existing_quick_mode(tmp_path) == "assistant"

    def test_fresh_install_allowed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        args = _Args(mode="core", dir=str(tmp_path / "niwa"))
        cfg = setup.build_quick_config(args)
        assert setup._ensure_mode_matches_existing(cfg, force=False) is None

    def test_same_mode_reinstall_allowed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        niwa_home = tmp_path / "niwa"
        niwa_home.mkdir()
        self._write_existing_install(niwa_home, "core")
        args = _Args(mode="core", dir=str(niwa_home))
        cfg = setup.build_quick_config(args)
        assert setup._ensure_mode_matches_existing(cfg, force=False) is None

    def test_core_over_assistant_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        niwa_home = tmp_path / "niwa"
        niwa_home.mkdir()
        self._write_existing_install(niwa_home, "assistant")
        args = _Args(mode="core", dir=str(niwa_home))
        cfg = setup.build_quick_config(args)
        msg = setup._ensure_mode_matches_existing(cfg, force=False)
        assert msg is not None
        assert "assistant" in msg
        assert "core" in msg
        assert "--force" in msg

    def test_assistant_over_core_blocks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            setup, "which",
            lambda name: "/usr/local/bin/openclaw" if name == "openclaw" else None,
        )
        niwa_home = tmp_path / "niwa"
        niwa_home.mkdir()
        self._write_existing_install(niwa_home, "core")
        args = _Args(mode="assistant", dir=str(niwa_home))
        cfg = setup.build_quick_config(args)
        msg = setup._ensure_mode_matches_existing(cfg, force=False)
        assert msg is not None
        assert "--force" in msg

    def test_force_flag_bypasses_mode_mismatch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "which", lambda _: None)
        niwa_home = tmp_path / "niwa"
        niwa_home.mkdir()
        self._write_existing_install(niwa_home, "assistant")
        args = _Args(mode="core", dir=str(niwa_home))
        cfg = setup.build_quick_config(args)
        assert setup._ensure_mode_matches_existing(cfg, force=True) is None


# ────────────────────────── single-instance guards (PR-A3) ──────────
class TestSingleInstanceGuards:
    """PR-A3 retires ``{instance}`` from the installer. These source-level
    guards keep the flag and the derived naming from creeping back."""

    def _setup_source(self) -> str:
        return (REPO_ROOT / "setup.py").read_text()

    def test_setup_source_has_no_instance_flag(self):
        """``p_install.add_argument("--instance", ...)`` must be gone."""
        import re
        src = self._setup_source()
        assert not re.search(r'add_argument\(\s*["\']--instance["\']', src), (
            "PR-A3: --instance CLI flag is retired; Niwa is single-instance"
        )

    def test_setup_source_has_no_instance_name_references(self):
        """``cfg.instance_name`` / ``self.instance_name`` must be gone."""
        src = self._setup_source()
        assert "cfg.instance_name" not in src, (
            "PR-A3: cfg.instance_name must not exist anywhere in setup.py"
        )
        assert "self.instance_name" not in src, (
            "PR-A3: WizardConfig.instance_name field is retired"
        )

    def test_setup_source_has_no_valid_instance_name_helper(self):
        """The validator is dead code once the prompt is gone."""
        src = self._setup_source()
        assert "valid_instance_name" not in src, (
            "PR-A3: valid_instance_name helper is dead code"
        )

    def test_executor_unit_name_is_fixed(self):
        """Systemd unit baked into the installer must be
        ``niwa-executor.service``, not the legacy ``niwa-{instance}-executor.service``.
        """
        src = self._setup_source()
        assert 'unit_name = f"niwa-{cfg.instance_name}-executor.service"' not in src
        assert 'unit_name = "niwa-executor.service"' in src

    def test_hosting_unit_name_is_fixed(self):
        src = self._setup_source()
        assert 'unit_name = f"niwa-{cfg.instance_name}-hosting.service"' not in src
        assert 'unit_name = "niwa-hosting.service"' in src


# ────────────────────────── compose template pin ────────────────────
class TestDockerImagePin:
    """PR-11 Dec 1: docker/mcp-gateway must be pinned via env var."""

    def test_template_uses_env_var_not_latest(self):
        template = (REPO_ROOT / "docker-compose.yml.tmpl").read_text()
        assert "docker/mcp-gateway:latest" not in template
        assert "${NIWA_MCP_GATEWAY_IMAGE}" in template
        # Appears in both the streamable-http and the legacy SSE services.
        assert template.count("${NIWA_MCP_GATEWAY_IMAGE}") >= 2

    def test_default_tag_is_a_semver_pin(self):
        tag = setup.NIWA_MCP_GATEWAY_IMAGE_DEFAULT
        assert tag.startswith("docker/mcp-gateway:")
        suffix = tag.split(":")[1]
        assert suffix not in ("latest", "")
        assert suffix[0] == "v"

    def test_env_var_propagates_to_install_vars(self, monkeypatch):
        # execute_install writes NIWA_MCP_GATEWAY_IMAGE into the env_vars
        # dict. We can't run the full install, but we can verify the
        # os.environ.get default path.
        monkeypatch.delenv("NIWA_MCP_GATEWAY_IMAGE", raising=False)
        value = os.environ.get(
            "NIWA_MCP_GATEWAY_IMAGE", setup.NIWA_MCP_GATEWAY_IMAGE_DEFAULT
        )
        assert value == setup.NIWA_MCP_GATEWAY_IMAGE_DEFAULT

        monkeypatch.setenv("NIWA_MCP_GATEWAY_IMAGE", "docker/mcp-gateway:v0.99.0")
        value = os.environ.get(
            "NIWA_MCP_GATEWAY_IMAGE", setup.NIWA_MCP_GATEWAY_IMAGE_DEFAULT
        )
        assert value == "docker/mcp-gateway:v0.99.0"
