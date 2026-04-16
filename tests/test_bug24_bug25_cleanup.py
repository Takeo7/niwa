"""Tests for PR-41 — Bugs 24 + 25 cleanup.

Bug 24 (docs/BUGS-FOUND.md:416): ``ClaudeCodeAdapter.start()`` used
``Path(artifact_root).mkdir(parents=True, exist_ok=True)`` raw. On
``PermissionError`` / ``OSError`` the exception would propagate to the
executor's generic ``except Exception`` which already marks the run
``failed`` — but with a vague ``error_code='adapter_exception'``. The
operator would have to dig through logs to figure out that
permissions were the issue. Fix: wrap the mkdir in a helper, on
failure transition the run explicitly with
``error_code='artifact_root_mkdir_failed'`` and return a failed-status
dict so the caller gets the same shape as other pre-execution
denials (non-transient — no fallback).

Bug 25 (docs/BUGS-FOUND.md:436): ``_prepare_backend_env`` for the
codex adapter does ``tempfile.mkdtemp(prefix='niwa-codex-v02-')`` and
stores the path in ``extra_env["CODEX_HOME"]``. The legacy path
cleaned it up in a ``finally``; the v0.2 path didn't. If the adapter
crashed after the mkdtemp, the directory leaked under /tmp. Fix:
track any ``CODEX_HOME`` produced by ``_prepare_backend_env`` in a
list owned by the ``_execute_task_v02`` wrapper and ``shutil.rmtree``
each in the ``finally``.

These tests cover:

* Adapter returns a structured failure (no raise) when
  ``artifact_root`` lives somewhere it can't mkdir.
* The failure dict uses the specific ``error_code`` so the UI can
  show a better message (PR-39 banner).
* The adapter calls ``finish_run`` with the same specific code so
  the run doesn't linger in ``starting``.
* Executor source guards: the body tracks any ``CODEX_HOME`` from
  ``_prepare_backend_env`` into the cleanup list, and the wrapper
  ``shutil.rmtree``s each in the ``finally``.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
BIN_DIR = REPO_ROOT / "bin"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ────────────────── Bug 24: adapter mkdir error handling ──────────────────

class TestArtifactRootMkdirFailure:
    """Pin the Bug 24 contract: adapter doesn't raise on mkdir failure,
    instead returns a structured failure dict AND marks the run
    ``failed`` with a specific error_code so it doesn't linger in
    ``starting``."""

    def _load_adapter_with_fake_db(self):
        from backend_adapters.claude_code import ClaudeCodeAdapter

        # Track the finish_run call for assertion.
        record = {"finish_called_with": None, "event_message": None}

        # Patch the ``runs_service`` module globally so the adapter's
        # ``_finish_run_failed`` picks up our fakes via ``import
        # runs_service``.
        fake_runs = MagicMock()
        def _finish(run_id, outcome, conn, *, error_code=None, exit_code=None):
            record["finish_called_with"] = {
                "run_id": run_id, "outcome": outcome,
                "error_code": error_code, "exit_code": exit_code,
            }
        def _record(run_id, event_type, conn, *, message=""):
            record["event_message"] = message
        fake_runs.finish_run = _finish
        fake_runs.record_event = _record
        sys.modules["runs_service"] = fake_runs

        # A minimal adapter wired to a no-op DB factory so
        # ``_finish_run_failed`` takes the real path.
        adapter = ClaudeCodeAdapter(db_conn_factory=lambda: MagicMock())
        return adapter, record

    def test_returns_failed_dict_with_specific_error_code(self, tmp_path):
        adapter, record = self._load_adapter_with_fake_db()
        # Point artifact_root at a path under a file (not a dir) —
        # makes mkdir raise NotADirectoryError.
        parent_file = tmp_path / "blocker"
        parent_file.write_text("x")
        bad_root = str(parent_file / "subdir")

        run = {"id": "run-bad", "artifact_root": bad_root}
        result = adapter._ensure_artifact_root(run)
        assert result is not None, (
            "mkdir failure must return a structured failure dict, "
            "not raise (raising would escalate to fallback which "
            "would hit the same unreadable path)."
        )
        assert result["status"] == "failed"
        assert result["outcome"] == "failure"
        assert result["error_code"] == "artifact_root_mkdir_failed", (
            "Specific error_code lets the operator diagnose quickly "
            "(filesystem/permissions) instead of the generic "
            "'adapter_exception'."
        )
        assert "artifact_root_mkdir_failed" in result["reason"] or \
               bad_root in result["reason"]

    def test_run_is_transitioned_to_failed(self, tmp_path):
        adapter, record = self._load_adapter_with_fake_db()
        parent_file = tmp_path / "blocker"
        parent_file.write_text("x")
        bad_root = str(parent_file / "subdir")

        adapter._ensure_artifact_root({"id": "run-X", "artifact_root": bad_root})

        assert record["finish_called_with"] is not None, (
            "The run must NOT linger in 'starting' — the adapter "
            "has to explicitly mark it failed before returning."
        )
        assert record["finish_called_with"]["run_id"] == "run-X"
        assert record["finish_called_with"]["outcome"] == "failure"
        assert record["finish_called_with"]["error_code"] == \
            "artifact_root_mkdir_failed"

    def test_missing_artifact_root_is_noop(self):
        """Not every run has an artifact_root (e.g. tasks with no
        project_id, legacy paths). ``_ensure_artifact_root`` must
        skip cleanly in that case."""
        adapter, _ = self._load_adapter_with_fake_db()
        assert adapter._ensure_artifact_root({"id": "r", "artifact_root": None}) is None
        assert adapter._ensure_artifact_root({"id": "r"}) is None

    def test_existing_artifact_root_is_noop(self, tmp_path):
        adapter, record = self._load_adapter_with_fake_db()
        good = tmp_path / "out"
        good.mkdir()
        assert adapter._ensure_artifact_root(
            {"id": "r", "artifact_root": str(good)},
        ) is None
        # No failure path triggered.
        assert record["finish_called_with"] is None


# ────────────────── Bug 25: codex tmpdir cleanup (static guards) ──────────────────

class TestCodexTmpdirCleanup:
    """The executor source must track any CODEX_HOME produced by
    ``_prepare_backend_env`` and rmtree it in the wrapper's finally.
    These are static source guards because exercising the real flow
    would require a codex OAuth token + full v0.2 pipeline stub — the
    invariant we care about is small and regex-checkable."""

    SRC = (BIN_DIR / "task-executor.py").read_text()

    def test_wrapper_owns_codex_tmpdirs_list(self):
        assert "codex_tmpdirs: list[str] = []" in self.SRC, (
            "_execute_task_v02 must declare the list in the wrapper "
            "scope so the ``finally`` can see it."
        )

    def test_body_appends_codex_home_to_tracker(self):
        assert 'codex_tmpdirs.append(extra_env["CODEX_HOME"])' in self.SRC, (
            "After _prepare_backend_env returns extra_env with "
            "CODEX_HOME, the body must add the path to the tracker "
            "so cleanup can find it."
        )

    def test_finally_calls_rmtree(self):
        # The finally block must shutil.rmtree each tracked dir.
        assert "shutil.rmtree(tmpdir, ignore_errors=True)" in self.SRC, (
            "cleanup must use shutil.rmtree with ignore_errors=True "
            "so a stray file permission doesn't hang the executor "
            "forever on the codex tmpdir."
        )

    def test_cleanup_runs_before_auto_project_finalize(self):
        """Order in the finally matters: rmtree is cheap and never
        needs the DB, auto_project_finalize hits the DB. If rmtree
        comes last and crashes, the DB work still runs; if first
        and crashes, best-effort log.exception lets finalize still
        run. Both orders are acceptable — pin the current one to
        catch accidental reordering in refactors."""
        finally_idx = self.SRC.index("for tmpdir in codex_tmpdirs:")
        auto_idx = self.SRC.index("_auto_project_finalize(auto_project_ctx, task_id)")
        assert finally_idx < auto_idx, (
            "codex tmpdir cleanup must come before "
            "_auto_project_finalize in the finally — keep the cheap "
            "FS cleanup first so a DB hang doesn't leak /tmp."
        )


# ────────────────── Integration: _prepare_backend_env contract ──────────────────

class TestPrepareBackendEnvContract:
    """Regression guard for the codex branch: extra_env dict exposes
    CODEX_HOME so the wrapper can track it. Tested with token
    injection + prepare_backend_env called directly."""

    def test_codex_extra_env_exposes_codex_home(self, tmp_path, monkeypatch):
        """If the codex OAuth token is available, _prepare_backend_env
        must return a dict with CODEX_HOME pointing at a freshly
        mkdtemp'd dir (the caller then tracks + cleans it)."""
        # Provide a fake executor environment minimally.
        (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)
        (tmp_path / "secrets" / "mcp.env").write_text("NIWA_DB_PATH=/tmp/x\n")
        (tmp_path / "logs").mkdir(exist_ok=True)
        (tmp_path / "data").mkdir(exist_ok=True)
        (tmp_path / "logs" / "executor.log").touch()
        monkeypatch.setenv("NIWA_HOME", str(tmp_path))

        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_executor_prepare_env", str(BIN_DIR / "task-executor.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            pytest.skip(f"executor import failed: {e}")

        # Short-circuit the oauth lookup so the codex branch proceeds.
        monkeypatch.setattr(
            mod, "_get_openai_oauth_token",
            lambda: "fake-access-token",
        )
        monkeypatch.setattr(
            mod, "_get_openai_refresh_token",
            lambda: "fake-refresh-token",
        )

        extra = mod._prepare_backend_env({"slug": "codex"})
        assert extra is not None
        assert "CODEX_HOME" in extra, (
            "Bug 25 cleanup needs this field to find the tmpdir. "
            "If the contract changes, _execute_task_v02's tracker "
            "loop silently stops cleaning up."
        )
        codex_home = extra["CODEX_HOME"]
        try:
            assert Path(codex_home).is_dir()
            # The auth.json file is still written — that's the
            # caller-visible behaviour, not a cleanup concern.
            assert (Path(codex_home) / "auth.json").is_file()
        finally:
            # Manually clean up — this test does NOT go through the
            # executor's finally, so we're responsible.
            import shutil
            shutil.rmtree(codex_home, ignore_errors=True)
