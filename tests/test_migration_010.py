"""Tests for migration 010 — external_ref column on chat_sessions.

Covers:
  - Migration adds the external_ref column to chat_sessions.
  - Migration is idempotent (applying twice is a no-op the second time).
  - schema.sql fresh install has the external_ref column.

Run with: pytest tests/test_migration_010.py -v
"""
import os
import sqlite3
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "niwa-app", "db", "schema.sql")
MIGRATION_010 = os.path.join(
    PROJECT_ROOT, "niwa-app", "db", "migrations", "010_chat_external_ref.sql",
)


def _get_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _apply_sql_idempotent(conn, sql):
    """Apply SQL idempotently, skipping ALTER TABLE ADD COLUMN when
    the column already exists (same helper pattern as PR-01 tests)."""
    import re

    for raw_stmt in sql.split(";"):
        stmt = raw_stmt.strip()
        if not stmt or stmt.startswith("--"):
            continue

        m = re.match(
            r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
            stmt,
            re.IGNORECASE,
        )
        if m:
            table, col = m.group(1), m.group(2)
            existing = _get_columns(conn, table)
            if col in existing:
                continue  # already present — skip

        conn.execute(stmt)
    conn.commit()


# ── Tests ─────────────────────────────────────────────────────────────


class TestMigration010:
    """Migration 010 on an existing DB."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys=ON")

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_migration_adds_column(self):
        """Migration 010 adds external_ref to chat_sessions."""
        # Apply schema WITHOUT external_ref to simulate pre-010 state.
        # schema.sql already includes the column, so we strip it.
        schema = open(SCHEMA_PATH).read()
        # Remove the external_ref line from CREATE TABLE chat_sessions
        schema_pre = schema.replace(
            "    external_ref TEXT,  -- PR-08: external channel identifier "
            "(e.g. OpenClaw chat_id)\n",
            "",
        )
        self.conn.executescript(schema_pre)

        cols_before = _get_columns(self.conn, "chat_sessions")
        assert "external_ref" not in cols_before

        # Apply migration
        migration_sql = open(MIGRATION_010).read()
        self.conn.executescript(migration_sql)

        cols_after = _get_columns(self.conn, "chat_sessions")
        assert "external_ref" in cols_after

    def test_migration_idempotent(self):
        """Applying migration 010 twice is a no-op the second time."""
        schema = open(SCHEMA_PATH).read()
        schema_pre = schema.replace(
            "    external_ref TEXT,  -- PR-08: external channel identifier "
            "(e.g. OpenClaw chat_id)\n",
            "",
        )
        self.conn.executescript(schema_pre)

        migration_sql = open(MIGRATION_010).read()
        self.conn.executescript(migration_sql)

        # Second application via idempotent helper
        _apply_sql_idempotent(self.conn, migration_sql)

        cols = _get_columns(self.conn, "chat_sessions")
        assert "external_ref" in cols


class TestSchemaFreshInstall010:
    """schema.sql fresh install includes external_ref."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys=ON")

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_fresh_install_has_external_ref(self):
        """Fresh install via schema.sql has external_ref on chat_sessions."""
        self.conn.executescript(open(SCHEMA_PATH).read())
        cols = _get_columns(self.conn, "chat_sessions")
        assert "external_ref" in cols

    def test_fresh_install_external_ref_nullable(self):
        """external_ref accepts NULL (default for web sessions)."""
        self.conn.executescript(open(SCHEMA_PATH).read())
        now = "2026-04-14T00:00:00Z"
        self.conn.execute(
            "INSERT INTO chat_sessions (id, title, created_at, updated_at) "
            "VALUES ('s1', 'test', ?, ?)",
            (now, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT external_ref FROM chat_sessions WHERE id='s1'"
        ).fetchone()
        assert row[0] is None

    def test_fresh_install_external_ref_stores_value(self):
        """external_ref stores and retrieves an OpenClaw identifier."""
        self.conn.executescript(open(SCHEMA_PATH).read())
        now = "2026-04-14T00:00:00Z"
        self.conn.execute(
            "INSERT INTO chat_sessions "
            "(id, title, external_ref, created_at, updated_at) "
            "VALUES ('s2', 'openclaw', 'oc-chat-abc123', ?, ?)",
            (now, now),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT external_ref FROM chat_sessions WHERE id='s2'"
        ).fetchone()
        assert row[0] == "oc-chat-abc123"
