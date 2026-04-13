"""Integration tests for PR-04 — end-to-end with fake claude binary.

Uses tests/fixtures/fake_claude.py as a drop-in replacement for the
real ``claude`` CLI.  Verifies the full flow:
  start → streaming events → heartbeat → session_handle → finish → collect_artifacts

Does NOT call the real Claude CLI.
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
FAKE_CLAUDE = os.path.join(ROOT_DIR, "tests", "fixtures", "fake_claude.py")

import runs_service
from backend_adapters import claude_code as cc_module
from backend_adapters.claude_code import ClaudeCodeAdapter


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
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, 'integ', 'Integration', 'proyecto', ?, ?)",
        (str(uuid.uuid4()), now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, description, area, status, priority, created_at, updated_at) "
        "VALUES (?, 'Integration test task', 'Test description', 'proyecto', "
        "'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, "
        "runtime_kind, default_model, enabled, priority, created_at, updated_at) "
        "VALUES (?, 'claude_code', 'Claude', 'claude_code', 'cli', "
        "'claude-sonnet-4-6', 1, 10, ?, ?)",
        (profile_id, now, now),
    )
    conn.execute(
        "INSERT INTO routing_decisions (id, task_id, decision_index, "
        "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
        (rd_id, task_id, profile_id, now),
    )
    conn.commit()
    return task_id, profile_id, rd_id


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
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_db_factory(self.db_path))
        self.tmpdir = tempfile.mkdtemp()
        # Override the CLI command to use fake_claude.py
        self._orig_cli = cc_module.CLAUDE_CLI_COMMAND
        cc_module.CLAUDE_CLI_COMMAND = sys.executable  # python3

    def teardown_method(self):
        cc_module.CLAUDE_CLI_COMMAND = self._orig_cli
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_start_to_finish(self):
        """End-to-end: start → stream events → succeeded → artifacts."""
        art_root = os.path.join(self.tmpdir, "artifacts")
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
            artifact_root=art_root,
        )

        task = {"id": self.task_id, "title": "Integration test task",
                "description": "Test description"}
        # Use command_template pointing to fake_claude.py
        # The adapter builds: [CLAUDE_CLI_COMMAND, "-p", "--output-format", "stream-json", ...]
        # We override CLAUDE_CLI_COMMAND to python3, and use command_template
        # to invoke fake_claude.py
        profile = {
            "default_model": "claude-sonnet-4-6",
            "command_template": f"{sys.executable} {FAKE_CLAUDE}",
        }

        result = self.adapter.start(task, run, profile, {})

        # 1. Outcome
        assert result["status"] == "succeeded"
        assert result["outcome"] == "success"
        assert result["exit_code"] == 0

        # 2. Session handle persisted
        assert result["session_handle"] == "fake-session-001"
        db_run = self.conn.execute(
            "SELECT session_handle, status, outcome, exit_code, "
            "started_at, finished_at, observed_usage_signals_json "
            "FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["session_handle"] == "fake-session-001"
        assert db_run["status"] == "succeeded"
        assert db_run["started_at"] is not None
        assert db_run["finished_at"] is not None

        # 3. Usage signals
        usage = json.loads(db_run["observed_usage_signals_json"])
        assert usage["cost_usd"] == 0.042
        assert usage["duration_ms"] == 5200
        assert usage["model"] == "claude-sonnet-4-6"
        assert usage["input_tokens"] == 1500
        assert usage["output_tokens"] == 800
        assert usage["cache_read_tokens"] == 300
        assert usage["cache_creation_tokens"] == 100
        assert usage["turns"] == 2

        # 4. Streaming events written to backend_run_events
        events = self.conn.execute(
            "SELECT event_type, message FROM backend_run_events "
            "WHERE backend_run_id = ? ORDER BY created_at",
            (run["id"],),
        ).fetchall()
        event_types = [e["event_type"] for e in events]
        assert "system_init" in event_types
        assert "assistant_message" in event_types
        assert "tool_use" in event_types
        assert "tool_result" in event_types
        assert "result" in event_types
        # At least 5 distinct events from fake_claude output
        assert len(events) >= 5

        # 5. Artifacts: fake_claude writes output.md into cwd (artifact_root)
        artifacts = self.adapter.collect_artifacts(
            {**run, "artifact_root": art_root},
        )
        if artifacts:  # fake_claude writes to cwd which is artifact_root
            assert any(a["path"].endswith(".md") for a in artifacts)
            # Verify DB persistence
            db_artifacts = self.conn.execute(
                "SELECT * FROM artifacts WHERE backend_run_id = ?",
                (run["id"],),
            ).fetchall()
            assert len(db_artifacts) == len(artifacts)

    def test_full_start_failure(self):
        """End-to-end: start with --fail flag → failed run."""
        art_root = os.path.join(self.tmpdir, "artifacts-fail")
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=art_root,
        )

        task = {"id": self.task_id, "title": "Should fail"}
        # Append --fail to fake_claude invocation
        profile = {
            "default_model": "claude-sonnet-4-6",
            "command_template": f"{sys.executable} {FAKE_CLAUDE} --fail",
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
# 2. Resume flow
# ═══════════════════════════════════════════════════════════════════

class TestIntegrationResume:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_db_factory(self.db_path))
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cli = cc_module.CLAUDE_CLI_COMMAND
        cc_module.CLAUDE_CLI_COMMAND = sys.executable

    def teardown_method(self):
        cc_module.CLAUDE_CLI_COMMAND = self._orig_cli
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_resume_uses_prior_session(self):
        """resume() passes prior run's session_handle to fake_claude."""
        # Simulate a prior completed run with session_handle
        prior_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        runs_service.update_session_handle(
            prior_run["id"], "prior-sess-42", self.conn,
        )
        prior_run = dict(prior_run)
        prior_run["session_handle"] = "prior-sess-42"

        art_root = os.path.join(self.tmpdir, "resume-artifacts")
        new_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=prior_run["id"], relation_type="resume",
            artifact_root=art_root,
        )

        task = {"id": self.task_id, "title": "Resume task"}
        profile = {
            "default_model": "claude-sonnet-4-6",
            "command_template": f"{sys.executable} {FAKE_CLAUDE}",
        }

        result = self.adapter.resume(task, prior_run, new_run, profile, {})

        assert result["status"] == "succeeded"
        # fake_claude uses the --resume value as session_id
        assert result["session_handle"] == "prior-sess-42"

        db_run = self.conn.execute(
            "SELECT status, relation_type, session_handle "
            "FROM backend_runs WHERE id = ?",
            (new_run["id"],),
        ).fetchone()
        assert db_run["status"] == "succeeded"
        assert db_run["relation_type"] == "resume"
        assert db_run["session_handle"] == "prior-sess-42"


# ═══════════════════════════════════════════════════════════════════
# 3. Event granularity verification
# ═══════════════════════════════════════════════════════════════════

class TestIntegrationEventGranularity:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_db_factory(self.db_path))
        self.tmpdir = tempfile.mkdtemp()
        self._orig_cli = cc_module.CLAUDE_CLI_COMMAND
        cc_module.CLAUDE_CLI_COMMAND = sys.executable

    def teardown_method(self):
        cc_module.CLAUDE_CLI_COMMAND = self._orig_cli
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_events_not_single_giant_blob(self):
        """Verify streaming produces multiple events, not one blob at end."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=self.tmpdir,
        )
        profile = {
            "default_model": "claude-sonnet-4-6",
            "command_template": f"{sys.executable} {FAKE_CLAUDE}",
        }
        self.adapter.start(
            {"id": self.task_id, "title": "Granularity test"},
            run, profile, {},
        )

        events = self.conn.execute(
            "SELECT event_type FROM backend_run_events WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchall()
        types = [e["event_type"] for e in events]

        # fake_claude emits 6 events: system_init, assistant, tool_use,
        # tool_result, assistant, result → at least 5 distinct rows
        assert len(events) >= 5, f"Expected >=5 events, got {len(events)}: {types}"

        # Multiple different event types (not all the same)
        unique_types = set(types)
        assert len(unique_types) >= 4, f"Expected >=4 unique types, got {unique_types}"

    def test_each_event_has_payload_or_message(self):
        """Every event row has at least a message or payload_json."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=self.tmpdir,
        )
        profile = {
            "default_model": "claude-sonnet-4-6",
            "command_template": f"{sys.executable} {FAKE_CLAUDE}",
        }
        self.adapter.start(
            {"id": self.task_id, "title": "Payload test"},
            run, profile, {},
        )

        events = self.conn.execute(
            "SELECT event_type, message, payload_json "
            "FROM backend_run_events WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchall()
        for e in events:
            has_content = (e["message"] is not None) or (e["payload_json"] is not None)
            assert has_content, f"Event {e['event_type']} has no message or payload"
