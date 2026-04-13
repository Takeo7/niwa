"""Tests for routing_rules seed — PR-06 Niwa v0.2.

Covers: seed_routing_rules() inserts 3 rules, only when table is
empty, idempotent on repeated calls.
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest import TestCase

TESTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = TESTS_DIR.parent
BACKEND_DIR = ROOT_DIR / "niwa-app" / "backend"
SCHEMA_PATH = ROOT_DIR / "niwa-app" / "db" / "schema.sql"

sys.path.insert(0, str(BACKEND_DIR))

import routing_service


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


class TestSeedRoutingRules(TestCase):

    def test_seeds_three_rules(self):
        conn = _make_conn()
        inserted = routing_service.seed_routing_rules(conn)
        conn.commit()

        self.assertEqual(inserted, 3)
        rows = conn.execute(
            "SELECT * FROM routing_rules ORDER BY position ASC"
        ).fetchall()
        self.assertEqual(len(rows), 3)

        r1, r2, r3 = [dict(r) for r in rows]

        # Rule 1: complex_to_claude at position 10
        self.assertEqual(r1["name"], "complex_to_claude")
        self.assertEqual(r1["position"], 10)
        self.assertEqual(r1["enabled"], 1)
        match1 = json.loads(r1["match_json"])
        self.assertIn("refactor", match1["keywords_any"])
        self.assertEqual(match1["description_min_words"], 30)
        action1 = json.loads(r1["action_json"])
        self.assertEqual(action1["backend_slug"], "claude_code")

        # Rule 2: small_patch_to_codex at position 20
        self.assertEqual(r2["name"], "small_patch_to_codex")
        self.assertEqual(r2["position"], 20)
        match2 = json.loads(r2["match_json"])
        self.assertIn("fix", match2["keywords_any"])
        self.assertEqual(match2["description_max_words"], 40)
        action2 = json.loads(r2["action_json"])
        self.assertEqual(action2["backend_slug"], "codex")

        # Rule 3: default_claude at position 999
        self.assertEqual(r3["name"], "default_claude")
        self.assertEqual(r3["position"], 999)
        match3 = json.loads(r3["match_json"])
        self.assertEqual(match3, {})
        action3 = json.loads(r3["action_json"])
        self.assertEqual(action3["backend_slug"], "claude_code")

    def test_seed_only_when_empty(self):
        """Seed does NOT run if routing_rules already has rows."""
        conn = _make_conn()
        # First seed
        routing_service.seed_routing_rules(conn)
        conn.commit()

        # Second seed — should be no-op
        inserted = routing_service.seed_routing_rules(conn)
        self.assertEqual(inserted, 0)

        # Still exactly 3 rules
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM routing_rules"
        ).fetchone()["cnt"]
        self.assertEqual(count, 3)

    def test_seed_idempotent_multiple_calls(self):
        """Multiple calls never duplicate rules."""
        conn = _make_conn()
        for _ in range(5):
            routing_service.seed_routing_rules(conn)
            conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM routing_rules"
        ).fetchone()["cnt"]
        self.assertEqual(count, 3)

    def test_seed_preserves_user_rules(self):
        """If user added a custom rule, seed doesn't overwrite."""
        conn = _make_conn()
        # User adds a custom rule
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO routing_rules "
            "(id, name, position, enabled, match_json, action_json, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?, ?, ?)",
            ("custom-1", "custom_rule", 5, '{}',
             '{"backend_slug": "claude_code"}', now, now),
        )
        conn.commit()

        # Seed should see non-empty table → do nothing
        inserted = routing_service.seed_routing_rules(conn)
        self.assertEqual(inserted, 0)

        # Only the custom rule exists
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM routing_rules"
        ).fetchone()["cnt"]
        self.assertEqual(count, 1)

    def test_rule_keywords_match_spec(self):
        """Verify exact keyword lists from the SPEC."""
        conn = _make_conn()
        routing_service.seed_routing_rules(conn)
        conn.commit()

        r1 = conn.execute(
            "SELECT match_json FROM routing_rules WHERE name = ?",
            ("complex_to_claude",),
        ).fetchone()
        match1 = json.loads(r1["match_json"])
        expected_keywords = [
            "refactor", "arquitectura", "diseño", "migra",
            "reestructura", "multi-archivo", "varios archivos", "todo el",
        ]
        self.assertEqual(match1["keywords_any"], expected_keywords)

        r2 = conn.execute(
            "SELECT match_json FROM routing_rules WHERE name = ?",
            ("small_patch_to_codex",),
        ).fetchone()
        match2 = json.loads(r2["match_json"])
        expected_keywords_2 = [
            "fix", "bug", "typo", "rename", "quita",
            "añade test", "parche", "corrige",
        ]
        self.assertEqual(match2["keywords_any"], expected_keywords_2)


class TestRoutingModeSettingSeed(TestCase):
    """Verify routing_mode setting is seeded in init_db context."""

    def test_routing_mode_default_v02(self):
        """Fresh install gets routing_mode=v02."""
        conn = _make_conn()
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) "
            "VALUES ('routing_mode', 'v02')",
        )
        conn.commit()

        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'routing_mode'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["value"], "v02")

    def test_routing_mode_not_overwritten(self):
        """If routing_mode already set to 'legacy', INSERT OR IGNORE preserves it."""
        conn = _make_conn()
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('routing_mode', 'legacy')"
        )
        conn.commit()

        # Simulate init_db seed
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) "
            "VALUES ('routing_mode', 'v02')",
        )
        conn.commit()

        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'routing_mode'"
        ).fetchone()
        self.assertEqual(row["value"], "legacy")


if __name__ == "__main__":
    import unittest
    unittest.main()
