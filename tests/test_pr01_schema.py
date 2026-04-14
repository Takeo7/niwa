#!/usr/bin/env python3
"""Tests for PR-01: v0.2 execution core schema and migration 007.

Covers:
  - Migration applies on a clean DB without errors.
  - Migration is idempotent (applying twice works).
  - All SPEC tables exist after applying.
  - All new columns on tasks exist after applying.
  - SPEC-required indices exist after applying.
  - Deprecated columns (assigned_to_claude, assigned_to_yume) still exist.
  - CHECK constraints for enums (relation_type, backend_kind, runtime_kind).

Run with: pytest tests/test_pr01_schema.py -v
"""
import os
import re
import sqlite3
import sys
import tempfile
import glob

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')
MIGRATIONS_DIR = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'migrations')
MIGRATION_007 = os.path.join(MIGRATIONS_DIR, '007_v02_execution_core.sql')

# Tables introduced by migration 007 (SPEC PR-01)
V02_TABLES = {
    'backend_profiles',
    'routing_rules',
    'routing_decisions',
    'backend_runs',
    'backend_run_events',
    'approvals',
    'artifacts',
    'project_capability_profiles',
    'secret_bindings',
}

# New columns added to tasks by migration 007
V02_TASKS_COLUMNS = {
    'requested_backend_profile_id',
    'selected_backend_profile_id',
    'current_run_id',
    'approval_required',
    'quota_risk',
    'estimated_resource_cost',
}

# Deprecated columns that must still exist in tasks
DEPRECATED_TASKS_COLUMNS = {
    'assigned_to_claude',
    'assigned_to_yume',
}

# SPEC-required indices (name -> table)
V02_INDICES = {
    'idx_tasks_status_source_updated',
    'idx_backend_runs_task_status',
    'idx_approvals_status_requested',
}


def _apply_pre_migration_schema(conn):
    """Apply the original schema (pre-v0.2) by running schema.sql and stripping
    v0.2 columns from the tasks CREATE TABLE before execution.

    This simulates an existing v0.1 database that migration 007 would upgrade.
    """
    schema_sql = open(SCHEMA_PATH).read()

    # Apply all migrations before 007 to simulate existing DB state.
    # schema.sql already has v0.2 columns/tables (authoritative final state),
    # so we need a version WITHOUT them for migration testing.
    #
    # Strategy: run schema.sql then DROP the v0.2-only tables and recreate tasks
    # without the v0.2 columns.  This is easier than parsing SQL.
    conn.execute('PRAGMA foreign_keys=OFF')
    conn.executescript(schema_sql)

    # Drop v0.2 tables that schema.sql now creates
    for t in V02_TABLES:
        conn.execute(f'DROP TABLE IF EXISTS {t}')

    # Drop v0.2 indices
    for idx in V02_INDICES:
        conn.execute(f'DROP INDEX IF EXISTS {idx}')

    # Recreate tasks WITHOUT v0.2 columns
    # Get existing data columns (minus v0.2 additions)
    original_cols = [
        'id', 'title', 'description', 'area', 'project_id', 'status',
        'priority', 'urgent', 'scheduled_for', 'due_at', 'completed_at',
        'source', 'notes', 'created_at', 'updated_at',
        'assigned_to_yume', 'assigned_to_claude', 'attachments',
    ]
    col_list = ', '.join(original_cols)

    conn.execute(f'CREATE TABLE _tasks_backup AS SELECT {col_list} FROM tasks')
    conn.execute('DROP TABLE tasks')
    conn.execute(f'''CREATE TABLE tasks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT,
        area TEXT NOT NULL CHECK (area IN ('personal','empresa','proyecto','sistema')) DEFAULT 'proyecto',
        project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
        status TEXT NOT NULL CHECK (status IN ('inbox','pendiente','en_progreso','bloqueada','revision','waiting_input','hecha','archivada')) DEFAULT 'inbox',
        priority TEXT NOT NULL CHECK (priority IN ('baja','media','alta','critica','low','medium','high','critical')) DEFAULT 'media',
        urgent INTEGER NOT NULL DEFAULT 0,
        scheduled_for TEXT,
        due_at TEXT,
        completed_at TEXT,
        source TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        assigned_to_yume INTEGER NOT NULL DEFAULT 0,
        assigned_to_claude INTEGER NOT NULL DEFAULT 0,
        attachments TEXT
    )''')
    conn.execute(f'INSERT INTO tasks ({col_list}) SELECT {col_list} FROM _tasks_backup')
    conn.execute('DROP TABLE _tasks_backup')

    conn.execute('PRAGMA foreign_keys=ON')
    conn.commit()


def _apply_migration_007(conn):
    """Apply migration 007 via executescript."""
    sql = open(MIGRATION_007).read()
    conn.executescript(sql)


def _apply_sql_idempotent(conn, sql):
    """Apply SQL idempotently, emulating ADD COLUMN IF NOT EXISTS.

    For ALTER TABLE ADD COLUMN, checks pragma table_info first and skips
    the statement when the column already exists. All other statements
    are executed directly.
    """
    lines = []
    for line in sql.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--') or not stripped:
            continue
        if ' --' in line:
            line = line[:line.index(' --')]
        lines.append(line)
    cleaned = '\n'.join(lines)

    for stmt in cleaned.split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = re.match(
            r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)',
            stmt, re.IGNORECASE,
        )
        if m:
            table, column = m.group(1), m.group(2)
            existing = {r[1] for r in conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()}
            if column in existing:
                continue
        conn.execute(stmt)
    conn.commit()


def _get_tables(conn):
    """Return set of table names in the database."""
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}


def _get_columns(conn, table):
    """Return set of column names for a table."""
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _get_indices(conn):
    """Return set of index names in the database."""
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}


class TestMigration007Clean:
    """Migration 007 applies on a clean pre-v0.2 database without errors."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute('PRAGMA foreign_keys=ON')

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_migration_applies_on_clean_db(self):
        """Migration 007 executes without errors on a pre-v0.2 database."""
        _apply_pre_migration_schema(self.conn)
        _apply_migration_007(self.conn)

    def test_all_v02_tables_exist(self):
        """All 9 SPEC tables exist after migration."""
        _apply_pre_migration_schema(self.conn)
        _apply_migration_007(self.conn)
        tables = _get_tables(self.conn)
        missing = V02_TABLES - tables
        assert not missing, f"Missing v0.2 tables: {missing}"

    def test_all_v02_task_columns_exist(self):
        """All 6 new columns on tasks exist after migration."""
        _apply_pre_migration_schema(self.conn)
        _apply_migration_007(self.conn)
        columns = _get_columns(self.conn, 'tasks')
        missing = V02_TASKS_COLUMNS - columns
        assert not missing, f"Missing v0.2 columns on tasks: {missing}"

    def test_deprecated_columns_still_exist(self):
        """Deprecated columns assigned_to_claude and assigned_to_yume still present."""
        _apply_pre_migration_schema(self.conn)
        _apply_migration_007(self.conn)
        columns = _get_columns(self.conn, 'tasks')
        missing = DEPRECATED_TASKS_COLUMNS - columns
        assert not missing, f"Deprecated columns removed prematurely: {missing}"

    def test_spec_indices_exist(self):
        """SPEC-required composite indices exist after migration."""
        _apply_pre_migration_schema(self.conn)
        _apply_migration_007(self.conn)
        indices = _get_indices(self.conn)
        missing = V02_INDICES - indices
        assert not missing, f"Missing SPEC indices: {missing}"


class TestMigration007Idempotent:
    """Migration 007 is idempotent: applying it twice does not fail."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute('PRAGMA foreign_keys=ON')

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_migration_idempotent(self):
        """Running migration 007 twice produces the same correct state."""
        _apply_pre_migration_schema(self.conn)
        _apply_migration_007(self.conn)

        # Second application — column-existence check skips ALTER TABLE,
        # CREATE TABLE/INDEX IF NOT EXISTS are no-ops.
        _apply_sql_idempotent(self.conn, open(MIGRATION_007).read())

        # Verify final state is correct
        tables = _get_tables(self.conn)
        missing_tables = V02_TABLES - tables
        assert not missing_tables, f"Tables missing after second apply: {missing_tables}"

        columns = _get_columns(self.conn, 'tasks')
        missing_cols = V02_TASKS_COLUMNS - columns
        assert not missing_cols, f"Columns missing after second apply: {missing_cols}"

    def test_schema_plus_migration_no_errors(self):
        """Full schema.sql + migration 007 works (fresh install path)."""
        self.conn.executescript(open(SCHEMA_PATH).read())
        # Migration on top of full schema: tables exist (IF NOT EXISTS = no-op),
        # ALTER TABLE columns already present — skipped by existence check.
        _apply_sql_idempotent(self.conn, open(MIGRATION_007).read())

        tables = _get_tables(self.conn)
        missing = V02_TABLES - tables
        assert not missing, f"Missing tables after schema+migration: {missing}"


class TestSchemaFreshInstall:
    """schema.sql alone creates a complete v0.2 database."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute('PRAGMA foreign_keys=ON')

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_schema_creates_v02_tables(self):
        """schema.sql includes all v0.2 tables for fresh installs."""
        self.conn.executescript(open(SCHEMA_PATH).read())
        tables = _get_tables(self.conn)
        missing = V02_TABLES - tables
        assert not missing, f"schema.sql missing v0.2 tables: {missing}"

    def test_schema_creates_v02_task_columns(self):
        """schema.sql includes v0.2 columns in tasks for fresh installs."""
        self.conn.executescript(open(SCHEMA_PATH).read())
        columns = _get_columns(self.conn, 'tasks')
        missing = V02_TASKS_COLUMNS - columns
        assert not missing, f"schema.sql missing v0.2 task columns: {missing}"

    def test_schema_creates_v02_indices(self):
        """schema.sql includes v0.2 indices for fresh installs."""
        self.conn.executescript(open(SCHEMA_PATH).read())
        indices = _get_indices(self.conn)
        missing = V02_INDICES - indices
        assert not missing, f"schema.sql missing v0.2 indices: {missing}"


class TestCheckConstraints:
    """CHECK constraints from the SPEC are enforced."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(open(SCHEMA_PATH).read())

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_backend_kind_check(self):
        """backend_profiles.backend_kind rejects invalid values."""
        now = '2026-01-01T00:00:00Z'
        # Valid values
        for kind in ('claude_code', 'codex'):
            self.conn.execute(
                "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, runtime_kind, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'cli', ?, ?)",
                (f'bp-{kind}', f'slug-{kind}', f'Test {kind}', kind, now, now)
            )
        self.conn.commit()
        # Invalid value
        try:
            self.conn.execute(
                "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, runtime_kind, created_at, updated_at) "
                "VALUES ('bp-bad', 'slug-bad', 'Bad', 'gemini', 'cli', ?, ?)",
                (now, now)
            )
            self.conn.commit()
            assert False, "Should have rejected invalid backend_kind 'gemini'"
        except sqlite3.IntegrityError:
            pass

    def test_runtime_kind_check(self):
        """backend_profiles.runtime_kind rejects invalid values."""
        now = '2026-01-01T00:00:00Z'
        for kind in ('cli', 'api', 'acp', 'local'):
            self.conn.execute(
                "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, runtime_kind, created_at, updated_at) "
                "VALUES (?, ?, ?, 'codex', ?, ?, ?)",
                (f'bp-rt-{kind}', f'slug-rt-{kind}', f'Test {kind}', kind, now, now)
            )
        self.conn.commit()
        try:
            self.conn.execute(
                "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, runtime_kind, created_at, updated_at) "
                "VALUES ('bp-rt-bad', 'slug-rt-bad', 'Bad', 'codex', 'docker', ?, ?)",
                (now, now)
            )
            self.conn.commit()
            assert False, "Should have rejected invalid runtime_kind 'docker'"
        except sqlite3.IntegrityError:
            pass

    def test_relation_type_check(self):
        """backend_runs.relation_type only accepts fallback|resume|retry|NULL."""
        now = '2026-01-01T00:00:00Z'
        # Insert required parent rows
        self.conn.execute(
            "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
            "VALUES ('proj-1', 'test', 'Test', 'proyecto', ?, ?)", (now, now)
        )
        self.conn.execute(
            "INSERT INTO tasks (id, title, status, created_at, updated_at) "
            "VALUES ('task-1', 'Test task', 'inbox', ?, ?)", (now, now)
        )
        self.conn.commit()

        # Valid values (including NULL for original runs)
        for i, rt in enumerate([None, 'fallback', 'resume', 'retry']):
            self.conn.execute(
                "INSERT INTO backend_runs (id, task_id, relation_type, status, created_at, updated_at) "
                "VALUES (?, 'task-1', ?, 'queued', ?, ?)",
                (f'run-{i}', rt, now, now)
            )
        self.conn.commit()

        # Invalid value
        try:
            self.conn.execute(
                "INSERT INTO backend_runs (id, task_id, relation_type, status, created_at, updated_at) "
                "VALUES ('run-bad', 'task-1', 'restart', 'queued', ?, ?)",
                (now, now)
            )
            self.conn.commit()
            assert False, "Should have rejected invalid relation_type 'restart'"
        except sqlite3.IntegrityError:
            pass

    def test_relation_type_null_allowed(self):
        """relation_type allows NULL (for original/first runs)."""
        now = '2026-01-01T00:00:00Z'
        self.conn.execute(
            "INSERT INTO tasks (id, title, status, created_at, updated_at) "
            "VALUES ('task-null', 'Test', 'inbox', ?, ?)", (now, now)
        )
        self.conn.execute(
            "INSERT INTO backend_runs (id, task_id, relation_type, status, created_at, updated_at) "
            "VALUES ('run-null', 'task-null', NULL, 'queued', ?, ?)",
            (now, now)
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT relation_type FROM backend_runs WHERE id='run-null'"
        ).fetchone()
        assert row[0] is None


class TestMigrationFileConventions:
    """Migration 007 follows the repo conventions."""

    def test_migration_file_exists(self):
        """007_v02_execution_core.sql exists in migrations dir."""
        assert os.path.isfile(MIGRATION_007), f"Migration file not found: {MIGRATION_007}"

    def test_migration_starts_with_comment(self):
        """Migration file starts with a descriptive SQL comment."""
        content = open(MIGRATION_007).read()
        assert content.startswith('-- Migration 007:'), \
            "Migration should start with '-- Migration 007:' header"

    def test_migration_documents_deprecation(self):
        """Migration documents the deprecation of assigned_to_claude/assigned_to_yume."""
        content = open(MIGRATION_007).read()
        assert 'assigned_to_claude' in content, "Migration should mention assigned_to_claude deprecation"
        assert 'assigned_to_yume' in content, "Migration should mention assigned_to_yume deprecation"
        assert 'DEPRECATED' in content.upper() or 'deprecated' in content.lower(), \
            "Migration should use the word 'deprecated'"

    def test_schema_documents_deprecation(self):
        """schema.sql documents the deprecation with inline comments."""
        content = open(SCHEMA_PATH).read()
        assert 'DEPRECATED' in content, "schema.sql should mark deprecated columns"


class TestTableStructure:
    """Verify detailed structure of each new table matches SPEC."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript(open(SCHEMA_PATH).read())

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _columns_for(self, table):
        return _get_columns(self.conn, table)

    def test_backend_profiles_columns(self):
        expected = {
            'id', 'slug', 'display_name', 'backend_kind', 'runtime_kind',
            'default_model', 'command_template', 'capabilities_json',
            'enabled', 'priority', 'created_at', 'updated_at',
        }
        actual = self._columns_for('backend_profiles')
        assert expected == actual, f"backend_profiles mismatch: missing={expected-actual}, extra={actual-expected}"

    def test_routing_rules_columns(self):
        expected = {
            'id', 'name', 'position', 'enabled', 'match_json',
            'action_json', 'created_at', 'updated_at',
        }
        actual = self._columns_for('routing_rules')
        assert expected == actual, f"routing_rules mismatch: missing={expected-actual}, extra={actual-expected}"

    def test_routing_decisions_columns(self):
        # PR-09 añadió la columna ``contract_version`` vía migration 011
        # (ver niwa-app/db/migrations/011_contract_version.sql). El test
        # original de PR-01 no la incluía y quedó desalineado en cuanto
        # se aplicó la migración — Bug 12 en docs/BUGS-FOUND.md.
        expected = {
            'id', 'task_id', 'decision_index', 'requested_profile_id',
            'selected_profile_id', 'reason_summary', 'matched_rules_json',
            'fallback_chain_json', 'estimated_resource_cost', 'quota_risk',
            'contract_version', 'created_at',
        }
        actual = self._columns_for('routing_decisions')
        assert expected == actual, f"routing_decisions mismatch: missing={expected-actual}, extra={actual-expected}"

    def test_backend_runs_columns(self):
        expected = {
            'id', 'task_id', 'routing_decision_id', 'previous_run_id',
            'relation_type', 'backend_profile_id', 'backend_kind',
            'runtime_kind', 'model_resolved', 'session_handle', 'status',
            'capability_snapshot_json', 'budget_snapshot_json',
            'observed_usage_signals_json', 'heartbeat_at', 'started_at',
            'finished_at', 'outcome', 'exit_code', 'error_code',
            'artifact_root', 'created_at', 'updated_at',
        }
        actual = self._columns_for('backend_runs')
        assert expected == actual, f"backend_runs mismatch: missing={expected-actual}, extra={actual-expected}"

    def test_backend_run_events_columns(self):
        expected = {
            'id', 'backend_run_id', 'event_type', 'message',
            'payload_json', 'created_at',
        }
        actual = self._columns_for('backend_run_events')
        assert expected == actual, f"backend_run_events mismatch: missing={expected-actual}, extra={actual-expected}"

    def test_approvals_columns(self):
        expected = {
            'id', 'task_id', 'backend_run_id', 'approval_type', 'reason',
            'risk_level', 'status', 'requested_at', 'resolved_at',
            'resolved_by', 'resolution_note',
        }
        actual = self._columns_for('approvals')
        assert expected == actual, f"approvals mismatch: missing={expected-actual}, extra={actual-expected}"

    def test_artifacts_columns(self):
        expected = {
            'id', 'task_id', 'backend_run_id', 'artifact_type', 'path',
            'size_bytes', 'sha256', 'created_at',
        }
        actual = self._columns_for('artifacts')
        assert expected == actual, f"artifacts mismatch: missing={expected-actual}, extra={actual-expected}"

    def test_project_capability_profiles_columns(self):
        expected = {
            'id', 'project_id', 'name', 'repo_mode', 'shell_mode',
            'shell_whitelist_json', 'web_mode', 'network_mode',
            'filesystem_scope_json', 'secrets_scope_json',
            'resource_budget_json', 'created_at', 'updated_at',
        }
        actual = self._columns_for('project_capability_profiles')
        assert expected == actual, f"project_capability_profiles mismatch: missing={expected-actual}, extra={actual-expected}"

    def test_secret_bindings_columns(self):
        expected = {
            'id', 'project_id', 'backend_profile_id', 'secret_name',
            'provider', 'created_at', 'updated_at',
        }
        actual = self._columns_for('secret_bindings')
        assert expected == actual, f"secret_bindings mismatch: missing={expected-actual}, extra={actual-expected}"
