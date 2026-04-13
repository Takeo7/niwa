"""Tests for PR-05 — capability_service.

Table-driven tests covering each of the 6 capability profile fields:
  1. repo_mode
  2. shell_mode
  3. web_mode
  4. network_mode
  5. filesystem_scope_json
  6. secrets_scope_json (no-op, verified non-breaking)
  7. resource_budget_json (pre-execution check)

Plus: get_effective_profile, seed_capability_profiles, _extract_commands.
"""

import json
import os
import sqlite3
import sys
import tempfile
import uuid

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import capability_service as cs


# ── Helpers ──────────────────────────────────────────────────────

def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _make_profile(**overrides):
    """Build a capability profile dict with sensible defaults."""
    profile = dict(cs.DEFAULT_CAPABILITY_PROFILE)
    profile.update(overrides)
    return profile


def _tool_use_event(tool_name, tool_input=None):
    """Build a tool_use stream-json event."""
    return {
        "type": "tool_use",
        "name": tool_name,
        "input": tool_input or {},
    }


# ═══════════════════════════════════════════════════════════════════
# 1. repo_mode — Write/Edit tool_use
# ═══════════════════════════════════════════════════════════════════

class TestRepoMode:

    @pytest.mark.parametrize("mode,allowed", [
        ("none", False),
        ("read-only", False),
        ("read-write", True),
    ])
    def test_write_tool_respects_repo_mode(self, mode, allowed):
        profile = _make_profile(repo_mode=mode)
        event = _tool_use_event("Write", {"file_path": "/workspace/file.py"})
        result = cs.evaluate_runtime_event(
            event, profile, workspace_path="/workspace",
        )
        assert result["allowed"] == allowed
        if not allowed:
            assert any(t["type"] == "repo_mode_violation"
                       for t in result["triggers"])

    @pytest.mark.parametrize("mode,allowed", [
        ("none", False),
        ("read-only", False),
        ("read-write", True),
    ])
    def test_edit_tool_respects_repo_mode(self, mode, allowed):
        profile = _make_profile(repo_mode=mode)
        event = _tool_use_event("Edit", {"file_path": "/workspace/x.py"})
        result = cs.evaluate_runtime_event(
            event, profile, workspace_path="/workspace",
        )
        assert result["allowed"] == allowed


# ═══════════════════════════════════════════════════════════════════
# 2. shell_mode — Bash tool_use
# ═══════════════════════════════════════════════════════════════════

class TestShellMode:

    def test_disabled_blocks_all_bash(self):
        profile = _make_profile(shell_mode="disabled")
        event = _tool_use_event("Bash", {"command": "ls"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "shell_disabled"
                   for t in result["triggers"])

    def test_whitelist_allows_whitelisted_command(self):
        profile = _make_profile(shell_mode="whitelist")
        for cmd in ["ls", "cat", "grep", "find", "pwd", "echo"]:
            event = _tool_use_event("Bash", {"command": cmd})
            result = cs.evaluate_runtime_event(event, profile)
            assert result["allowed"] is True, f"{cmd} should be allowed"

    def test_whitelist_blocks_non_whitelisted_command(self):
        profile = _make_profile(shell_mode="whitelist")
        event = _tool_use_event("Bash", {"command": "python3 script.py"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "shell_not_whitelisted"
                   for t in result["triggers"])

    def test_free_allows_all_commands(self):
        profile = _make_profile(shell_mode="free")
        event = _tool_use_event("Bash", {"command": "python3 script.py"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True

    def test_whitelist_blocks_chained_command(self):
        """Even if first command is whitelisted, a chained non-whitelisted
        command should trigger denial."""
        profile = _make_profile(shell_mode="whitelist")
        event = _tool_use_event("Bash", {"command": "ls && python3 x.py"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False

    def test_deletion_always_triggers_approval(self):
        """rm triggers deletion approval even with shell_mode=free."""
        profile = _make_profile(shell_mode="free")
        event = _tool_use_event("Bash", {"command": "rm -rf /tmp/stuff"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "deletion"
                   for t in result["triggers"])

    @pytest.mark.parametrize("cmd", ["rm", "rmdir", "unlink", "shred"])
    def test_all_deletion_commands_detected(self, cmd):
        profile = _make_profile(shell_mode="free")
        event = _tool_use_event("Bash", {"command": f"{cmd} somefile"})
        result = cs.evaluate_runtime_event(event, profile)
        assert any(t["type"] == "deletion" for t in result["triggers"])

    def test_custom_whitelist_from_profile(self):
        """A custom shell_whitelist_json in the profile overrides the
        default whitelist — allows python3 if listed."""
        profile = _make_profile(
            shell_mode="whitelist",
            shell_whitelist_json=json.dumps(["ls", "python3"]),
        )
        event = _tool_use_event("Bash", {"command": "python3 script.py"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True

    def test_custom_whitelist_blocks_unlisted(self):
        """Custom whitelist blocks commands not in the list."""
        profile = _make_profile(
            shell_mode="whitelist",
            shell_whitelist_json=json.dumps(["ls"]),
        )
        event = _tool_use_event("Bash", {"command": "cat file.txt"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False

    def test_db_whitelist_change_takes_effect(self):
        """Changing shell_whitelist_json in a DB-backed profile changes
        behavior without restart — verifies the value is read live."""
        db_fd, db_path, conn = _make_db()
        now = cs._now_iso()
        proj_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
            "VALUES (?, 'test', 'Test', 'proyecto', ?, ?)",
            (proj_id, now, now),
        )
        conn.execute(
            "INSERT INTO project_capability_profiles "
            "(id, project_id, name, repo_mode, shell_mode, "
            " shell_whitelist_json, web_mode, network_mode, "
            " filesystem_scope_json, secrets_scope_json, "
            " resource_budget_json, created_at, updated_at) "
            "VALUES (?, ?, 'custom', 'read-write', 'whitelist', "
            " ?, 'off', 'off', '{}', '{}', '{}', ?, ?)",
            (str(uuid.uuid4()), proj_id,
             json.dumps(["ls"]), now, now),
        )
        conn.commit()

        # With ["ls"], cat is blocked
        profile = cs.get_effective_profile(proj_id, conn)
        event = _tool_use_event("Bash", {"command": "cat file"})
        r1 = cs.evaluate_runtime_event(event, profile)
        assert r1["allowed"] is False

        # Update whitelist to include cat
        conn.execute(
            "UPDATE project_capability_profiles "
            "SET shell_whitelist_json = ? WHERE project_id = ?",
            (json.dumps(["ls", "cat"]), proj_id),
        )
        conn.commit()

        # Re-fetch profile — cat now allowed
        profile2 = cs.get_effective_profile(proj_id, conn)
        r2 = cs.evaluate_runtime_event(event, profile2)
        assert r2["allowed"] is True

        conn.close()
        os.close(db_fd)
        os.unlink(db_path)


# ═══════════════════════════════════════════════════════════════════
# 3. web_mode — WebFetch/WebSearch tool_use
# ═══════════════════════════════════════════════════════════════════

class TestWebMode:

    def test_off_blocks_webfetch(self):
        profile = _make_profile(web_mode="off")
        event = _tool_use_event("WebFetch", {"url": "https://example.com"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "web_mode_denied"
                   for t in result["triggers"])

    def test_off_blocks_websearch(self):
        profile = _make_profile(web_mode="off")
        event = _tool_use_event("WebSearch", {"query": "test"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False

    def test_on_allows_webfetch(self):
        profile = _make_profile(web_mode="on", network_mode="on")
        event = _tool_use_event("WebFetch", {"url": "https://example.com"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True


# ═══════════════════════════════════════════════════════════════════
# 4. network_mode — Bash network commands + WebFetch/WebSearch
# ═══════════════════════════════════════════════════════════════════

class TestNetworkMode:

    @pytest.mark.parametrize("cmd", [
        "curl https://example.com",
        "wget https://example.com",
        "ssh user@host",
    ])
    def test_off_blocks_network_commands_in_bash(self, cmd):
        profile = _make_profile(
            shell_mode="free", network_mode="off",
        )
        event = _tool_use_event("Bash", {"command": cmd})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "network_mode_denied"
                   for t in result["triggers"])

    def test_on_allows_network_commands(self):
        profile = _make_profile(
            shell_mode="free", network_mode="on",
        )
        event = _tool_use_event("Bash", {"command": "curl https://x.com"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True

    def test_off_blocks_webfetch_network(self):
        profile = _make_profile(web_mode="on", network_mode="off")
        event = _tool_use_event("WebFetch", {"url": "https://example.com"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "network_mode_denied"
                   for t in result["triggers"])


# ═══════════════════════════════════════════════════════════════════
# 5. filesystem_scope_json — Write/Edit paths
# ═══════════════════════════════════════════════════════════════════

class TestFilesystemScope:

    def test_write_inside_workspace_allowed(self):
        profile = _make_profile(
            filesystem_scope_json=json.dumps({
                "allow": ["<workspace>"], "deny": [],
            }),
        )
        event = _tool_use_event("Write", {
            "file_path": "/workspace/project/file.py",
        })
        result = cs.evaluate_runtime_event(
            event, profile, workspace_path="/workspace/project",
        )
        assert result["allowed"] is True

    def test_write_outside_workspace_denied(self):
        profile = _make_profile(
            filesystem_scope_json=json.dumps({
                "allow": ["<workspace>"], "deny": [],
            }),
        )
        event = _tool_use_event("Write", {
            "file_path": "/etc/passwd",
        })
        result = cs.evaluate_runtime_event(
            event, profile, workspace_path="/workspace/project",
        )
        assert result["allowed"] is False
        assert any(t["type"] == "filesystem_write_outside_scope"
                   for t in result["triggers"])

    def test_deny_list_takes_precedence(self):
        profile = _make_profile(
            filesystem_scope_json=json.dumps({
                "allow": ["<workspace>"],
                "deny": ["/workspace/project/secrets"],
            }),
        )
        event = _tool_use_event("Write", {
            "file_path": "/workspace/project/secrets/key.pem",
        })
        result = cs.evaluate_runtime_event(
            event, profile, workspace_path="/workspace/project",
        )
        assert result["allowed"] is False
        assert any(t["type"] == "filesystem_write_denied"
                   for t in result["triggers"])

    def test_explicit_allow_path(self):
        profile = _make_profile(
            filesystem_scope_json=json.dumps({
                "allow": ["/opt/output"], "deny": [],
            }),
        )
        event = _tool_use_event("Write", {
            "file_path": "/opt/output/result.txt",
        })
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True

    def test_no_scope_allows_all(self):
        profile = _make_profile(filesystem_scope_json="{}")
        event = _tool_use_event("Write", {
            "file_path": "/anywhere/file.txt",
        })
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True

    def test_workspace_without_path_fails_closed(self):
        """allow: ['<workspace>'] + workspace_path=None → deny (fail-closed)."""
        profile = _make_profile(
            filesystem_scope_json=json.dumps({
                "allow": ["<workspace>"], "deny": [],
            }),
        )
        event = _tool_use_event("Write", {
            "file_path": "/some/file.py",
        })
        result = cs.evaluate_runtime_event(
            event, profile, workspace_path=None,
        )
        assert result["allowed"] is False
        assert any(t["type"] == "filesystem_scope_unresolvable"
                   for t in result["triggers"])


# ═══════════════════════════════════════════════════════════════════
# 6. secrets_scope_json — no-op, verify non-breaking
# ═══════════════════════════════════════════════════════════════════

class TestSecretsScope:

    def test_secrets_scope_does_not_affect_write(self):
        """secrets_scope_json is no-op in PR-05 — verify it doesn't
        accidentally block writes."""
        profile = _make_profile(
            secrets_scope_json=json.dumps({"allow": []}),
        )
        event = _tool_use_event("Write", {
            "file_path": "/workspace/file.py",
        })
        result = cs.evaluate_runtime_event(
            event, profile, workspace_path="/workspace",
        )
        assert result["allowed"] is True

    def test_secrets_scope_does_not_affect_bash(self):
        profile = _make_profile(
            shell_mode="free",
            secrets_scope_json=json.dumps({"allow": []}),
        )
        event = _tool_use_event("Bash", {"command": "ls"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True


# ═══════════════════════════════════════════════════════════════════
# 7. resource_budget_json — pre-execution check
# ═══════════════════════════════════════════════════════════════════

class TestResourceBudget:

    def test_cost_within_budget_allowed(self):
        profile = _make_profile(
            resource_budget_json=json.dumps({"max_cost_usd": 5.0}),
        )
        task = {"estimated_resource_cost": "3.0", "quota_risk": None}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is True

    def test_cost_over_budget_denied(self):
        profile = _make_profile(
            resource_budget_json=json.dumps({"max_cost_usd": 5.0}),
        )
        task = {"estimated_resource_cost": "10.0", "quota_risk": None}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is False
        assert result["approval_required"] is True
        assert any(t["type"] == "estimated_resource_cost"
                   for t in result["triggers"])

    def test_null_cost_passes(self):
        """No-op when estimated_resource_cost is None (PR-06 not yet)."""
        profile = _make_profile(
            resource_budget_json=json.dumps({"max_cost_usd": 5.0}),
        )
        task = {"estimated_resource_cost": None, "quota_risk": None}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is True

    def test_quota_risk_medium_denied(self):
        profile = _make_profile()
        task = {"quota_risk": "medium", "estimated_resource_cost": None}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "quota_risk" for t in result["triggers"])

    def test_quota_risk_low_allowed(self):
        profile = _make_profile()
        task = {"quota_risk": "low", "estimated_resource_cost": None}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is True

    @pytest.mark.parametrize("risk", ["medium", "high", "critical"])
    def test_quota_risk_levels_denied(self, risk):
        profile = _make_profile()
        task = {"quota_risk": risk, "estimated_resource_cost": None}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is False


# ═══════════════════════════════════════════════════════════════════
# 8. Non-tool_use events pass through
# ═══════════════════════════════════════════════════════════════════

class TestNonToolEvents:

    def test_assistant_message_always_allowed(self):
        profile = _make_profile(shell_mode="disabled")
        event = {"type": "assistant", "message": "Hello"}
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True

    def test_system_event_always_allowed(self):
        profile = _make_profile(shell_mode="disabled")
        event = {"type": "system", "subtype": "init"}
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True

    def test_none_event_allowed(self):
        result = cs.evaluate_runtime_event(None, _make_profile())
        assert result["allowed"] is True


# ═══════════════════════════════════════════════════════════════════
# 9. _extract_commands helper
# ═══════════════════════════════════════════════════════════════════

class TestExtractCommands:

    def test_simple_command(self):
        assert cs._extract_commands("ls -la") == ["ls"]

    def test_chained_commands(self):
        cmds = cs._extract_commands("ls && grep foo && cat bar")
        assert cmds == ["ls", "grep", "cat"]

    def test_piped_commands(self):
        cmds = cs._extract_commands("cat file | grep pattern")
        assert cmds == ["cat", "grep"]

    def test_semicolon_separated(self):
        cmds = cs._extract_commands("echo hello; rm -rf /tmp")
        assert cmds == ["echo", "rm"]

    def test_path_prefix_stripped(self):
        cmds = cs._extract_commands("/usr/bin/rm -rf /tmp")
        assert cmds == ["rm"]

    def test_empty_string(self):
        assert cs._extract_commands("") == []

    def test_or_operator(self):
        cmds = cs._extract_commands("test -f x || rm x")
        assert cmds == ["test", "rm"]


# ═══════════════════════════════════════════════════════════════════
# 10. get_effective_profile + seed
# ═══════════════════════════════════════════════════════════════════

class TestProfileRetrieval:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.now = cs._now_iso()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_returns_default_when_no_project(self):
        profile = cs.get_effective_profile(None, self.conn)
        assert profile["name"] == "standard"
        assert profile["shell_mode"] == "whitelist"

    def test_returns_default_when_project_has_no_profile(self):
        proj_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
            "VALUES (?, 'test', 'Test', 'proyecto', ?, ?)",
            (proj_id, self.now, self.now),
        )
        self.conn.commit()
        profile = cs.get_effective_profile(proj_id, self.conn)
        assert profile["name"] == "standard"

    def test_returns_db_profile_when_exists(self):
        proj_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
            "VALUES (?, 'test', 'Test', 'proyecto', ?, ?)",
            (proj_id, self.now, self.now),
        )
        self.conn.execute(
            "INSERT INTO project_capability_profiles "
            "(id, project_id, name, repo_mode, shell_mode, web_mode, "
            " network_mode, filesystem_scope_json, secrets_scope_json, "
            " resource_budget_json, created_at, updated_at) "
            "VALUES (?, ?, 'custom', 'read-only', 'free', 'on', 'on', "
            " '{}', '{}', '{}', ?, ?)",
            (str(uuid.uuid4()), proj_id, self.now, self.now),
        )
        self.conn.commit()
        profile = cs.get_effective_profile(proj_id, self.conn)
        assert profile["name"] == "custom"
        assert profile["shell_mode"] == "free"

    def test_seed_creates_profiles_for_projects(self):
        proj_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
            "VALUES (?, 'proj1', 'P1', 'proyecto', ?, ?)",
            (proj_id, self.now, self.now),
        )
        self.conn.commit()
        inserted = cs.seed_capability_profiles(self.conn)
        assert inserted == 1
        profile = cs.get_effective_profile(proj_id, self.conn)
        assert profile["name"] == "standard"
        assert profile["repo_mode"] == "read-write"
        assert profile["shell_mode"] == "whitelist"
        whitelist = json.loads(profile["shell_whitelist_json"])
        assert "ls" in whitelist
        assert "cat" in whitelist
        assert "pwd" in whitelist
        assert "echo" in whitelist

    def test_seed_idempotent(self):
        proj_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
            "VALUES (?, 'proj2', 'P2', 'proyecto', ?, ?)",
            (proj_id, self.now, self.now),
        )
        self.conn.commit()
        cs.seed_capability_profiles(self.conn)
        count2 = cs.seed_capability_profiles(self.conn)
        assert count2 == 0  # No new insertions

    def test_seed_no_projects_is_noop(self):
        inserted = cs.seed_capability_profiles(self.conn)
        assert inserted == 0
