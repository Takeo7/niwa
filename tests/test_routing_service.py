"""Tests for routing_service — PR-06 Niwa v0.2.

Covers: decide() API, evaluation order (pin > capability > resume >
rules > default), idempotency, persistence of routing_decisions,
Codex disabled fallthrough, and capability denied → approval flow.
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase

# ── Path setup ──────────────────────────────────────────────────────
TESTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TESTS_DIR.parent
BACKEND_DIR = ROOT_DIR / "niwa-app" / "backend"
SCHEMA_PATH = ROOT_DIR / "niwa-app" / "db" / "schema.sql"

sys.path.insert(0, str(BACKEND_DIR))

import routing_service
import capability_service
import approval_service


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_conn():
    """Create an in-memory SQLite DB with the full schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _seed_profiles(conn):
    """Insert the two default backend profiles."""
    now = _now_iso()
    # claude_code — enabled, priority=10
    conn.execute(
        "INSERT INTO backend_profiles "
        "(id, slug, display_name, backend_kind, runtime_kind, "
        " default_model, capabilities_json, enabled, priority, "
        " created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "prof-claude", "claude_code", "Claude Code",
            "claude_code", "cli", "claude-sonnet-4-6",
            json.dumps({
                "resume_modes": ["session_resume"],
                "fs_modes": ["read-write"],
                "shell_modes": ["whitelist", "free"],
                "network_modes": ["on", "off"],
                "approval_modes": ["always", "on_trigger"],
                "secrets_modes": ["env_inject"],
            }),
            1, 10, now, now,
        ),
    )
    # codex — disabled, priority=0
    conn.execute(
        "INSERT INTO backend_profiles "
        "(id, slug, display_name, backend_kind, runtime_kind, "
        " default_model, capabilities_json, enabled, priority, "
        " created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "prof-codex", "codex", "Codex",
            "codex", "cli", None,
            json.dumps({
                "resume_modes": ["new_session"],
                "fs_modes": ["repo_only", "readonly"],
                "shell_modes": ["sandboxed"],
                "network_modes": ["off"],
                "approval_modes": ["always", "never"],
                "secrets_modes": ["env_inject", "none"],
            }),
            0, 0, now, now,
        ),
    )
    conn.commit()


def _seed_rules(conn):
    """Seed the default routing rules."""
    routing_service.seed_routing_rules(conn)
    conn.commit()


def _make_project(conn, project_id="proj-1"):
    """Insert a minimal project."""
    now = _now_iso()
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, "test-proj", "Test Project", "proyecto", now, now),
    )
    conn.commit()
    return project_id


def _make_task(conn, task_id=None, title="Test task",
               description="A test task", project_id=None, **kwargs):
    """Insert a minimal task and return it as a dict."""
    if task_id is None:
        task_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO tasks "
        "(id, title, description, area, project_id, status, priority, "
        " urgent, created_at, updated_at, "
        " requested_backend_profile_id, selected_backend_profile_id, "
        " current_run_id, approval_required, quota_risk, "
        " estimated_resource_cost) "
        "VALUES (?, ?, ?, 'proyecto', ?, 'pendiente', 'media', 0, ?, ?, "
        "        ?, ?, ?, ?, ?, ?)",
        (
            task_id, title, description, project_id, now, now,
            kwargs.get("requested_backend_profile_id"),
            kwargs.get("selected_backend_profile_id"),
            kwargs.get("current_run_id"),
            kwargs.get("approval_required", 0),
            kwargs.get("quota_risk"),
            kwargs.get("estimated_resource_cost"),
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    return dict(row)


class TestDecidePinExplicit(TestCase):
    """Step 1: User pin always wins."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        _seed_rules(self.conn)

    def test_pin_to_enabled_backend(self):
        task = _make_task(
            self.conn, title="Fix bug",
            requested_backend_profile_id="prof-claude",
        )
        result = routing_service.decide(task, self.conn)

        self.assertEqual(result["selected_backend_profile_id"], "prof-claude")
        self.assertFalse(result["approval_required"])
        self.assertIsNone(result["approval_id"])
        self.assertEqual(result["matched_rules"][0]["rule"], "user_pin")
        self.assertIn("prof-claude", result["fallback_chain"])
        self.assertEqual(result["fallback_chain"][0], "prof-claude")
        self.assertIn("User pin", result["reason_summary"])

    def test_pin_to_disabled_backend_falls_through(self):
        """Pin to disabled backend → pin is ignored, falls to rules/default."""
        task = _make_task(
            self.conn, title="Fix bug",
            requested_backend_profile_id="prof-codex",
        )
        result = routing_service.decide(task, self.conn)

        # Codex is disabled, so pin fails. Falls to rules/default.
        # Default is claude_code (highest priority enabled).
        self.assertEqual(result["selected_backend_profile_id"], "prof-claude")
        # Should NOT have user_pin in matched rules
        pin_rules = [r for r in result["matched_rules"]
                     if r["rule"] == "user_pin"]
        self.assertEqual(len(pin_rules), 0)


class TestDecideCapabilityCheck(TestCase):
    """Step 2: Capability check blocks if denied."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        _seed_rules(self.conn)

    def test_capability_denied_creates_approval(self):
        """High quota_risk triggers capability denial and approval."""
        project_id = _make_project(self.conn)
        task = _make_task(
            self.conn,
            title="Big task",
            description="Something expensive",
            project_id=project_id,
            quota_risk="high",
        )

        result = routing_service.decide(task, self.conn)

        self.assertTrue(result["approval_required"])
        self.assertIsNotNone(result["approval_id"])
        self.assertIsNone(result["selected_backend_profile_id"])
        self.assertEqual(result["fallback_chain"], [])
        self.assertIn("Capability denied", result["reason_summary"])

        # Verify approval exists in DB
        approval = approval_service.get_approval(
            result["approval_id"], self.conn,
        )
        self.assertIsNotNone(approval)
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["task_id"], task["id"])

    def test_capability_allowed_proceeds(self):
        """No quota risk → passes capability check, selects backend."""
        project_id = _make_project(self.conn)
        task = _make_task(
            self.conn,
            title="Normal task",
            description="Do something small",
            project_id=project_id,
        )

        result = routing_service.decide(task, self.conn)

        self.assertFalse(result["approval_required"])
        self.assertIsNotNone(result["selected_backend_profile_id"])


class TestDecideResumeAware(TestCase):
    """Step 3: Resume-aware prioritizes prior run's backend."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        _seed_rules(self.conn)

    def test_resume_from_prior_run(self):
        """Task with terminal prior run → reuse backend if resume supported."""
        now = _now_iso()
        task = _make_task(self.conn, title="Resume task")

        # Create a prior run that succeeded (routing_decision_id=NULL is OK)
        run_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO backend_runs "
            "(id, task_id, routing_decision_id, backend_profile_id, "
            " backend_kind, runtime_kind, status, created_at, updated_at) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)",
            (run_id, task["id"], "prof-claude",
             "claude_code", "cli", "succeeded", now, now),
        )
        # Update task with current_run_id
        self.conn.execute(
            "UPDATE tasks SET current_run_id = ? WHERE id = ?",
            (run_id, task["id"]),
        )
        self.conn.commit()
        # Re-read task
        task = dict(self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task["id"],)
        ).fetchone())

        result = routing_service.decide(task, self.conn)

        self.assertEqual(
            result["selected_backend_profile_id"], "prof-claude",
        )
        resume_rules = [r for r in result["matched_rules"]
                        if r["rule"] == "resume_aware"]
        self.assertEqual(len(resume_rules), 1)
        self.assertIn("Resume-aware", result["reason_summary"])


class TestDecidePersistedRules(TestCase):
    """Step 4: Persisted routing rules, ordered by position."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        _seed_rules(self.conn)

    def test_complex_task_matches_rule_1(self):
        """Long refactor description → complex_to_claude (pos=10)."""
        desc = (
            "Refactor the entire authentication module to use the new "
            "framework. This requires changes across multiple files and "
            "updating the API layer, the service layer, and the database "
            "models. We also need to update the test suite."
        )
        task = _make_task(
            self.conn, title="Refactor auth module", description=desc,
        )

        result = routing_service.decide(task, self.conn)

        self.assertEqual(
            result["selected_backend_profile_id"], "prof-claude",
        )
        self.assertEqual(
            result["matched_rules"][0]["rule"], "routing_rule",
        )
        self.assertEqual(
            result["matched_rules"][0]["rule_name"], "complex_to_claude",
        )

    def test_codex_disabled_rule_skipped(self):
        """small_patch_to_codex matches but codex disabled → skip to next."""
        task = _make_task(
            self.conn,
            title="Fix typo in README",
            description="Fix a typo in the README file",
        )

        result = routing_service.decide(task, self.conn)

        # Codex is disabled, so rule 2 is skipped.
        # Falls to rule 3 (default_claude) which always matches.
        self.assertEqual(
            result["selected_backend_profile_id"], "prof-claude",
        )
        self.assertEqual(
            result["matched_rules"][0]["rule_name"], "default_claude",
        )

    def test_codex_enabled_rule_matches(self):
        """Enable codex → small_patch_to_codex matches."""
        self.conn.execute(
            "UPDATE backend_profiles SET enabled = 1, priority = 5 "
            "WHERE slug = 'codex'",
        )
        self.conn.commit()

        task = _make_task(
            self.conn,
            title="Fix typo in README",
            description="Fix a typo in the README file",
        )

        result = routing_service.decide(task, self.conn)

        self.assertEqual(
            result["selected_backend_profile_id"], "prof-codex",
        )
        self.assertEqual(
            result["matched_rules"][0]["rule_name"], "small_patch_to_codex",
        )

    def test_default_rule_catches_all(self):
        """Task matching no specific rule → default_claude (pos=999)."""
        task = _make_task(
            self.conn,
            title="Do something generic",
            description="This is a generic task with no keywords",
        )

        result = routing_service.decide(task, self.conn)

        self.assertEqual(
            result["selected_backend_profile_id"], "prof-claude",
        )
        self.assertEqual(
            result["matched_rules"][0]["rule_name"], "default_claude",
        )


class TestDecideDefault(TestCase):
    """Step 5: Default when no rules match at all."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        # No rules seeded

    def test_no_rules_uses_highest_priority(self):
        task = _make_task(self.conn, title="Anything")

        result = routing_service.decide(task, self.conn)

        self.assertEqual(
            result["selected_backend_profile_id"], "prof-claude",
        )
        self.assertEqual(result["matched_rules"][0]["rule"], "default")
        self.assertIn("Default", result["reason_summary"])


class TestDecideIdempotency(TestCase):
    """decide() twice on same task reuses existing decision."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        _seed_rules(self.conn)

    def test_idempotent_reuse(self):
        task = _make_task(self.conn, title="Test idempotency")

        result1 = routing_service.decide(task, self.conn)
        result2 = routing_service.decide(task, self.conn)

        self.assertEqual(
            result1["routing_decision_id"],
            result2["routing_decision_id"],
        )
        self.assertEqual(
            result1["selected_backend_profile_id"],
            result2["selected_backend_profile_id"],
        )


class TestDecisionPersistence(TestCase):
    """routing_decisions row is persisted with all fields."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        _seed_rules(self.conn)

    def test_decision_persisted(self):
        task = _make_task(self.conn, title="Persistence test")

        result = routing_service.decide(task, self.conn)

        row = self.conn.execute(
            "SELECT * FROM routing_decisions WHERE id = ?",
            (result["routing_decision_id"],),
        ).fetchone()
        self.assertIsNotNone(row)
        row = dict(row)
        self.assertEqual(row["task_id"], task["id"])
        self.assertEqual(row["decision_index"], 0)
        self.assertIsNotNone(row["selected_profile_id"])
        self.assertIsNotNone(row["reason_summary"])
        self.assertIsNotNone(row["matched_rules_json"])
        self.assertIsNotNone(row["fallback_chain_json"])
        self.assertIsNotNone(row["created_at"])

        # Verify JSON fields are parseable
        matched_rules = json.loads(row["matched_rules_json"])
        self.assertIsInstance(matched_rules, list)
        fallback_chain = json.loads(row["fallback_chain_json"])
        self.assertIsInstance(fallback_chain, list)


class TestPrecedenceOrder(TestCase):
    """Pin > capability > resume > rules > default."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        _seed_rules(self.conn)
        # Enable codex for this test
        self.conn.execute(
            "UPDATE backend_profiles SET enabled = 1, priority = 5 "
            "WHERE slug = 'codex'",
        )
        self.conn.commit()

    def test_pin_overrides_rules(self):
        """Even if rules would match claude, pin to codex wins."""
        desc = (
            "Refactor the entire module. This requires architecture "
            "changes across multiple files and restructuring the "
            "whole codebase to a new pattern that supports all needs."
        )
        task = _make_task(
            self.conn,
            title="Refactor everything",
            description=desc,
            requested_backend_profile_id="prof-codex",
        )

        result = routing_service.decide(task, self.conn)

        self.assertEqual(
            result["selected_backend_profile_id"], "prof-codex",
        )
        self.assertEqual(result["matched_rules"][0]["rule"], "user_pin")

    def test_capability_blocks_before_rules(self):
        """Capability check fires before rules are evaluated."""
        project_id = _make_project(self.conn)
        task = _make_task(
            self.conn,
            title="Fix a simple typo bug",
            description="Fix it",
            project_id=project_id,
            quota_risk="critical",
        )

        result = routing_service.decide(task, self.conn)

        self.assertTrue(result["approval_required"])
        self.assertIsNone(result["selected_backend_profile_id"])


class TestFallbackChain(TestCase):
    """Fallback chain: selected first, then other enabled by priority."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)

    def test_single_enabled_backend(self):
        """Only claude enabled → chain is just [claude]."""
        task = _make_task(self.conn, title="Test")
        result = routing_service.decide(task, self.conn)

        self.assertEqual(result["fallback_chain"], ["prof-claude"])

    def test_multiple_enabled_backends(self):
        """Both enabled → selected first, then others by priority DESC."""
        self.conn.execute(
            "UPDATE backend_profiles SET enabled = 1, priority = 5 "
            "WHERE slug = 'codex'",
        )
        self.conn.commit()

        task = _make_task(self.conn, title="Test")
        result = routing_service.decide(task, self.conn)

        self.assertEqual(len(result["fallback_chain"]), 2)
        self.assertEqual(result["fallback_chain"][0],
                         result["selected_backend_profile_id"])


class TestGetFallbackChain(TestCase):
    """get_fallback_chain() reads from persisted decision."""

    def setUp(self):
        self.conn = _make_conn()
        _seed_profiles(self.conn)
        _seed_rules(self.conn)

    def test_reads_from_db(self):
        task = _make_task(self.conn, title="Test")
        result = routing_service.decide(task, self.conn)

        chain = routing_service.get_fallback_chain(
            {"routing_decision_id": result["routing_decision_id"]},
            self.conn,
        )
        self.assertEqual(chain, result["fallback_chain"])

    def test_missing_decision_returns_empty(self):
        chain = routing_service.get_fallback_chain(
            {"routing_decision_id": "nonexistent"}, self.conn,
        )
        self.assertEqual(chain, [])


if __name__ == "__main__":
    import unittest
    unittest.main()
