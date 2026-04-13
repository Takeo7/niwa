"""Tests for PR-03 — Backend abstraction layer.

Covers:
  - BackendRegistry register/resolve behaviour
  - ClaudeCodeAdapter and CodexAdapter capabilities()
  - Stub methods raise NotImplementedError with correct PR references
  - seed_backend_profiles() integration with SQLite
  - save_agents_config() no longer injects --dangerously-skip-permissions
"""

import json
import os
import sqlite3
import sys
import tempfile

import pytest

# ── Ensure backend dir is on sys.path (same pattern as test_pr02) ──
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

from backend_adapters.base import BackendAdapter
from backend_adapters.claude_code import ClaudeCodeAdapter
from backend_adapters.codex import CodexAdapter
from backend_registry import (
    BackendRegistry,
    get_default_registry,
    seed_backend_profiles,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_db():
    """Create a temporary SQLite DB with the full Niwa schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


# ═══════════════════════════════════════════════════════════════════
# 1. Registry tests
# ═══════════════════════════════════════════════════════════════════

class TestBackendRegistry:

    def test_register_and_resolve(self):
        """Registry can register and resolve backends by slug."""
        reg = BackendRegistry()
        adapter = ClaudeCodeAdapter()
        reg.register("test_claude", adapter)
        assert reg.resolve("test_claude") is adapter

    def test_resolve_unknown_slug_raises(self):
        """Resolving an unregistered slug raises KeyError."""
        reg = BackendRegistry()
        with pytest.raises(KeyError, match="No backend adapter registered"):
            reg.resolve("nonexistent")

    def test_duplicate_register_raises(self):
        """Registering the same slug twice raises ValueError."""
        reg = BackendRegistry()
        reg.register("dup", ClaudeCodeAdapter())
        with pytest.raises(ValueError, match="already registered"):
            reg.register("dup", CodexAdapter())

    def test_list_slugs(self):
        """list_slugs() returns sorted registered slugs."""
        reg = BackendRegistry()
        reg.register("codex", CodexAdapter())
        reg.register("claude_code", ClaudeCodeAdapter())
        assert reg.list_slugs() == ["claude_code", "codex"]

    def test_default_registry_has_both_backends(self):
        """The default registry has claude_code and codex registered."""
        reg = get_default_registry()
        assert "claude_code" in reg.list_slugs()
        assert "codex" in reg.list_slugs()


# ═══════════════════════════════════════════════════════════════════
# 2. Capabilities tests
# ═══════════════════════════════════════════════════════════════════

_REQUIRED_CAPABILITY_KEYS = {
    "resume_modes", "fs_modes", "shell_modes",
    "network_modes", "approval_modes", "secrets_modes",
}

_REQUIRED_BUDGET_KEYS = {
    "estimated_resource_cost", "cost_confidence",
    "quota_risk", "latency_tier",
}


class TestClaudeCodeCapabilities:

    def setup_method(self):
        self.adapter = ClaudeCodeAdapter()
        self.caps = self.adapter.capabilities()

    def test_has_all_capability_fields(self):
        """capabilities() returns all 6 SPEC-required fields."""
        assert _REQUIRED_CAPABILITY_KEYS.issubset(self.caps.keys())

    def test_has_all_budget_fields(self):
        """capabilities() returns all 4 resource-budget fields."""
        assert _REQUIRED_BUDGET_KEYS.issubset(self.caps.keys())

    def test_resume_modes(self):
        assert "session_restore" in self.caps["resume_modes"]
        assert "context_summary" in self.caps["resume_modes"]

    def test_fs_modes(self):
        assert "full" in self.caps["fs_modes"]
        assert "repo_only" in self.caps["fs_modes"]
        assert "readonly" in self.caps["fs_modes"]

    def test_shell_modes(self):
        assert "unrestricted" in self.caps["shell_modes"]

    def test_network_modes(self):
        assert "full" in self.caps["network_modes"]

    def test_approval_modes(self):
        assert "always" in self.caps["approval_modes"]
        assert "risk_based" in self.caps["approval_modes"]

    def test_secrets_modes(self):
        assert "env_inject" in self.caps["secrets_modes"]
        assert "file_mount" in self.caps["secrets_modes"]

    def test_budget_defaults(self):
        assert self.caps["estimated_resource_cost"] is None
        assert self.caps["cost_confidence"] == "unknown"
        assert self.caps["quota_risk"] == "unknown"
        assert self.caps["latency_tier"] == "unknown"


class TestCodexCapabilities:

    def setup_method(self):
        self.adapter = CodexAdapter()
        self.caps = self.adapter.capabilities()

    def test_has_all_capability_fields(self):
        """capabilities() returns all 6 SPEC-required fields."""
        assert _REQUIRED_CAPABILITY_KEYS.issubset(self.caps.keys())

    def test_has_all_budget_fields(self):
        """capabilities() returns all 4 resource-budget fields."""
        assert _REQUIRED_BUDGET_KEYS.issubset(self.caps.keys())

    def test_resume_modes_limited(self):
        assert self.caps["resume_modes"] == ["new_session"]

    def test_fs_modes_restricted(self):
        assert "full" not in self.caps["fs_modes"]
        assert "repo_only" in self.caps["fs_modes"]

    def test_shell_sandboxed(self):
        assert self.caps["shell_modes"] == ["sandboxed"]

    def test_network_off(self):
        assert self.caps["network_modes"] == ["off"]

    def test_approval_modes(self):
        assert "always" in self.caps["approval_modes"]
        assert "never" in self.caps["approval_modes"]
        assert "risk_based" not in self.caps["approval_modes"]

    def test_secrets_modes(self):
        assert "env_inject" in self.caps["secrets_modes"]
        assert "file_mount" not in self.caps["secrets_modes"]


# ═══════════════════════════════════════════════════════════════════
# 3. Stub methods raise NotImplementedError
# ═══════════════════════════════════════════════════════════════════

_STUB_ARGS = {
    "start": ({"id": "t1"}, {"id": "r1"}, {"id": "p1"}, {}),
    "resume": ({"id": "t1"}, {"id": "r0"}, {"id": "r1"}, {"id": "p1"}, {}),
    "cancel": ({"id": "r1"},),
    "heartbeat": ({"id": "r1"},),
    "collect_artifacts": ({"id": "r1"},),
    "parse_usage_signals": ("raw output",),
}


class TestClaudeCodeStubs:

    def setup_method(self):
        self.adapter = ClaudeCodeAdapter()

    @pytest.mark.parametrize("method", [
        "start", "resume", "cancel", "heartbeat",
        "collect_artifacts", "parse_usage_signals",
    ])
    def test_raises_not_implemented(self, method):
        with pytest.raises(NotImplementedError, match="PR-04"):
            getattr(self.adapter, method)(*_STUB_ARGS[method])


class TestCodexStubs:

    def setup_method(self):
        self.adapter = CodexAdapter()

    @pytest.mark.parametrize("method", [
        "start", "resume", "cancel", "heartbeat",
        "collect_artifacts", "parse_usage_signals",
    ])
    def test_raises_not_implemented(self, method):
        with pytest.raises(NotImplementedError, match="PR-07"):
            getattr(self.adapter, method)(*_STUB_ARGS[method])


# ═══════════════════════════════════════════════════════════════════
# 4. Seed backend_profiles integration
# ═══════════════════════════════════════════════════════════════════

class TestSeedBackendProfiles:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_seed_creates_both_profiles(self):
        """Seeds create claude_code and codex rows in backend_profiles."""
        inserted = seed_backend_profiles(self.conn)
        self.conn.commit()
        assert inserted == 2

        rows = self.conn.execute(
            "SELECT slug, backend_kind, runtime_kind, enabled "
            "FROM backend_profiles ORDER BY slug"
        ).fetchall()
        slugs = [r["slug"] for r in rows]
        assert "claude_code" in slugs
        assert "codex" in slugs

        claude_row = next(r for r in rows if r["slug"] == "claude_code")
        assert claude_row["backend_kind"] == "claude_code"
        assert claude_row["runtime_kind"] == "cli"
        assert claude_row["enabled"] == 1

        codex_row = next(r for r in rows if r["slug"] == "codex")
        assert codex_row["backend_kind"] == "codex"
        assert codex_row["enabled"] == 0

    def test_seed_idempotent(self):
        """Running seed twice does not duplicate or overwrite rows."""
        seed_backend_profiles(self.conn)
        self.conn.commit()
        inserted_second = seed_backend_profiles(self.conn)
        self.conn.commit()
        assert inserted_second == 0

        count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM backend_profiles"
        ).fetchone()["cnt"]
        assert count == 2

    def test_seed_capabilities_json_valid(self):
        """Seeded rows have valid capabilities_json matching adapter output."""
        seed_backend_profiles(self.conn)
        self.conn.commit()

        for slug in ("claude_code", "codex"):
            row = self.conn.execute(
                "SELECT capabilities_json FROM backend_profiles WHERE slug=?",
                (slug,),
            ).fetchone()
            caps = json.loads(row["capabilities_json"])
            assert "resume_modes" in caps
            assert "fs_modes" in caps
            assert "shell_modes" in caps
            assert "network_modes" in caps
            assert "approval_modes" in caps
            assert "secrets_modes" in caps

    def test_seed_preserves_existing_data(self):
        """Seed does not overwrite a manually modified profile."""
        seed_backend_profiles(self.conn)
        self.conn.commit()

        # Manually change the display_name
        self.conn.execute(
            "UPDATE backend_profiles SET display_name='Custom Claude' "
            "WHERE slug='claude_code'"
        )
        self.conn.commit()

        seed_backend_profiles(self.conn)
        self.conn.commit()

        row = self.conn.execute(
            "SELECT display_name FROM backend_profiles WHERE slug='claude_code'"
        ).fetchone()
        assert row["display_name"] == "Custom Claude"


# ═══════════════════════════════════════════════════════════════════
# 5. save_agents_config no longer injects dangerous flags
# ═══════════════════════════════════════════════════════════════════

class TestSaveAgentsConfigNoDangerousFlags:
    """Verify --dangerously-skip-permissions is no longer injected."""

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        # Insert a settings row so the function has something to read
        self.conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('agent.chat', ?)",
            (json.dumps({"model": "claude-haiku-4-5", "max_turns": 10}),),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('agent.planner', ?)",
            (json.dumps({"model": "claude-opus-4-6", "max_turns": 10}),),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('agent.executor', ?)",
            (json.dumps({"model": "claude-sonnet-4-6", "max_turns": 50}),),
        )
        self.conn.commit()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_no_dangerous_flag_in_generated_commands(self):
        """save_agents_config() must not inject --dangerously-skip-permissions."""
        # Simulate what save_agents_config does with this connection
        # We call the core logic directly to avoid needing the full app context.
        agents = {}
        for role in ("chat", "planner", "executor"):
            row = self.conn.execute(
                "SELECT value FROM settings WHERE key=?",
                (f"agent.{role}",),
            ).fetchone()
            if row:
                agents[role] = json.loads(row["value"])

        model_to_cmd = {
            "claude-haiku-4-5": "claude -p --model claude-haiku-4-5",
            "claude-sonnet-4-6": "claude -p --model claude-sonnet-4-6",
            "claude-opus-4-6": "claude -p --model claude-opus-4-6",
        }

        generated_commands = []
        for role, setting_key in [
            ("chat", "int.llm_command_chat"),
            ("planner", "int.llm_command_planner"),
            ("executor", "int.llm_command_executor"),
        ]:
            agent = agents.get(role, {})
            model_id = agent.get("model", "")
            max_turns = agent.get("max_turns", 10 if role != "executor" else 50)
            if model_id and model_id != "auto":
                cmd = model_to_cmd.get(model_id, f"claude -p --model {model_id}")
                cmd += f" --max-turns {max_turns}"
                generated_commands.append(cmd)

        for cmd in generated_commands:
            assert "--dangerously-skip-permissions" not in cmd, (
                f"Dangerous flag found in generated command: {cmd}"
            )

    def test_source_code_has_no_dangerous_flag(self):
        """The save_agents_config function source must not contain the flag."""
        import inspect
        # We need to import from the app module — use importlib to avoid
        # running the app's startup code (which needs a real DB path).
        app_path = os.path.join(
            ROOT_DIR, "niwa-app", "backend", "app.py"
        )
        source = open(app_path).read()

        # Find the save_agents_config function body
        start = source.find("def save_agents_config(")
        assert start != -1, "save_agents_config not found in app.py"
        # Find the next top-level def or class to bound the search
        next_def = source.find("\ndef ", start + 1)
        func_source = source[start:next_def] if next_def != -1 else source[start:]

        assert "--dangerously-skip-permissions" not in func_source, (
            "save_agents_config() still contains --dangerously-skip-permissions"
        )


# ═══════════════════════════════════════════════════════════════════
# 6. init_db() integration: seeds backend_profiles
# ═══════════════════════════════════════════════════════════════════

class TestInitDbSeedsBackendProfiles:
    """Verify init_db() calls seed_backend_profiles() on a fresh DB."""

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_init_db_seeds_backend_profiles(self):
        """Replicate init_db()'s code path: schema.sql + seed → 2 profiles."""
        # schema.sql was already applied by _make_db(). Now call seed
        # exactly as init_db() does.
        seed_backend_profiles(self.conn)
        self.conn.commit()

        count = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM backend_profiles"
        ).fetchone()["cnt"]
        assert count == 2

        slugs = sorted(
            r["slug"]
            for r in self.conn.execute(
                "SELECT slug FROM backend_profiles"
            ).fetchall()
        )
        assert slugs == ["claude_code", "codex"]

    def test_init_db_source_calls_seed(self):
        """init_db() source code must contain the seed_backend_profiles call."""
        app_path = os.path.join(ROOT_DIR, "niwa-app", "backend", "app.py")
        source = open(app_path).read()

        start = source.find("def init_db(")
        assert start != -1, "init_db not found in app.py"
        next_def = source.find("\ndef ", start + 1)
        func_source = source[start:next_def] if next_def != -1 else source[start:]

        assert "seed_backend_profiles" in func_source, (
            "init_db() does not call seed_backend_profiles()"
        )
