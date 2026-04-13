"""Tests for PR-04 — ClaudeCodeAdapter.collect_artifacts().

Covers:
  - Scanning artifact_root for files
  - sha256 and size_bytes computed correctly
  - artifact_type classified from extension
  - Rows inserted into artifacts table
  - Empty directory returns empty list
  - Non-existent path returns empty list
  - Nested directory structure scanned recursively
"""

import hashlib
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

import runs_service
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
        "VALUES (?, 'p', 'P', 'proyecto', ?, ?)",
        (str(uuid.uuid4()), now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, created_at, updated_at) "
        "VALUES (?, 'Test', 'proyecto', 'en_progreso', 'media', ?, ?)",
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
# 1. Basic artifact collection
# ═══════════════════════════════════════════════════════════════════

class TestCollectArtifacts:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_db_factory(self.db_path))
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_run(self):
        return runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=self.tmpdir,
        )

    def _write_file(self, relpath, content="hello"):
        fpath = os.path.join(self.tmpdir, relpath)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as f:
            f.write(content)
        return fpath

    def test_empty_dir_returns_empty(self):
        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        assert artifacts == []

    def test_no_artifact_root_returns_empty(self):
        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
        )
        # run has no artifact_root set
        artifacts = self.adapter.collect_artifacts(run)
        assert artifacts == []

    def test_nonexistent_path_returns_empty(self):
        run = self._make_run()
        run = dict(run)
        run["artifact_root"] = "/nonexistent/path/xyz"
        artifacts = self.adapter.collect_artifacts(run)
        assert artifacts == []

    def test_single_file(self):
        self._write_file("main.py", "print('hello')")
        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        assert len(artifacts) == 1
        assert artifacts[0]["path"] == "main.py"
        assert artifacts[0]["artifact_type"] == "code"
        assert artifacts[0]["size_bytes"] == len("print('hello')")

    def test_sha256_correct(self):
        content = "print('hello world')"
        self._write_file("script.py", content)
        expected_sha = hashlib.sha256(content.encode()).hexdigest()

        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        assert artifacts[0]["sha256"] == expected_sha

    def test_nested_directory(self):
        self._write_file("src/lib/utils.py", "def foo(): pass")
        self._write_file("docs/README.md", "# Readme")
        self._write_file("config.json", '{"key": "val"}')

        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        paths = sorted(a["path"] for a in artifacts)
        assert paths == ["config.json", "docs/README.md", "src/lib/utils.py"]

    def test_artifact_types_classified(self):
        self._write_file("code.py", "x")
        self._write_file("doc.md", "x")
        self._write_file("data.json", "x")
        self._write_file("image.png", "x")
        self._write_file("misc.xyz", "x")
        self._write_file("log.log", "x")

        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        type_map = {a["path"]: a["artifact_type"] for a in artifacts}
        assert type_map["code.py"] == "code"
        assert type_map["doc.md"] == "document"
        assert type_map["data.json"] == "data"
        assert type_map["image.png"] == "image"
        assert type_map["misc.xyz"] == "file"
        assert type_map["log.log"] == "log"


# ═══════════════════════════════════════════════════════════════════
# 2. DB persistence
# ═══════════════════════════════════════════════════════════════════

class TestCollectArtifactsDB:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = ClaudeCodeAdapter(db_conn_factory=_db_factory(self.db_path))
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_artifacts_inserted_in_db(self):
        fpath = os.path.join(self.tmpdir, "output.py")
        with open(fpath, "w") as f:
            f.write("result = 42")

        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=self.tmpdir,
        )
        self.adapter.collect_artifacts(run)

        rows = self.conn.execute(
            "SELECT * FROM artifacts WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchall()
        assert len(rows) == 1
        row = dict(rows[0])
        assert row["artifact_type"] == "code"
        assert row["path"] == "output.py"
        assert row["size_bytes"] == len("result = 42")
        assert row["sha256"] is not None
        assert row["task_id"] == self.task_id

    def test_multiple_files_all_persisted(self):
        for name in ("a.py", "b.md", "c.json"):
            with open(os.path.join(self.tmpdir, name), "w") as f:
                f.write("content")

        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=self.tmpdir,
        )
        self.adapter.collect_artifacts(run)

        count = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM artifacts WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchone()["cnt"]
        assert count == 3

    def test_no_db_factory_skips_persistence(self):
        """Without db_conn_factory, artifacts are returned but not persisted."""
        adapter_no_db = ClaudeCodeAdapter()
        with open(os.path.join(self.tmpdir, "x.py"), "w") as f:
            f.write("y")

        run = runs_service.create_run(
            self.task_id, self.rd_id, self.profile_id, self.conn,
            artifact_root=self.tmpdir,
        )
        artifacts = adapter_no_db.collect_artifacts(run)
        assert len(artifacts) == 1

        # DB should have no artifacts (adapter had no factory)
        count = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM artifacts",
        ).fetchone()["cnt"]
        assert count == 0
