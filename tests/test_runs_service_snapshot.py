"""Tests for FIX-20260420 snapshot helpers in runs_service.

Four cases mapped to the brief:
  1. Empty directory → empty mapping.
  2. 3 files → 3 entries with sha256.
  3. Diff(before=5, after=6 with 1 modified) → 1 added, 1 modified.
  4. Excludes: `__pycache__`, `.git`, `node_modules` not present in
     snapshot even when they contain files.

Additional coverage:
  - Deterministic output order.
  - Missing root returns ``missing=True``.
  - Truncation at ``max_files`` sets ``truncated=True``.

Run: pytest tests/test_runs_service_snapshot.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import runs_service  # noqa: E402


def _write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


# ── snapshot_directory ────────────────────────────────────────────


def test_empty_directory_returns_empty_mapping():
    with tempfile.TemporaryDirectory() as d:
        snap = runs_service.snapshot_directory(d)
        assert snap["files"] == {}
        assert snap["file_count"] == 0
        assert snap["truncated"] is False
        assert snap["missing"] is False


def test_missing_root_returns_missing_true():
    with tempfile.TemporaryDirectory() as d:
        ghost = Path(d) / "does-not-exist"
        snap = runs_service.snapshot_directory(ghost)
        assert snap["missing"] is True
        assert snap["files"] == {}


def test_three_files_yield_three_entries():
    with tempfile.TemporaryDirectory() as d:
        _write(Path(d) / "index.html", "<html/>")
        _write(Path(d) / "style.css", "body{}")
        _write(Path(d) / "app.js", "console.log(1)")
        snap = runs_service.snapshot_directory(d)
        assert set(snap["files"].keys()) == {"index.html", "style.css", "app.js"}
        # sha256 hex length is always 64
        assert all(len(v) == 64 and int(v, 16) >= 0
                   for v in snap["files"].values())
        # Different contents → different hashes
        assert len(set(snap["files"].values())) == 3


def test_deterministic(tmp_path):
    """Brief calls out this case explicitly
    (test_runs_service_snapshot.py::test_deterministic)."""
    _write(tmp_path / "a.txt", "a")
    _write(tmp_path / "b" / "c.txt", "c")
    _write(tmp_path / "b" / "d.txt", "d")
    snap1 = runs_service.snapshot_directory(tmp_path)
    snap2 = runs_service.snapshot_directory(tmp_path)
    # Keys iterate in the same order AND hashes match. Dict equality
    # covers value equality; list(keys) covers ordering.
    assert list(snap1["files"].keys()) == list(snap2["files"].keys())
    assert snap1["files"] == snap2["files"]


def test_excludes_skip_git_pycache_node_modules(tmp_path):
    _write(tmp_path / "real.py", "print(1)")
    _write(tmp_path / ".git" / "HEAD", "ref: refs/heads/main")
    _write(tmp_path / "pkg" / "__pycache__" / "mod.cpython-311.pyc", "...")
    _write(tmp_path / "node_modules" / "foo" / "index.js", "{}")
    snap = runs_service.snapshot_directory(tmp_path)
    assert list(snap["files"].keys()) == ["real.py"]


def test_custom_excludes_override_default(tmp_path):
    """Caller can override default excludes (ignored .git should show)."""
    _write(tmp_path / "real.py", "print(1)")
    _write(tmp_path / ".git" / "HEAD", "ref")
    snap = runs_service.snapshot_directory(tmp_path, excludes=())
    assert ".git/HEAD" in snap["files"]
    assert "real.py" in snap["files"]


def test_truncation_at_max_files(tmp_path):
    for i in range(5):
        _write(tmp_path / f"f{i}.txt", str(i))
    snap = runs_service.snapshot_directory(tmp_path, max_files=3)
    assert snap["truncated"] is True
    assert snap["file_count"] == 3
    assert len(snap["files"]) == 3


# ── diff_snapshots ────────────────────────────────────────────────


def test_diff_detects_added_modified_removed(tmp_path):
    _write(tmp_path / "a", "1")
    _write(tmp_path / "b", "2")
    _write(tmp_path / "c", "3")
    _write(tmp_path / "d", "4")
    _write(tmp_path / "e", "5")
    before = runs_service.snapshot_directory(tmp_path)

    # Modify b, remove c, add f.
    (tmp_path / "b").write_text("2-modified", encoding="utf-8")
    (tmp_path / "c").unlink()
    _write(tmp_path / "f", "6")
    after = runs_service.snapshot_directory(tmp_path)

    diff = runs_service.diff_snapshots(before, after)
    assert diff["added"] == ["f"]
    assert diff["modified"] == ["b"]
    assert diff["removed"] == ["c"]


def test_diff_brief_signature(tmp_path):
    """Brief: before=5 files, after=6 with 1 modified → 1 added, 1 modified, 0 removed."""
    for name in ("a", "b", "c", "d", "e"):
        _write(tmp_path / name, name)
    before = runs_service.snapshot_directory(tmp_path)

    (tmp_path / "b").write_text("b-new", encoding="utf-8")
    _write(tmp_path / "f", "f")
    after = runs_service.snapshot_directory(tmp_path)

    diff = runs_service.diff_snapshots(before, after)
    assert diff == {"added": ["f"], "modified": ["b"], "removed": []}


def test_diff_accepts_files_mapping_directly():
    """Callers can pass the raw ``files`` mapping instead of the full snapshot."""
    diff = runs_service.diff_snapshots(
        {"a": "0" * 64}, {"a": "1" * 64, "b": "2" * 64},
    )
    assert diff == {"added": ["b"], "modified": ["a"], "removed": []}


def test_diff_empty_snapshots_produces_empty_diff():
    assert runs_service.diff_snapshots({"files": {}}, {"files": {}}) == {
        "added": [], "modified": [], "removed": [],
    }


def test_diff_is_nonempty_helper():
    assert runs_service.diff_is_nonempty(
        {"added": ["x"], "modified": [], "removed": []}
    ) is True
    assert runs_service.diff_is_nonempty(
        {"added": [], "modified": [], "removed": []}
    ) is False


# ── register_artifacts_from_diff ──────────────────────────────────


def _make_db():
    import sqlite3
    import uuid

    SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")
    fd, path = tempfile.mkstemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(open(SCHEMA_PATH).read())

    now = runs_service._now_iso()
    task_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, updated_at) "
        "VALUES (?, 'p', 'P', 'proyecto', ?, ?)",
        (str(uuid.uuid4()), now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, "
        "created_at, updated_at) VALUES (?, 'T', 'proyecto', "
        "'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, "
        "backend_kind, runtime_kind, enabled, priority, "
        "created_at, updated_at) VALUES (?, 'claude_code', 'C', "
        "'claude_code', 'cli', 1, 10, ?, ?)",
        (profile_id, now, now),
    )
    conn.commit()

    run = runs_service.create_run(
        task_id, None, profile_id, conn,
        backend_kind="claude_code", runtime_kind="cli",
    )
    return fd, path, conn, task_id, run["id"]


def test_register_artifacts_from_diff_inserts_rows(tmp_path):
    fd, path, conn, task_id, run_id = _make_db()
    try:
        _write(tmp_path / "index.html", "<html/>")
        _write(tmp_path / "app.js", "x")
        after_snap = runs_service.snapshot_directory(tmp_path)
        diff = {"added": ["index.html", "app.js"], "modified": [], "removed": []}

        n = runs_service.register_artifacts_from_diff(
            task_id, run_id, diff, tmp_path, conn,
            after_snapshot=after_snap,
        )
        assert n == 2

        rows = conn.execute(
            "SELECT artifact_type, path, size_bytes, sha256 FROM artifacts "
            "WHERE backend_run_id = ? ORDER BY path",
            (run_id,),
        ).fetchall()
        assert len(rows) == 2
        paths = {r["path"]: r for r in rows}
        assert paths["index.html"]["artifact_type"] == "added"
        assert paths["index.html"]["size_bytes"] == len("<html/>")
        assert len(paths["index.html"]["sha256"]) == 64
        assert paths["app.js"]["size_bytes"] == 1
    finally:
        conn.close()
        os.close(fd)
        os.unlink(path)


def test_register_artifacts_from_diff_handles_removed(tmp_path):
    fd, path, conn, task_id, run_id = _make_db()
    try:
        diff = {"added": [], "modified": [], "removed": ["gone.txt"]}
        n = runs_service.register_artifacts_from_diff(
            task_id, run_id, diff, tmp_path, conn,
        )
        assert n == 1
        row = conn.execute(
            "SELECT artifact_type, size_bytes, sha256 FROM artifacts "
            "WHERE backend_run_id = ?",
            (run_id,),
        ).fetchone()
        assert row["artifact_type"] == "removed"
        assert row["size_bytes"] is None
        assert row["sha256"] is None
    finally:
        conn.close()
        os.close(fd)
        os.unlink(path)
