"""Integration tests for PR-05 — approval gate in ClaudeCodeAdapter.

Uses fake_claude_violation.py to emit tool_use events that violate
the capability profile.  Verifies:
  1. Bash command outside whitelist → approval created, run waiting_approval,
     process killed.
  2. Write outside filesystem scope → same flow.
  3. Approval resolved as 'approved' → new backend_run with
     relation_type='resume', session_handle inherited.
  4. Compose security: docker-compose.yml.tmpl has no privileged/pid:host/
     network_mode:host in the main services.
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")
FAKE_CLAUDE = os.path.join(ROOT_DIR, "tests", "fixtures", "fake_claude.py")
FAKE_CLAUDE_VIOLATION = os.path.join(
    ROOT_DIR, "tests", "fixtures", "fake_claude_violation.py",
)

import approval_service
import capability_service as cs
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


def _seed(conn, *, project_dir=None):
    """Create project + task + profile + routing_decision.

    Returns (task_id, profile_id, rd_id, project_id).
    """
    now = runs_service._now_iso()
    proj_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO projects (id, slug, name, area, directory, "
        "created_at, updated_at) "
        "VALUES (?, 'proj', 'Project', 'proyecto', ?, ?, ?)",
        (proj_id, project_dir, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, "
        "project_id, created_at, updated_at) "
        "VALUES (?, 'Test task', 'proyecto', 'en_progreso', 'media', "
        "?, ?, ?)",
        (task_id, proj_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, "
        "backend_kind, runtime_kind, default_model, enabled, priority, "
        "created_at, updated_at) "
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
    return task_id, profile_id, rd_id, proj_id


def _db_factory(db_path):
    def factory():
        c = sqlite3.connect(db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c
    return factory


def _standard_profile():
    """Build the standard capability profile (whitelist shell, off network)."""
    return dict(cs.DEFAULT_CAPABILITY_PROFILE)


# ═══════════════════════════════════════════════════════════════════
# 1. Shell violation → approval gate triggered
# ═══════════════════════════════════════════════════════════════════

class TestShellViolation:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.tmpdir = tempfile.mkdtemp()
        self.task_id, self.profile_id, self.rd_id, self.proj_id = _seed(
            self.conn, project_dir=self.tmpdir,
        )
        self.adapter = ClaudeCodeAdapter(
            db_conn_factory=_db_factory(self.db_path),
        )
        self._orig_cli = cc_module.CLAUDE_CLI_COMMAND
        cc_module.CLAUDE_CLI_COMMAND = sys.executable

    def teardown_method(self):
        cc_module.CLAUDE_CLI_COMMAND = self._orig_cli
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bash_outside_whitelist_triggers_approval(self):
        """Fake claude emits `rm -rf /tmp/danger` → approval created,
        run → waiting_approval, process killed."""
        art_root = os.path.join(self.tmpdir, "artifacts")
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
            artifact_root=art_root,
        )

        task = {"id": self.task_id, "title": "Shell test"}
        profile = {
            "default_model": "claude-sonnet-4-6",
            "command_template": (
                f"{sys.executable} {FAKE_CLAUDE_VIOLATION} "
                f"--violation shell"
            ),
        }
        cap_profile = _standard_profile()

        result = self.adapter.start(task, run, profile, cap_profile)

        # 1. Result status is waiting_approval
        assert result["status"] == "waiting_approval"

        # 2. Run in DB is waiting_approval
        db_run = self.conn.execute(
            "SELECT status FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["status"] == "waiting_approval"

        # 3. Approval created in DB
        approvals = approval_service.list_approvals(
            self.conn, task_id=self.task_id,
        )
        assert len(approvals) >= 1
        approval = approvals[0]
        assert approval["status"] == "pending"
        assert approval["backend_run_id"] == run["id"]
        # Should mention shell or deletion
        assert approval["approval_type"] in (
            "shell_not_whitelisted", "deletion",
        )

        # 4. Events include the trigger
        events = self.conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchall()
        types = [e["event_type"] for e in events]
        assert "approval_gate_triggered" in types

        # 5. Process is dead (adapter killed it)
        with self.adapter._lock:
            assert run["id"] not in self.adapter._processes


# ═══════════════════════════════════════════════════════════════════
# 2. Write outside filesystem scope → approval gate triggered
# ═══════════════════════════════════════════════════════════════════

class TestWriteViolation:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.tmpdir = tempfile.mkdtemp()
        self.task_id, self.profile_id, self.rd_id, self.proj_id = _seed(
            self.conn, project_dir=self.tmpdir,
        )
        self.adapter = ClaudeCodeAdapter(
            db_conn_factory=_db_factory(self.db_path),
        )
        self._orig_cli = cc_module.CLAUDE_CLI_COMMAND
        cc_module.CLAUDE_CLI_COMMAND = sys.executable

    def teardown_method(self):
        cc_module.CLAUDE_CLI_COMMAND = self._orig_cli
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_outside_scope_triggers_approval(self):
        """Fake claude emits Write to /etc/passwd → approval created."""
        art_root = os.path.join(self.tmpdir, "artifacts")
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
            artifact_root=art_root,
        )

        task = {"id": self.task_id, "title": "Write test"}
        profile = {
            "default_model": "claude-sonnet-4-6",
            "command_template": (
                f"{sys.executable} {FAKE_CLAUDE_VIOLATION} "
                f"--violation write"
            ),
        }
        cap_profile = _standard_profile()

        result = self.adapter.start(task, run, profile, cap_profile)

        # 1. Result status is waiting_approval
        assert result["status"] == "waiting_approval"

        # 2. Run in DB is waiting_approval
        db_run = self.conn.execute(
            "SELECT status FROM backend_runs WHERE id = ?",
            (run["id"],),
        ).fetchone()
        assert db_run["status"] == "waiting_approval"

        # 3. Approval created with filesystem trigger
        approvals = approval_service.list_approvals(
            self.conn, task_id=self.task_id,
        )
        assert len(approvals) >= 1
        assert approvals[0]["approval_type"] == "filesystem_write_outside_scope"


# ═══════════════════════════════════════════════════════════════════
# 3. Approval resolved → resume with new run + inherited session
# ═══════════════════════════════════════════════════════════════════

class TestApprovalResumeFlow:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.tmpdir = tempfile.mkdtemp()
        self.task_id, self.profile_id, self.rd_id, self.proj_id = _seed(
            self.conn, project_dir=self.tmpdir,
        )
        self.adapter = ClaudeCodeAdapter(
            db_conn_factory=_db_factory(self.db_path),
        )
        self._orig_cli = cc_module.CLAUDE_CLI_COMMAND
        cc_module.CLAUDE_CLI_COMMAND = sys.executable

    def teardown_method(self):
        cc_module.CLAUDE_CLI_COMMAND = self._orig_cli
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_approved_approval_allows_resume(self):
        """After approval is approved, a new run with relation_type='resume'
        and the prior session_handle succeeds."""
        # Step 1: Start a run that triggers a violation
        art_root = os.path.join(self.tmpdir, "artifacts-v1")
        first_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            backend_kind="claude_code", runtime_kind="cli",
            artifact_root=art_root,
        )

        task = {"id": self.task_id, "title": "Resume test"}
        profile_violation = {
            "default_model": "claude-sonnet-4-6",
            "command_template": (
                f"{sys.executable} {FAKE_CLAUDE_VIOLATION} "
                f"--violation shell"
            ),
        }
        cap_profile = _standard_profile()

        result = self.adapter.start(
            task, first_run, profile_violation, cap_profile,
        )
        assert result["status"] == "waiting_approval"

        # Verify session_handle was captured before violation
        first_run_db = self.conn.execute(
            "SELECT session_handle FROM backend_runs WHERE id = ?",
            (first_run["id"],),
        ).fetchone()
        session_handle = first_run_db["session_handle"]
        assert session_handle == "violation-sess-001"

        # Step 2: Resolve the approval
        approvals = approval_service.list_approvals(
            self.conn, task_id=self.task_id,
        )
        assert len(approvals) >= 1
        approval_service.resolve_approval(
            approvals[0]["id"], "approved", "admin", self.conn,
            resolution_note="Verified safe",
        )

        # Step 3: Create a new run with relation_type='resume'
        art_root2 = os.path.join(self.tmpdir, "artifacts-v2")
        resume_run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            previous_run_id=first_run["id"],
            relation_type="resume",
            backend_kind="claude_code",
            runtime_kind="cli",
            artifact_root=art_root2,
        )

        # Step 4: Resume using the inherited session_handle
        # Use a permissive profile (shell_mode=free) so the resume
        # doesn't trigger the same violation
        permissive_profile = dict(cap_profile)
        permissive_profile["shell_mode"] = "free"

        # Use the normal fake_claude for the resume (no violation)
        profile_ok = {
            "default_model": "claude-sonnet-4-6",
            "command_template": f"{sys.executable} {FAKE_CLAUDE}",
        }

        prior_run_dict = dict(first_run)
        prior_run_dict["session_handle"] = session_handle

        result = self.adapter.resume(
            task, prior_run_dict, resume_run,
            profile_ok, permissive_profile,
        )

        # Step 5: Verify the resume succeeded
        assert result["status"] == "succeeded"
        assert result["session_handle"] == session_handle

        # Verify the new run in DB
        db_run = self.conn.execute(
            "SELECT status, relation_type, previous_run_id, session_handle "
            "FROM backend_runs WHERE id = ?",
            (resume_run["id"],),
        ).fetchone()
        assert db_run["status"] == "succeeded"
        assert db_run["relation_type"] == "resume"
        assert db_run["previous_run_id"] == first_run["id"]
        assert db_run["session_handle"] == session_handle


# ═══════════════════════════════════════════════════════════════════
# 4. Compose security — no privileged/pid:host/network_mode:host
# ═══════════════════════════════════════════════════════════════════

class TestComposeSecurity:

    def test_main_compose_no_privileged(self):
        """docker-compose.yml.tmpl must not contain 'privileged: true'
        outside of comments."""
        compose_path = os.path.join(
            ROOT_DIR, "docker-compose.yml.tmpl",
        )
        if not os.path.exists(compose_path):
            pytest.skip("docker-compose.yml.tmpl not found")

        with open(compose_path) as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "privileged: true" not in stripped, (
                f"Line {i}: privileged found in main compose"
            )

    def test_main_compose_no_pid_host(self):
        """docker-compose.yml.tmpl must not contain 'pid: host'
        outside of comments."""
        compose_path = os.path.join(
            ROOT_DIR, "docker-compose.yml.tmpl",
        )
        if not os.path.exists(compose_path):
            pytest.skip("docker-compose.yml.tmpl not found")

        with open(compose_path) as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "pid: host" not in stripped, (
                f"Line {i}: pid:host found in main compose"
            )

    def test_main_compose_no_network_mode_host(self):
        """docker-compose.yml.tmpl must not contain 'network_mode: host'
        outside of comments."""
        compose_path = os.path.join(
            ROOT_DIR, "docker-compose.yml.tmpl",
        )
        if not os.path.exists(compose_path):
            pytest.skip("docker-compose.yml.tmpl not found")

        with open(compose_path) as f:
            lines = f.readlines()

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "network_mode: host" not in stripped, (
                f"Line {i}: network_mode:host found in main compose"
            )

    def test_advanced_compose_exists(self):
        """docker-compose.advanced.yml must exist and contain the
        terminal service."""
        advanced_path = os.path.join(
            ROOT_DIR, "docker-compose.advanced.yml",
        )
        assert os.path.exists(advanced_path), (
            "docker-compose.advanced.yml not found"
        )
        with open(advanced_path) as f:
            content = f.read()
        assert "terminal" in content
        assert "privileged: true" in content
