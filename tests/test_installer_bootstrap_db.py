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
