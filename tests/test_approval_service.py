"""Tests for PR-05 — approval_service.

Covers:
  - request_approval: creation with correct fields
  - list_approvals: filtering by status, task_id
  - get_approval: found and not-found
  - resolve_approval: approve, reject, idempotency, conflict
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

import approval_service


# ── Helpers ──────────────────────────────────────────────────────

def _make_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())
    return fd, path, conn


def _seed_task(conn):
    """Create a project + task + profile + routing_decision + run.

    Returns (task_id, run_id).
    """
    now = approval_service._now_iso()
    proj_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, 'proj', 'Project', 'proyecto', ?, ?)",
        (proj_id, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, created_at, updated_at) "
        "VALUES (?, 'Test task', 'proyecto', 'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, backend_kind, "
        "runtime_kind, enabled, priority, created_at, updated_at) "
        "VALUES (?, 'claude_code', 'Claude', 'claude_code', 'cli', 1, 10, ?, ?)",
        (profile_id, now, now),
    )
    conn.execute(
        "INSERT INTO routing_decisions (id, task_id, decision_index, "
        "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
        (rd_id, task_id, profile_id, now),
    )
    conn.execute(
        "INSERT INTO backend_runs (id, task_id, routing_decision_id, "
        "backend_profile_id, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'running', ?, ?)",
        (run_id, task_id, rd_id, profile_id, now, now),
    )
    conn.commit()
    return task_id, run_id


# ═══════════════════════════════════════════════════════════════════
# 1. request_approval
# ═══════════════════════════════════════════════════════════════════

class TestRequestApproval:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.run_id = _seed_task(self.conn)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_creates_pending_approval(self):
        approval = approval_service.request_approval(
            self.task_id, self.run_id,
            "shell_not_whitelisted",
            "Command 'python3' not in whitelist",
            "medium",
            self.conn,
        )
        assert approval["status"] == "pending"
        assert approval["task_id"] == self.task_id
        assert approval["backend_run_id"] == self.run_id
        assert approval["approval_type"] == "shell_not_whitelisted"
        assert approval["reason"] == "Command 'python3' not in whitelist"
        assert approval["risk_level"] == "medium"
        assert approval["requested_at"] is not None
        assert approval["resolved_at"] is None
        assert approval["resolved_by"] is None

    def test_creates_unique_id(self):
        a1 = approval_service.request_approval(
            self.task_id, self.run_id,
            "deletion", "rm detected", "high", self.conn,
        )
        a2 = approval_service.request_approval(
            self.task_id, self.run_id,
            "deletion", "rm detected", "high", self.conn,
        )
        assert a1["id"] != a2["id"]

    def test_persisted_in_db(self):
        approval = approval_service.request_approval(
            self.task_id, self.run_id,
            "network_mode_denied", "curl denied", "medium", self.conn,
        )
        row = self.conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval["id"],),
        ).fetchone()
        assert row is not None
        assert row["status"] == "pending"


# ═══════════════════════════════════════════════════════════════════
# 2. get_approval
# ═══════════════════════════════════════════════════════════════════

class TestGetApproval:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.run_id = _seed_task(self.conn)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_found(self):
        created = approval_service.request_approval(
            self.task_id, self.run_id,
            "test", "reason", "low", self.conn,
        )
        fetched = approval_service.get_approval(created["id"], self.conn)
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_not_found(self):
        result = approval_service.get_approval("nonexistent-id", self.conn)
        assert result is None


# ═══════════════════════════════════════════════════════════════════
# 3. list_approvals
# ═══════════════════════════════════════════════════════════════════

class TestListApprovals:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.run_id = _seed_task(self.conn)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_list_all(self):
        approval_service.request_approval(
            self.task_id, self.run_id, "a", "r", "low", self.conn,
        )
        approval_service.request_approval(
            self.task_id, self.run_id, "b", "r", "medium", self.conn,
        )
        results = approval_service.list_approvals(self.conn)
        assert len(results) == 2

    def test_filter_by_status(self):
        a = approval_service.request_approval(
            self.task_id, self.run_id, "a", "r", "low", self.conn,
        )
        approval_service.request_approval(
            self.task_id, self.run_id, "b", "r", "low", self.conn,
        )
        approval_service.resolve_approval(
            a["id"], "approved", "admin", self.conn,
        )

        pending = approval_service.list_approvals(
            self.conn, status="pending",
        )
        assert len(pending) == 1
        approved = approval_service.list_approvals(
            self.conn, status="approved",
        )
        assert len(approved) == 1

    def test_filter_by_task_id(self):
        # Create a second task
        now = approval_service._now_iso()
        task2 = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO tasks (id, title, area, status, priority, "
            "created_at, updated_at) VALUES (?, 'T2', 'proyecto', "
            "'en_progreso', 'media', ?, ?)",
            (task2, now, now),
        )
        self.conn.commit()

        approval_service.request_approval(
            self.task_id, self.run_id, "a", "r", "low", self.conn,
        )
        approval_service.request_approval(
            task2, self.run_id, "b", "r", "low", self.conn,
        )

        results = approval_service.list_approvals(
            self.conn, task_id=self.task_id,
        )
        assert len(results) == 1
        assert results[0]["task_id"] == self.task_id

    def test_empty_list(self):
        results = approval_service.list_approvals(self.conn)
        assert results == []


# ═══════════════════════════════════════════════════════════════════
# 4. resolve_approval
# ═══════════════════════════════════════════════════════════════════

class TestResolveApproval:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.run_id = _seed_task(self.conn)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_approve(self):
        a = approval_service.request_approval(
            self.task_id, self.run_id,
            "shell_not_whitelisted", "reason", "medium", self.conn,
        )
        resolved = approval_service.resolve_approval(
            a["id"], "approved", "admin", self.conn,
            resolution_note="Looks safe",
        )
        assert resolved["status"] == "approved"
        assert resolved["resolved_by"] == "admin"
        assert resolved["resolution_note"] == "Looks safe"
        assert resolved["resolved_at"] is not None

    def test_reject(self):
        a = approval_service.request_approval(
            self.task_id, self.run_id,
            "deletion", "rm detected", "high", self.conn,
        )
        resolved = approval_service.resolve_approval(
            a["id"], "rejected", "admin", self.conn,
            resolution_note="Too risky",
        )
        assert resolved["status"] == "rejected"
        assert resolved["resolved_by"] == "admin"

    def test_idempotent_same_status(self):
        """Resolving with the same status again is a no-op."""
        a = approval_service.request_approval(
            self.task_id, self.run_id,
            "test", "reason", "low", self.conn,
        )
        approval_service.resolve_approval(
            a["id"], "approved", "admin", self.conn,
        )
        # Second call with same status — no error
        result = approval_service.resolve_approval(
            a["id"], "approved", "admin2", self.conn,
        )
        assert result["status"] == "approved"
        # Original resolver is preserved
        assert result["resolved_by"] == "admin"

    def test_conflict_different_status(self):
        """Resolving with a different status raises ValueError."""
        a = approval_service.request_approval(
            self.task_id, self.run_id,
            "test", "reason", "low", self.conn,
        )
        approval_service.resolve_approval(
            a["id"], "approved", "admin", self.conn,
        )
        with pytest.raises(ValueError, match="already resolved"):
            approval_service.resolve_approval(
                a["id"], "rejected", "admin", self.conn,
            )

    def test_invalid_status(self):
        a = approval_service.request_approval(
            self.task_id, self.run_id,
            "test", "reason", "low", self.conn,
        )
        with pytest.raises(ValueError, match="Invalid approval status"):
            approval_service.resolve_approval(
                a["id"], "maybe", "admin", self.conn,
            )

    def test_not_found(self):
        with pytest.raises(LookupError, match="not found"):
            approval_service.resolve_approval(
                "nonexistent", "approved", "admin", self.conn,
            )

    def test_resolve_persists_in_db(self):
        a = approval_service.request_approval(
            self.task_id, self.run_id,
            "test", "reason", "low", self.conn,
        )
        approval_service.resolve_approval(
            a["id"], "rejected", "reviewer", self.conn,
            resolution_note="Not needed",
        )
        row = self.conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (a["id"],),
        ).fetchone()
        assert row["status"] == "rejected"
        assert row["resolved_by"] == "reviewer"
        assert row["resolution_note"] == "Not needed"
        assert row["resolved_at"] is not None
