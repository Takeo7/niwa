"""Integration tests for PR-07 — end-to-end with fake codex binary.

Uses tests/fixtures/fake_codex.py as a drop-in replacement for the
real ``codex`` CLI.  Verifies the full flow:
  start → streaming events → heartbeat → session_handle → finish → collect_artifacts

Also tests:
  - seed upgrade_codex_profile (existing installs)
  - Capability gate integration (pre-execution + runtime)

Does NOT call the real Codex CLI.
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
FAKE_CODEX = os.path.join(ROOT_DIR, "tests", "fixtures", "fake_codex.py")

import runs_service
from backend_adapters import codex as cx_module
from backend_adapters.codex import CodexAdapter


# ── Helpers ──────────────────────────────────────────────────────

def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _seed(conn):
    now = runs_service._now_iso()
    task_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, 'integ', 'Integration', 'proyecto', ?, ?)",
        (project_id, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, description, area, status, priority, "
        "created_at, updated_at) VALUES (?, 'Integration test', 'Test desc', "
        "'proyecto', 'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, "
        "runtime_kind, default_model, enabled, priority, created_at, updated_at) "
        "VALUES (?, 'codex', 'Codex', 'codex', 'cli', 'o4-mini', 1, 5, ?, ?)",
        (profile_id, now, now),
    )
    conn.execute(
        "INSERT INTO routing_decisions (id, task_id, decision_index, "
        "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
        (rd_id, task_id, profile_id, now),
    )
    conn.commit()
    return task_id, profile_id, rd_id, project_id


def _db_factory(db_path):
    def factory():
        c = sqlite3.connect(db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c
    return factory


# ═══════════════════════════════════════════════════════════════════
# 1. Full happy path: start → events → finish → artifacts
# ═══════════════════════════════════════════════════════════════════

class TestIntegrationHappyPath:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id, self.project_id = (
            _seed(self.conn))
        self.adapter = CodexAdapter(
            db_conn_factory=_db_factory(self.db_path))
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cli = cx_module.CODEX_CLI_COMMAND
        cx_module.CODEX_CLI_COMMAND = sys.executable

    def teardown_method(self):
        cx_module.CODEX_CLI_COMMAND = self._orig_cli
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_start_to_finish(self):
        art_root = os.path.join(self.tmpdir, "artifacts")
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="codex", runtime_kind="cli",
            artifact_root=art_root,
        )

        task = {"id": self.task_id, "title": "Integration test",
                "description": "Test desc"}
        profile = {
            "default_model": "o4-mini",
            "command_template": f"{sys.executable} {FAKE_CODEX}",
        }

        result = self.adapter.start(task, run, profile, {})

        # Outcome
        assert result["status"] == "succeeded"
        assert result["outcome"] == "success"
        assert result["exit_code"] == 0

        # Session handle
        assert result["session_handle"] == "codex-sess-001"
        db_run = self.conn.execute(
            "SELECT session_handle, status, outcome, exit_code, "
            "started_at, finished_at, observed_usage_signals_json "
            "FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["session_handle"] == "codex-sess-001"
        assert db_run["status"] == "succeeded"
        assert db_run["started_at"] is not None
        assert db_run["finished_at"] is not None

        # Usage signals
        usage = json.loads(db_run["observed_usage_signals_json"])
        assert usage["cost_usd"] == 0.015
        assert usage["duration_ms"] == 3000
        assert usage["model"] == "o4-mini"
        assert usage["input_tokens"] == 200
        assert usage["output_tokens"] == 300
        assert usage["total_tokens"] == 500
        assert usage["turns"] == 2

        # Streaming events
        events = self.conn.execute(
            "SELECT event_type, message FROM backend_run_events "
            "WHERE backend_run_id = ? ORDER BY created_at",
            (run["id"],),
        ).fetchall()
        types = [e["event_type"] for e in events]
        assert "system_init" in types
        assert "assistant_message" in types
        assert "tool_use" in types
        assert "tool_result" in types
        assert "result" in types
        assert len(events) >= 5

        # Artifacts
        artifacts = self.adapter.collect_artifacts(
            {**run, "artifact_root": art_root})
        if artifacts:
            assert any(a["path"].endswith(".diff") for a in artifacts)
            db_artifacts = self.conn.execute(
                "SELECT * FROM artifacts WHERE backend_run_id = ?",
                (run["id"],),
            ).fetchall()
            assert len(db_artifacts) == len(artifacts)

    def test_full_start_failure(self):
        art_root = os.path.join(self.tmpdir, "artifacts-fail")
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=art_root,
        )

        task = {"id": self.task_id, "title": "Should fail"}
        profile = {
            "default_model": "o4-mini",
            "command_template": f"{sys.executable} {FAKE_CODEX} --fail",
        }

        result = self.adapter.start(task, run, profile, {})

        assert result["status"] == "failed"
        assert result["outcome"] == "failure"
        assert result["exit_code"] == 1

        db_run = self.conn.execute(
            "SELECT status, exit_code FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["status"] == "failed"
        assert db_run["exit_code"] == 1


# ═══════════════════════════════════════════════════════════════════
# 2. Event granularity
# ═══════════════════════════════════════════════════════════════════

class TestIntegrationEventGranularity:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id, _ = _seed(self.conn)
        self.adapter = CodexAdapter(
            db_conn_factory=_db_factory(self.db_path))
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cli = cx_module.CODEX_CLI_COMMAND
        cx_module.CODEX_CLI_COMMAND = sys.executable

    def teardown_method(self):
        cx_module.CODEX_CLI_COMMAND = self._orig_cli
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_events_not_single_blob(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=self.tmpdir,
        )
        profile = {
            "default_model": "o4-mini",
            "command_template": f"{sys.executable} {FAKE_CODEX}",
        }
        self.adapter.start(
            {"id": self.task_id, "title": "Granularity test"},
            run, profile, {},
        )

        events = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ?", (run["id"],),
        ).fetchall()
        types = [e["event_type"] for e in events]

        assert len(events) >= 5
        assert len(set(types)) >= 4


# ═══════════════════════════════════════════════════════════════════
# 3. Seed upgrade
# ═══════════════════════════════════════════════════════════════════

class TestCodexProfileUpgrade:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_upgrade_from_old_defaults(self):
        """Existing install with enabled=0 priority=0 gets upgraded."""
        from backend_registry import upgrade_codex_profile
        now = runs_service._now_iso()
        self.conn.execute(
            "INSERT INTO backend_profiles "
            "(id, slug, display_name, backend_kind, runtime_kind, "
            "enabled, priority, created_at, updated_at) "
            "VALUES (?, 'codex', 'Codex', 'codex', 'cli', 0, 0, ?, ?)",
            (str(uuid.uuid4()), now, now),
        )
        self.conn.commit()

        updated = upgrade_codex_profile(self.conn)
        assert updated is True

        row = self.conn.execute(
            "SELECT enabled, priority FROM backend_profiles "
            "WHERE slug = 'codex'",
        ).fetchone()
        assert row["enabled"] == 1
        assert row["priority"] == 5

    def test_upgrade_respects_user_changes(self):
        """User-modified profile is NOT overwritten."""
        from backend_registry import upgrade_codex_profile
        now = runs_service._now_iso()
        self.conn.execute(
            "INSERT INTO backend_profiles "
            "(id, slug, display_name, backend_kind, runtime_kind, "
            "enabled, priority, created_at, updated_at) "
            "VALUES (?, 'codex', 'Codex', 'codex', 'cli', 0, 3, ?, ?)",
            (str(uuid.uuid4()), now, now),
        )
        self.conn.commit()

        updated = upgrade_codex_profile(self.conn)
        assert updated is False

        row = self.conn.execute(
            "SELECT enabled, priority FROM backend_profiles "
            "WHERE slug = 'codex'",
        ).fetchone()
        assert row["enabled"] == 0
        assert row["priority"] == 3

    def test_upgrade_already_enabled(self):
        """Already enabled profile is NOT touched."""
        from backend_registry import upgrade_codex_profile
        now = runs_service._now_iso()
        self.conn.execute(
            "INSERT INTO backend_profiles "
            "(id, slug, display_name, backend_kind, runtime_kind, "
            "enabled, priority, created_at, updated_at) "
            "VALUES (?, 'codex', 'Codex', 'codex', 'cli', 1, 5, ?, ?)",
            (str(uuid.uuid4()), now, now),
        )
        self.conn.commit()

        updated = upgrade_codex_profile(self.conn)
        assert updated is False

    def test_fresh_install_seed(self):
        """Fresh install gets codex with enabled=1 priority=5."""
        from backend_registry import seed_backend_profiles
        seed_backend_profiles(self.conn)
        self.conn.commit()

        row = self.conn.execute(
            "SELECT enabled, priority FROM backend_profiles "
            "WHERE slug = 'codex'",
        ).fetchone()
        assert row["enabled"] == 1
        assert row["priority"] == 5

    def test_capabilities_json_updated(self):
        """Upgrade also refreshes capabilities_json."""
        from backend_registry import upgrade_codex_profile
        now = runs_service._now_iso()
        old_caps = json.dumps({"resume_modes": ["new_session"]})
        self.conn.execute(
            "INSERT INTO backend_profiles "
            "(id, slug, display_name, backend_kind, runtime_kind, "
            "capabilities_json, enabled, priority, created_at, updated_at) "
            "VALUES (?, 'codex', 'Codex', 'codex', 'cli', ?, 0, 0, ?, ?)",
            (str(uuid.uuid4()), old_caps, now, now),
        )
        self.conn.commit()

        upgrade_codex_profile(self.conn)

        row = self.conn.execute(
            "SELECT capabilities_json FROM backend_profiles "
            "WHERE slug = 'codex'",
        ).fetchone()
        caps = json.loads(row["capabilities_json"])
        assert caps["resume_modes"] == []


# ═══════════════════════════════════════════════════════════════════
# 4. Capability gate integration
# ═══════════════════════════════════════════════════════════════════

class TestCodexCapabilityGate:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id, self.project_id = (
            _seed(self.conn))
        self.adapter = CodexAdapter(
            db_conn_factory=_db_factory(self.db_path))

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_pre_exec_denial_high_quota_risk(self):
        """High quota_risk triggers approval gate."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        task = {"id": self.task_id, "title": "Expensive",
                "quota_risk": "high"}
        profile = {"default_model": "o4-mini"}
        cap = {"resource_budget_json": json.dumps(
            {"max_cost_usd": 5.0})}

        result = self.adapter.start(task, run, profile, cap)

        assert result["status"] == "waiting_approval"

        db_run = self.conn.execute(
            "SELECT status FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["status"] == "waiting_approval"

        approvals = self.conn.execute(
            "SELECT * FROM approvals WHERE task_id = ?",
            (self.task_id,),
        ).fetchall()
        assert len(approvals) == 1
        assert approvals[0]["status"] == "pending"
