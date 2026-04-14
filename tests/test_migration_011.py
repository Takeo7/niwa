"""Tests for migration 011 — contract_version column on routing_decisions.

Covers:
  - Migration adds the contract_version column.
  - Migration is idempotent (applying twice is a no-op the second time).
  - schema.sql fresh install has the contract_version column.

Run with: pytest tests/test_migration_011.py -v
"""
import os
import re
import sqlite3
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "niwa-app", "db", "schema.sql")
MIGRATION_011 = os.path.join(
    PROJECT_ROOT, "niwa-app", "db", "migrations", "011_contract_version.sql",
)


def _get_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _apply_sql_idempotent(conn, sql):
    """Apply SQL idempotently, skipping ALTER TABLE ADD COLUMN when
    the column already exists (same helper pattern as PR-01 tests)."""
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


# Pre-migration routing_decisions table (without contract_version)
_OLD_ROUTING_DECISIONS_DDL = """
CREATE TABLE IF NOT EXISTS routing_decisions (
    id                      TEXT PRIMARY KEY,
    task_id                 TEXT NOT NULL,
    decision_index          INTEGER NOT NULL,
    requested_profile_id    TEXT,
    selected_profile_id     TEXT,
    reason_summary          TEXT,
    matched_rules_json      TEXT,
    fallback_chain_json     TEXT,
    estimated_resource_cost TEXT,
    quota_risk              TEXT,
    created_at              TEXT NOT NULL
);
"""


class TestMigration011:

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.executescript(_OLD_ROUTING_DECISIONS_DDL)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_migration_adds_column(self):
        cols_before = _get_columns(self.conn, "routing_decisions")
        assert "contract_version" not in cols_before

        migration = open(MIGRATION_011).read()
        self.conn.executescript(migration)

        cols_after = _get_columns(self.conn, "routing_decisions")
        assert "contract_version" in cols_after

    def test_migration_idempotent(self):
        migration = open(MIGRATION_011).read()
        self.conn.executescript(migration)
        # Second pass uses idempotent helper to skip existing column
        _apply_sql_idempotent(self.conn, migration)

        cols = _get_columns(self.conn, "routing_decisions")
        assert "contract_version" in cols


class TestFreshInstallSchema:
    """Verify schema.sql has the contract_version column defined."""

    def test_schema_sql_contains_contract_version(self):
        """Check schema.sql text includes contract_version in routing_decisions."""
        schema = open(SCHEMA_PATH).read()
        # Find the routing_decisions CREATE TABLE block
        assert "contract_version" in schema
        # Verify it's in the routing_decisions table definition
        idx_table = schema.index("CREATE TABLE IF NOT EXISTS routing_decisions")
        idx_close = schema.index(");", idx_table)
        table_def = schema[idx_table:idx_close]
        assert "contract_version" in table_def
