"""Tests for PR-04 — runs_service lifecycle.

Covers:
  - create_run() inserts a queued run
  - transition_run() enforces state machine
  - record_heartbeat() updates timestamp
  - record_event() inserts backend_run_events rows
  - finish_run() maps outcome → terminal status
  - register_artifact() inserts into artifacts table
  - update_session_handle() sets column without state transition
"""

import json
import os
import sqlite3
import sys
import tempfile
import uuid

import pytest

# ── Ensure backend dir is on sys.path ──
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import runs_service
import state_machines


# ── Helpers ──────────────────────────────────────────────────────

def _make_db():
    """Create a temporary SQLite DB with the full Niwa schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _seed_task_and_profile(conn):
    """Insert minimal task + project + backend_profile for FK satisfaction."""
    project_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    now = runs_service._now_iso()

    conn.execute(
        "INSERT INTO projects (id, slug, name, area, description, active, created_at, updated_at) "
        "VALUES (?, 'test-proj', 'Test', 'proyecto', '', 1, ?, ?)",
        (project_id, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, created_at, updated_at) "
        "VALUES (?, 'Test task', 'proyecto', 'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, runtime_kind, "
        "enabled, priority, created_at, updated_at) "
        "VALUES (?, 'test_claude', 'Test Claude', 'claude_code', 'cli', 1, 10, ?, ?)",
        (profile_id, now, now),
    )
    conn.commit()
    return task_id, profile_id


def _seed_routing_decision(conn, task_id, profile_id):
    """Insert a minimal routing_decision for FK satisfaction."""
    rd_id = str(uuid.uuid4())
    now = runs_service._now_iso()
    conn.execute(
        "INSERT INTO routing_decisions (id, task_id, decision_index, "
        "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
        (rd_id, task_id, profile_id, now),
    )
    conn.commit()
    return rd_id


# ═══════════════════════════════════════════════════════════════════
# 1. create_run
# ═══════════════════════════════════════════════════════════════════

class TestCreateRun:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id = _seed_task_and_profile(self.conn)
        self.rd_id = _seed_routing_decision(self.conn, self.task_id, self.profile_id)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_creates_queued_run(self):
        """create_run inserts a row with status 'queued'."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
        )
        assert run["status"] == "queued"
        assert run["task_id"] == self.task_id
        assert run["backend_profile_id"] == self.profile_id
        assert run["routing_decision_id"] == self.rd_id
        assert run["backend_kind"] == "claude_code"
        assert run["session_handle"] is None

    def test_creates_with_artifact_root(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root="/tmp/test-artifacts/run-1",
        )
        assert run["artifact_root"] == "/tmp/test-artifacts/run-1"

    def test_creates_with_relation_type(self):
        # First run
        run1 = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        # Resume run
        run2 = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=run1["id"], relation_type="resume",
        )
        assert run2["previous_run_id"] == run1["id"]
        assert run2["relation_type"] == "resume"

    def test_run_persisted_in_db(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        row = self.conn.execute(
            "SELECT * FROM backend_runs WHERE id = ?", (run["id"],)
        ).fetchone()
        assert row is not None
        assert dict(row)["status"] == "queued"


# ═══════════════════════════════════════════════════════════════════
# 2. transition_run
# ═══════════════════════════════════════════════════════════════════

class TestTransitionRun:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id = _seed_task_and_profile(self.conn)
        self.rd_id = _seed_routing_decision(self.conn, self.task_id, self.profile_id)
        self.run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_queued_to_starting(self):
        updated = runs_service.transition_run(
            self.run["id"], "starting", self.conn,
        )
        assert updated["status"] == "starting"

    def test_starting_to_running(self):
        runs_service.transition_run(self.run["id"], "starting", self.conn)
        updated = runs_service.transition_run(
            self.run["id"], "running", self.conn,
            started_at=runs_service._now_iso(),
        )
        assert updated["status"] == "running"
        assert updated["started_at"] is not None

    def test_running_to_succeeded(self):
        runs_service.transition_run(self.run["id"], "starting", self.conn)
        runs_service.transition_run(self.run["id"], "running", self.conn)
        updated = runs_service.transition_run(
            self.run["id"], "succeeded", self.conn,
            outcome="success", exit_code=0,
        )
        assert updated["status"] == "succeeded"
        assert updated["outcome"] == "success"
        assert updated["exit_code"] == 0

    def test_invalid_transition_raises(self):
        with pytest.raises(state_machines.InvalidTransitionError):
            runs_service.transition_run(
                self.run["id"], "running", self.conn,
            )  # queued → running is invalid

    def test_sets_session_handle(self):
        runs_service.transition_run(self.run["id"], "starting", self.conn)
        updated = runs_service.transition_run(
            self.run["id"], "running", self.conn,
            session_handle="sess-abc-123",
        )
        assert updated["session_handle"] == "sess-abc-123"

    def test_sets_observed_usage_signals(self):
        runs_service.transition_run(self.run["id"], "starting", self.conn)
        runs_service.transition_run(self.run["id"], "running", self.conn)
        usage = json.dumps({"input_tokens": 100, "output_tokens": 50})
        updated = runs_service.transition_run(
            self.run["id"], "succeeded", self.conn,
            observed_usage_signals_json=usage,
        )
        assert json.loads(updated["observed_usage_signals_json"]) == {
            "input_tokens": 100, "output_tokens": 50,
        }

    def test_ignores_unknown_kwargs(self):
        """Unknown kwargs are silently ignored (not written)."""
        runs_service.transition_run(self.run["id"], "starting", self.conn)
        updated = runs_service.transition_run(
            self.run["id"], "running", self.conn,
            bogus_field="should be ignored",
        )
        assert updated["status"] == "running"


# ═══════════════════════════════════════════════════════════════════
# 3. record_heartbeat
# ═══════════════════════════════════════════════════════════════════

class TestRecordHeartbeat:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id = _seed_task_and_profile(self.conn)
        self.rd_id = _seed_routing_decision(self.conn, self.task_id, self.profile_id)
        self.run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_updates_heartbeat_at(self):
        assert self.run["heartbeat_at"] is None
        runs_service.record_heartbeat(self.run["id"], self.conn)
        row = self.conn.execute(
            "SELECT heartbeat_at FROM backend_runs WHERE id = ?",
            (self.run["id"],),
        ).fetchone()
        assert row["heartbeat_at"] is not None


# ═══════════════════════════════════════════════════════════════════
# 4. record_event
# ═══════════════════════════════════════════════════════════════════

class TestRecordEvent:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id = _seed_task_and_profile(self.conn)
        self.rd_id = _seed_routing_decision(self.conn, self.task_id, self.profile_id)
        self.run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_inserts_event(self):
        eid = runs_service.record_event(
            self.run["id"], "assistant_message", self.conn,
            message="Hello world",
        )
        row = self.conn.execute(
            "SELECT * FROM backend_run_events WHERE id = ?", (eid,)
        ).fetchone()
        assert row is not None
        assert row["event_type"] == "assistant_message"
        assert row["message"] == "Hello world"

    def test_inserts_event_with_payload(self):
        payload = json.dumps({"tool": "Read", "path": "/tmp/x"})
        eid = runs_service.record_event(
            self.run["id"], "tool_use", self.conn,
            message="Tool call: Read",
            payload_json=payload,
        )
        row = self.conn.execute(
            "SELECT payload_json FROM backend_run_events WHERE id = ?", (eid,)
        ).fetchone()
        assert json.loads(row["payload_json"]) == {"tool": "Read", "path": "/tmp/x"}

    def test_multiple_events_ordered(self):
        runs_service.record_event(self.run["id"], "system_init", self.conn)
        runs_service.record_event(self.run["id"], "assistant_message", self.conn)
        runs_service.record_event(self.run["id"], "tool_use", self.conn)

        rows = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ? ORDER BY created_at",
            (self.run["id"],),
        ).fetchall()
        types = [r["event_type"] for r in rows]
        assert types == ["system_init", "assistant_message", "tool_use"]


# ═══════════════════════════════════════════════════════════════════
# 5. finish_run
# ═══════════════════════════════════════════════════════════════════

class TestFinishRun:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id = _seed_task_and_profile(self.conn)
        self.rd_id = _seed_routing_decision(self.conn, self.task_id, self.profile_id)
        self.run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        # Advance to running
        runs_service.transition_run(self.run["id"], "starting", self.conn)
        runs_service.transition_run(self.run["id"], "running", self.conn)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_finish_success(self):
        result = runs_service.finish_run(
            self.run["id"], "success", self.conn, exit_code=0,
        )
        assert result["status"] == "succeeded"
        assert result["outcome"] == "success"
        assert result["finished_at"] is not None

    def test_finish_failure(self):
        result = runs_service.finish_run(
            self.run["id"], "failure", self.conn,
            exit_code=1, error_code="nonzero_exit",
        )
        assert result["status"] == "failed"
        assert result["exit_code"] == 1
        assert result["error_code"] == "nonzero_exit"

    def test_finish_cancelled(self):
        result = runs_service.finish_run(
            self.run["id"], "cancelled", self.conn, exit_code=-15,
        )
        assert result["status"] == "cancelled"

    def test_finish_timed_out(self):
        result = runs_service.finish_run(
            self.run["id"], "timed_out", self.conn,
        )
        assert result["status"] == "timed_out"

    def test_finish_with_usage_signals(self):
        usage = json.dumps({"input_tokens": 500, "cost_usd": 0.01})
        result = runs_service.finish_run(
            self.run["id"], "success", self.conn,
            exit_code=0, observed_usage_signals_json=usage,
        )
        parsed = json.loads(result["observed_usage_signals_json"])
        assert parsed["input_tokens"] == 500

    def test_unknown_outcome_raises(self):
        with pytest.raises(ValueError, match="Unknown outcome"):
            runs_service.finish_run(self.run["id"], "bogus", self.conn)


# ═══════════════════════════════════════════════════════════════════
# 6. register_artifact
# ═══════════════════════════════════════════════════════════════════

class TestRegisterArtifact:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id = _seed_task_and_profile(self.conn)
        self.rd_id = _seed_routing_decision(self.conn, self.task_id, self.profile_id)
        self.run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_registers_artifact(self):
        aid = runs_service.register_artifact(
            self.task_id, self.run["id"], "code", "main.py", self.conn,
            size_bytes=1234, sha256="abc123",
        )
        row = self.conn.execute(
            "SELECT * FROM artifacts WHERE id = ?", (aid,)
        ).fetchone()
        assert row is not None
        assert row["artifact_type"] == "code"
        assert row["path"] == "main.py"
        assert row["size_bytes"] == 1234
        assert row["sha256"] == "abc123"
        assert row["task_id"] == self.task_id
        assert row["backend_run_id"] == self.run["id"]


# ═══════════════════════════════════════════════════════════════════
# 7. update_session_handle
# ═══════════════════════════════════════════════════════════════════

class TestUpdateSessionHandle:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id = _seed_task_and_profile(self.conn)
        self.rd_id = _seed_routing_decision(self.conn, self.task_id, self.profile_id)
        self.run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_sets_session_handle(self):
        assert self.run["session_handle"] is None
        runs_service.update_session_handle(
            self.run["id"], "session-xyz-789", self.conn,
        )
        row = self.conn.execute(
            "SELECT session_handle FROM backend_runs WHERE id = ?",
            (self.run["id"],),
        ).fetchone()
        assert row["session_handle"] == "session-xyz-789"

    def test_overwrites_existing_handle(self):
        runs_service.update_session_handle(
            self.run["id"], "old-handle", self.conn,
        )
        runs_service.update_session_handle(
            self.run["id"], "new-handle", self.conn,
        )
        row = self.conn.execute(
            "SELECT session_handle FROM backend_runs WHERE id = ?",
            (self.run["id"],),
        ).fetchone()
        assert row["session_handle"] == "new-handle"


# ═══════════════════════════════════════════════════════════════════
# 8. Full lifecycle: create → start → run → finish
# ═══════════════════════════════════════════════════════════════════

class TestFullLifecycle:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id = _seed_task_and_profile(self.conn)
        self.rd_id = _seed_routing_decision(self.conn, self.task_id, self.profile_id)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_happy_path(self):
        """Full lifecycle: queued → starting → running → succeeded."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        assert run["status"] == "queued"

        run = runs_service.transition_run(run["id"], "starting", self.conn)
        assert run["status"] == "starting"

        run = runs_service.transition_run(
            run["id"], "running", self.conn,
            session_handle="sess-123",
        )
        assert run["status"] == "running"
        assert run["session_handle"] == "sess-123"

        runs_service.record_heartbeat(run["id"], self.conn)
        runs_service.record_event(
            run["id"], "assistant_message", self.conn,
            message="Working on it...",
        )

        usage = json.dumps({"input_tokens": 1000, "output_tokens": 200})
        run = runs_service.finish_run(
            run["id"], "success", self.conn,
            exit_code=0, observed_usage_signals_json=usage,
        )
        assert run["status"] == "succeeded"

        events = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchall()
        assert len(events) == 1
        assert events[0]["event_type"] == "assistant_message"

    def test_failure_path(self):
        """Full lifecycle: queued → starting → running → failed."""
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        runs_service.transition_run(run["id"], "starting", self.conn)
        runs_service.transition_run(run["id"], "running", self.conn)
        run = runs_service.finish_run(
            run["id"], "failure", self.conn,
            exit_code=1, error_code="cli_error",
        )
        assert run["status"] == "failed"
        assert run["error_code"] == "cli_error"
