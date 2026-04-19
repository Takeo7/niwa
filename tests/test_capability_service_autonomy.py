"""Tests for PR-B3 — autonomy_mode=dangerous bypass.

When a project has ``autonomy_mode='dangerous'``, the capability
service must return ``allowed=True`` for both pre-execution
(``evaluate``) and runtime (``evaluate_runtime_event``) checks so no
approvals are created and the task executes without interruption.
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


def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _make_profile(**overrides):
    profile = dict(cs.DEFAULT_CAPABILITY_PROFILE)
    profile.update(overrides)
    return profile


def _tool_use_event(tool_name, tool_input=None):
    return {
        "type": "tool_use",
        "name": tool_name,
        "input": tool_input or {},
    }


# ═══════════════════════════════════════════════════════════════════
# evaluate() — pre-execution bypass
# ═══════════════════════════════════════════════════════════════════

class TestEvaluateAutonomyBypass:

    def test_dangerous_bypasses_quota_risk_trigger(self):
        profile = _make_profile(autonomy_mode="dangerous")
        task = {"quota_risk": "critical"}
        run = {}
        result = cs.evaluate(task, run, {}, profile)
        assert result["allowed"] is True
        assert result["approval_required"] is False
        assert result["triggers"] == []
        assert "dangerous" in result["reason"]

    def test_dangerous_bypasses_resource_cost_trigger(self):
        profile = _make_profile(
            autonomy_mode="dangerous",
            resource_budget_json=json.dumps({"max_cost_usd": 1.0}),
        )
        task = {"estimated_resource_cost": "99.0"}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is True
        assert result["triggers"] == []

    def test_normal_still_triggers_quota_risk(self):
        profile = _make_profile(autonomy_mode="normal")
        task = {"quota_risk": "critical"}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "quota_risk" for t in result["triggers"])

    def test_missing_autonomy_mode_defaults_to_normal(self):
        profile = _make_profile()
        profile.pop("autonomy_mode", None)
        task = {"quota_risk": "high"}
        result = cs.evaluate(task, {}, {}, profile)
        assert result["allowed"] is False


# ═══════════════════════════════════════════════════════════════════
# evaluate_runtime_event() — runtime bypass
# ═══════════════════════════════════════════════════════════════════

class TestEvaluateRuntimeAutonomyBypass:

    def test_dangerous_bypasses_shell_whitelist(self):
        profile = _make_profile(autonomy_mode="dangerous")
        event = _tool_use_event("Bash", {"command": "rm -rf /tmp/nope"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True
        assert result["approval_required"] is False
        assert result["triggers"] == []

    def test_dangerous_bypasses_repo_mode(self):
        profile = _make_profile(
            autonomy_mode="dangerous", repo_mode="read-only",
        )
        event = _tool_use_event("Write", {"file_path": "/workspace/x.py"})
        result = cs.evaluate_runtime_event(
            event, profile, workspace_path="/workspace",
        )
        assert result["allowed"] is True

    def test_dangerous_bypasses_web_mode(self):
        profile = _make_profile(
            autonomy_mode="dangerous", web_mode="off",
        )
        event = _tool_use_event("WebFetch", {"url": "http://x"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is True

    def test_normal_still_blocks_rm(self):
        profile = _make_profile(autonomy_mode="normal")
        event = _tool_use_event("Bash", {"command": "rm -rf /tmp/x"})
        result = cs.evaluate_runtime_event(event, profile)
        assert result["allowed"] is False
        assert any(t["type"] == "deletion" for t in result["triggers"])


# ═══════════════════════════════════════════════════════════════════
# get_effective_profile() — merges autonomy_mode from projects
# ═══════════════════════════════════════════════════════════════════

class TestGetEffectiveProfileAutonomy:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.now = cs._now_iso()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _insert_project(self, autonomy_mode=None):
        proj_id = str(uuid.uuid4())
        if autonomy_mode is None:
            self.conn.execute(
                "INSERT INTO projects (id, slug, name, area, "
                "created_at, updated_at) VALUES (?, ?, 'P', "
                "'proyecto', ?, ?)",
                (proj_id, f"p-{proj_id[:6]}", self.now, self.now),
            )
        else:
            self.conn.execute(
                "INSERT INTO projects (id, slug, name, area, "
                "autonomy_mode, created_at, updated_at) VALUES "
                "(?, ?, 'P', 'proyecto', ?, ?, ?)",
                (proj_id, f"p-{proj_id[:6]}",
                 autonomy_mode, self.now, self.now),
            )
        self.conn.commit()
        return proj_id

    def test_none_project_id_returns_normal(self):
        profile = cs.get_effective_profile(None, self.conn)
        assert profile.get("autonomy_mode") == "normal"

    def test_project_without_explicit_flag_returns_normal(self):
        proj_id = self._insert_project()
        profile = cs.get_effective_profile(proj_id, self.conn)
        assert profile.get("autonomy_mode") == "normal"

    def test_project_with_dangerous_flag_propagates(self):
        proj_id = self._insert_project(autonomy_mode="dangerous")
        profile = cs.get_effective_profile(proj_id, self.conn)
        assert profile.get("autonomy_mode") == "dangerous"

    def test_dangerous_flag_survives_existing_capability_profile(self):
        proj_id = self._insert_project(autonomy_mode="dangerous")
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
        assert profile.get("autonomy_mode") == "dangerous"
