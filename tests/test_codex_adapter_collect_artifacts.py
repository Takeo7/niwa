"""Unit tests for CodexAdapter.collect_artifacts() — PR-07 Niwa v0.2.

Verifies artifact scanning, type classification, sha256 hashing,
and DB persistence.
"""

import hashlib
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
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, 'test', 'Test', 'proyecto', ?, ?)",
        (str(uuid.uuid4()), now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, description, area, status, priority, "
        "created_at, updated_at) VALUES (?, 'Test', 'desc', 'proyecto', "
        "'en_progreso', 'media', ?, ?)",
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
    return task_id, profile_id, rd_id


def _db_factory(db_path):
    def factory():
        c = sqlite3.connect(db_path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c
    return factory


# ═══════════════════════════════════════════════════════════════════

class TestCollectArtifacts:

    def setup_method(self):
        self.db_fd, self.db_path, self.conn = _make_db()
        self.task_id, self.profile_id, self.rd_id = _seed(self.conn)
        self.adapter = CodexAdapter(db_conn_factory=_db_factory(self.db_path))
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
            backend_kind="codex", runtime_kind="cli",
            artifact_root=self.tmpdir,
        )

    def _write_file(self, name, content="test content"):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return path

    # ── Basic functionality ───────────────────────────────────────

    def test_empty_directory(self):
        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        assert artifacts == []

    def test_missing_artifact_root(self):
        run = self._make_run()
        run = dict(run)
        run["artifact_root"] = "/nonexistent/path"
        artifacts = self.adapter.collect_artifacts(run)
        assert artifacts == []

    def test_no_artifact_root_key(self):
        run = {"id": "fake", "task_id": self.task_id}
        artifacts = self.adapter.collect_artifacts(run)
        assert artifacts == []

    def test_single_file(self):
        self._write_file("patch.diff", "--- a/x\n+++ b/x\n")
        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        assert len(artifacts) == 1
        assert artifacts[0]["path"] == "patch.diff"
        assert artifacts[0]["size_bytes"] > 0
        assert len(artifacts[0]["sha256"]) == 64

    def test_multiple_files(self):
        self._write_file("output.py", "print('hello')")
        self._write_file("readme.md", "# README")
        self._write_file("data.json", '{"key": "val"}')
        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        assert len(artifacts) == 3
        paths = {a["path"] for a in artifacts}
        assert paths == {"output.py", "readme.md", "data.json"}

    def test_nested_files(self):
        self._write_file("src/main.py", "main()")
        self._write_file("src/utils/helper.py", "help()")
        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        assert len(artifacts) == 2
        paths = {a["path"] for a in artifacts}
        assert "src/main.py" in paths
        assert "src/utils/helper.py" in paths

    # ── SHA256 correctness ────────────────────────────────────────

    def test_sha256_matches(self):
        content = "exact content for hash"
        self._write_file("test.txt", content)
        expected = hashlib.sha256(content.encode()).hexdigest()
        run = self._make_run()
        artifacts = self.adapter.collect_artifacts(run)
        assert artifacts[0]["sha256"] == expected

    # ── Type classification ───────────────────────────────────────

    def test_classify_code(self):
        assert CodexAdapter._classify_artifact_type(".py") == "code"
        assert CodexAdapter._classify_artifact_type(".js") == "code"
        assert CodexAdapter._classify_artifact_type(".rs") == "code"

    def test_classify_document(self):
        assert CodexAdapter._classify_artifact_type(".md") == "document"
        assert CodexAdapter._classify_artifact_type(".txt") == "document"

    def test_classify_data(self):
        assert CodexAdapter._classify_artifact_type(".json") == "data"
        assert CodexAdapter._classify_artifact_type(".yaml") == "data"

    def test_classify_patch(self):
        assert CodexAdapter._classify_artifact_type(".diff") == "patch"
        assert CodexAdapter._classify_artifact_type(".patch") == "patch"

    def test_classify_log(self):
        assert CodexAdapter._classify_artifact_type(".log") == "log"

    def test_classify_image(self):
        assert CodexAdapter._classify_artifact_type(".png") == "image"

    def test_classify_unknown(self):
        assert CodexAdapter._classify_artifact_type(".xyz") == "file"

    # ── DB persistence ────────────────────────────────────────────

    def test_artifacts_persisted_to_db(self):
        self._write_file("out.py", "code")
        self._write_file("notes.md", "notes")
        run = self._make_run()
        self.adapter.collect_artifacts(run)

        db_artifacts = self.conn.execute(
            "SELECT * FROM artifacts WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchall()
        assert len(db_artifacts) == 2

    def test_artifact_db_fields(self):
        content = "the content"
        self._write_file("single.py", content)
        run = self._make_run()
        self.adapter.collect_artifacts(run)

        row = self.conn.execute(
            "SELECT * FROM artifacts WHERE backend_run_id = ?",
            (run["id"],),
        ).fetchone()
        assert row["task_id"] == self.task_id
        assert row["artifact_type"] == "code"
        assert row["path"] == "single.py"
        assert row["size_bytes"] == len(content.encode())
        assert row["sha256"] == hashlib.sha256(content.encode()).hexdigest()

    # ── Without DB factory ────────────────────────────────────────

    def test_collect_without_db_returns_artifacts(self):
        """Adapter without db_conn_factory still returns artifacts."""
        adapter = CodexAdapter()
        self._write_file("test.py", "pass")
        run = {"id": "fake", "task_id": self.task_id,
               "artifact_root": self.tmpdir}
        artifacts = adapter.collect_artifacts(run)
        assert len(artifacts) == 1
        assert artifacts[0]["path"] == "test.py"
