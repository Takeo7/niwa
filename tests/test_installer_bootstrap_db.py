"""Tests for the installer's fresh-DB bootstrap path (setup.py).

Regression guard for the "duplicate column name: requested_backend_profile_id"
bug seen on fresh ``./niwa install --quick --mode core --yes`` runs in v0.2.

Root cause: ``niwa-app/db/schema.sql`` already declares the v0.2 columns on
``tasks``, and migration 007 then tries to ``ALTER TABLE ADD COLUMN`` those
same columns. SQLite has no ``IF NOT EXISTS`` clause for ``ADD COLUMN``, so
``conn.executescript(migration_sql)`` blows up on a fresh install.

PR-17 fixed this in the *app-side* runner (``niwa-app/backend/app.py``), but
the installer's bootstrap block in ``setup.py`` had its own path that still
called ``conn.executescript`` directly. These tests exercise that bootstrap
path end-to-end against a temp DB so the bug cannot regress silently on any
future PR that touches migrations or the installer.
"""
from __future__ import annotations

import glob
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: E402 — module under test

SCHEMA_SQL = REPO_ROOT / "niwa-app" / "db" / "schema.sql"
MIGRATIONS_DIR = REPO_ROOT / "niwa-app" / "db" / "migrations"
V02_TASK_COLUMNS = {
    "requested_backend_profile_id",
    "selected_backend_profile_id",
    "current_run_id",
    "approval_required",
    "quota_risk",
    "estimated_resource_cost",
}


def _bootstrap_fresh_db(db_path: Path) -> sqlite3.Connection:
    """Replicate the installer's fresh-DB bootstrap exactly.

    Mirrors setup.py::execute_install's ``if cfg.db_mode == 'fresh':`` block:
    apply schema.sql, then run every migration in order through
    ``_apply_sql_idempotent``. Returns an open connection for assertions.
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL.read_text())
    for mfile in sorted(glob.glob(str(MIGRATIONS_DIR / "*.sql"))):
        setup._apply_sql_idempotent(conn, Path(mfile).read_text())
    conn.commit()
    return conn


class TestApplySqlIdempotent:
    """Unit tests for the helper itself."""

    def test_skips_alter_when_column_exists(self, tmp_path):
        conn = sqlite3.connect(":memory:")
        conn.executescript("CREATE TABLE t (id INTEGER, foo TEXT);")
        # Attempting to re-add `foo` should be a no-op, not an error.
        setup._apply_sql_idempotent(
            conn, "ALTER TABLE t ADD COLUMN foo TEXT;"
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(t)").fetchall()}
        assert cols == {"id", "foo"}

    def test_adds_column_when_missing(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("CREATE TABLE t (id INTEGER);")
        setup._apply_sql_idempotent(
            conn, "ALTER TABLE t ADD COLUMN bar TEXT;"
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(t)").fetchall()}
        assert cols == {"id", "bar"}

    def test_strips_line_and_trailing_comments(self):
        conn = sqlite3.connect(":memory:")
        sql = """
        -- top-of-file comment
        CREATE TABLE t (id INTEGER); -- inline trailing comment
        ALTER TABLE t ADD COLUMN baz TEXT; -- another one
        """
        setup._apply_sql_idempotent(conn, sql)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(t)").fetchall()}
        assert cols == {"id", "baz"}

    def test_runs_regular_ddl(self):
        conn = sqlite3.connect(":memory:")
        setup._apply_sql_idempotent(
            conn,
            "CREATE TABLE IF NOT EXISTS a (id INTEGER);"
            "CREATE INDEX IF NOT EXISTS idx_a ON a(id);",
        )
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "a" in tables

    def test_skips_explicit_transaction_control(self):
        """Regression for the "cannot start a transaction within a transaction"
        bug seen on ``./niwa install`` after PR-18.

        Migration 008 wraps its table swap in ``BEGIN TRANSACTION; ... COMMIT;``.
        Python's sqlite3 driver opens an implicit transaction on DML, so when
        the statements before it have already triggered that implicit BEGIN
        (e.g. the installer's ``INSERT OR IGNORE`` seeds), the explicit BEGIN
        inside the migration errors out. The helper must strip those
        transaction-control statements and let the outer connection manage
        the transaction.
        """
        conn = sqlite3.connect(":memory:")
        conn.executescript("CREATE TABLE t (id INTEGER);")
        # Trigger an implicit transaction like the installer does.
        conn.execute("INSERT INTO t (id) VALUES (1)")
        # This SQL is a miniature of migration 008: open BEGIN/COMMIT around
        # DDL after an implicit transaction has already started.
        sql = """
        BEGIN TRANSACTION;
        ALTER TABLE t ADD COLUMN foo TEXT;
        COMMIT;
        """
        # Must not raise "cannot start a transaction within a transaction".
        setup._apply_sql_idempotent(conn, sql)
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(t)").fetchall()}
        assert "foo" in cols

    def test_strips_begin_commit_case_insensitive_and_variants(self):
        """All documented variants of transaction-control statements are skipped."""
        conn = sqlite3.connect(":memory:")
        conn.executescript("CREATE TABLE t (id INTEGER);")
        conn.execute("INSERT INTO t (id) VALUES (1)")
        for variant in (
            "BEGIN",
            "begin",
            "BEGIN TRANSACTION",
            "BEGIN WORK",
            "COMMIT",
            "commit",
            "COMMIT TRANSACTION",
            "END",
            "END TRANSACTION",
            "ROLLBACK",
        ):
            # Should be treated as a no-op; never reaches sqlite as a BEGIN
            # inside the already-open implicit transaction.
            setup._apply_sql_idempotent(conn, variant + ";")


class TestInstallerBootstrap:
    """End-to-end: schema.sql + every migration, via the installer path."""

    def test_fresh_bootstrap_completes_without_error(self, tmp_path):
        """Regression: a clean install must not raise 'duplicate column name'.

        Before the fix, sorting the migrations and calling executescript on
        007 would raise because schema.sql already defines the v0.2 columns.
        """
        db = tmp_path / "niwa.sqlite3"
        conn = _bootstrap_fresh_db(db)
        try:
            # Sanity: the v0.2 columns exist exactly once on `tasks`.
            cols = {
                r[1] for r in conn.execute(
                    "PRAGMA table_info(tasks)"
                ).fetchall()
            }
            assert V02_TASK_COLUMNS.issubset(cols)
        finally:
            conn.close()

    def test_bootstrap_creates_all_v02_tables(self, tmp_path):
        """After bootstrap, the v0.2 execution-core tables from migration 007
        must be present."""
        db = tmp_path / "niwa.sqlite3"
        conn = _bootstrap_fresh_db(db)
        try:
            tables = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            # kanban_columns is intentionally dropped by migration 004; we
            # only care that the v0.2 execution-core tables from migration
            # 007 all landed.
            expected = {
                "backend_profiles", "routing_rules", "routing_decisions",
                "backend_runs", "backend_run_events", "approvals",
                "artifacts", "project_capability_profiles", "secret_bindings",
                "tasks", "projects",
            }
            missing = expected - tables
            assert not missing, f"missing v0.2 tables: {missing}"
        finally:
            conn.close()

    def test_bootstrap_is_reentrant(self, tmp_path):
        """Running the bootstrap twice on the same DB must not error.

        This catches any migration that is not idempotent under the helper.
        """
        db = tmp_path / "niwa.sqlite3"
        conn = _bootstrap_fresh_db(db)
        conn.close()
        # Second pass: apply every migration again. With _apply_sql_idempotent
        # the ALTER TABLE ADD COLUMNs must be skipped.
        conn = sqlite3.connect(str(db))
        try:
            for mfile in sorted(glob.glob(str(MIGRATIONS_DIR / "*.sql"))):
                setup._apply_sql_idempotent(conn, Path(mfile).read_text())
            conn.commit()
        finally:
            conn.close()

    def test_bootstrap_applies_migration_008_check_constraint(self, tmp_path):
        """Regression for "cannot start a transaction within a transaction".

        Migration 008 wraps its table swap in ``BEGIN TRANSACTION; … COMMIT;``.
        Before the fix the bootstrap raised here because the installer's
        earlier ``INSERT OR IGNORE`` seeds had already opened an implicit
        transaction. After the fix, the helper strips those inner
        transaction-control statements and 008's CHECK constraint on
        ``backend_runs.status`` lands correctly.
        """
        db = tmp_path / "niwa.sqlite3"
        conn = sqlite3.connect(str(db))
        conn.executescript(SCHEMA_SQL.read_text())
        # Reproduce the installer's implicit-BEGIN-trigger exactly.
        ts = "2025-01-01T00:00:00Z"
        conn.execute(
            "INSERT OR IGNORE INTO projects (id, slug, name, area, "
            "description, active, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("proj-default", "default", "Default", "proyecto",
             "x", 1, ts, ts),
        )
        try:
            for mfile in sorted(glob.glob(str(MIGRATIONS_DIR / "*.sql"))):
                setup._apply_sql_idempotent(conn, Path(mfile).read_text())
            conn.commit()
            # The CHECK constraint introduced by migration 008 must be
            # effective on the final backend_runs table.
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='backend_runs'"
            ).fetchone()[0]
            assert "CHECK" in ddl and "queued" in ddl, (
                f"migration 008 CHECK constraint missing: {ddl}"
            )
            # And the constraint actually rejects invalid status values.
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO backend_runs (id, task_id, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    ("r1", "t1", "bogus_status", ts, ts),
                )
        finally:
            conn.close()

    def test_pre_fix_helper_on_008_after_seed_fails(self, tmp_path):
        """Negative control: the *pre-fix* helper (no BEGIN/COMMIT skip)
        actually does fail on migration 008 after the implicit BEGIN has
        opened, with the exact production error message. This proves the
        fixture reproduces the bug and the fix is necessary.

        If this ever stops failing (e.g. migration 008 is rewritten without
        ``BEGIN TRANSACTION``) we want an explicit signal rather than silent
        drift.
        """
        import re as _re

        def _apply_sql_pre_fix(conn, sql):
            """Exact copy of _apply_sql_idempotent **before** the PR-19
            BEGIN/COMMIT skip was added. Used solely to reproduce the bug."""
            lines = []
            for line in sql.split("\n"):
                stripped = line.strip()
                if stripped.startswith("--") or not stripped:
                    continue
                if " --" in line:
                    line = line[: line.index(" --")]
                lines.append(line)
            cleaned = "\n".join(lines)
            for stmt in cleaned.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                m = _re.match(
                    r"ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)",
                    stmt, _re.IGNORECASE,
                )
                if m:
                    table, column = m.group(1), m.group(2)
                    existing = {r[1] for r in conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()}
                    if column in existing:
                        continue
                conn.execute(stmt)

        db = tmp_path / "niwa.sqlite3"
        conn = sqlite3.connect(str(db))
        try:
            conn.executescript(SCHEMA_SQL.read_text())
            ts = "2025-01-01T00:00:00Z"
            # Implicit-BEGIN trigger, exactly like the installer path.
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, slug, name, area, "
                "description, active, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("proj-default", "default", "Default", "proyecto",
                 "x", 1, ts, ts),
            )
            mig008 = MIGRATIONS_DIR / "008_state_machine_checks.sql"
            with pytest.raises(sqlite3.OperationalError) as exc:
                _apply_sql_pre_fix(conn, mig008.read_text())
            assert "cannot start a transaction within a transaction" in str(
                exc.value
            )
        finally:
            conn.close()

    def test_executescript_on_007_fails_proving_helper_is_needed(
        self, tmp_path
    ):
        """Negative control: the naive executescript path actually *does* fail
        here, so this test fixture is correctly reproducing the bug. If this
        ever stops failing (e.g. schema.sql loses the v0.2 columns, or 007 is
        rewritten), the production fix may no longer be necessary — but we
        want an explicit signal rather than silent drift.
        """
        db = tmp_path / "niwa.sqlite3"
        conn = sqlite3.connect(str(db))
        try:
            conn.executescript(SCHEMA_SQL.read_text())
            mig007 = MIGRATIONS_DIR / "007_v02_execution_core.sql"
            with pytest.raises(sqlite3.OperationalError) as exc:
                conn.executescript(mig007.read_text())
            assert "duplicate column name" in str(exc.value)
        finally:
            conn.close()
