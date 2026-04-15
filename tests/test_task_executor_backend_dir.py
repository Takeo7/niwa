"""Tests for the executor's backend-dir resolution (PR-27, Bug 20).

Regression guard for Bug 20 (docs/BUGS-FOUND.md): the executor's
``sys.path.insert`` for the v0.2 backend modules used to compute
``_BACKEND_DIR`` purely from ``__file__``:

    _BACKEND_DIR = Path(__file__).resolve().parent.parent / "niwa-app" / "backend"

That worked from a repo checkout but silently broke after
``setup.py`` copied ``bin/task-executor.py`` to
``/home/niwa/.<instance>/bin/task-executor.py`` — the relative
resolution then pointed at ``/home/niwa/.<instance>/niwa-app/backend``,
a directory that the installer never created. ``sys.path.insert``
on a non-existent path is a silent no-op, ``import routing_service``
raised ``ModuleNotFoundError`` and the executor fell back to the
tier-3 legacy pipeline. The whole v0.2 routing surface
(``routing_decisions``, ``backend_runs``, the new state machine)
never ran in any production install.

The fix: the installer copies the backend tree to a niwa-readable
location and exports ``NIWA_BACKEND_DIR`` in the systemd unit. The
executor prefers that env var over the relative fallback, and
fail-loud-aborts (exit 2) if the directory doesn't exist so PR-25's
post-install health check turns the failure into a visible install
abort within 15 s.

These tests run ``bin/task-executor.py`` as a subprocess so we
exercise the real top-level resolution code (which runs at module
import time, before anything else is wired up).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXECUTOR = REPO_ROOT / "bin" / "task-executor.py"
BACKEND_DIR_REPO = REPO_ROOT / "niwa-app" / "backend"


def _run_executor(env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Spawn ``task-executor.py`` with a clean env. The script will
    exit early — either because the backend dir resolution fails
    (exit 2, our fail-loud) or because a later check fails (no
    ~/.niwa install). We only care about behaviour around the
    backend-dir block, which runs first at import time."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        # Force the executor to look in a place where there is no
        # Niwa install, so the only thing we exercise is the
        # backend-dir resolution at the top of the module.
        "HOME": "/tmp",
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(EXECUTOR)],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


class TestBackendDirEnvVarPrecedence:
    """``NIWA_BACKEND_DIR`` must take precedence over the relative
    fallback. This is the contract the installer relies on."""

    def test_env_var_overrides_relative_fallback(self, tmp_path):
        """Set NIWA_BACKEND_DIR to a *valid* tree (the repo's own
        backend dir) and verify the executor accepts it. We don't
        try to inspect _BACKEND_DIR from the outside — instead we
        rely on the negative case in the next test, plus the
        positive signal that the executor moves past the backend
        check (failing later for unrelated reasons)."""
        result = _run_executor({"NIWA_BACKEND_DIR": str(BACKEND_DIR_REPO)})
        # The fail-loud message must NOT appear — the env var
        # pointed at a real directory.
        assert "FATAL: niwa backend modules not found" not in result.stderr, (
            f"executor reported missing backend dir even though "
            f"NIWA_BACKEND_DIR={BACKEND_DIR_REPO} exists. stderr: "
            f"{result.stderr}"
        )

    def test_env_var_pointing_at_missing_dir_fails_loud(self, tmp_path):
        """If NIWA_BACKEND_DIR is set but the directory doesn't
        exist, exit 2 with a clear FATAL message."""
        ghost = tmp_path / "no" / "such" / "dir"
        result = _run_executor({"NIWA_BACKEND_DIR": str(ghost)})
        assert result.returncode == 2, (
            f"expected exit 2 on missing backend dir, got "
            f"{result.returncode}. stderr={result.stderr}"
        )
        assert "FATAL: niwa backend modules not found" in result.stderr
        assert str(ghost) in result.stderr

    def test_fatal_message_mentions_both_dev_and_install_paths(self, tmp_path):
        """The fail-loud message must guide both the dev (run from
        repo) and the operator (set NIWA_BACKEND_DIR)."""
        ghost = tmp_path / "ghost"
        result = _run_executor({"NIWA_BACKEND_DIR": str(ghost)})
        assert result.returncode == 2
        assert "repo checkout" in result.stderr
        assert "NIWA_BACKEND_DIR" in result.stderr
        assert "/opt/" in result.stderr  # mentions installer-typical path


class TestRelativeFallbackInDev:
    """When ``NIWA_BACKEND_DIR`` is unset, the relative-to-__file__
    fallback must still resolve correctly for repo-checkout dev
    runs and CI. PR-27 must not break that path."""

    def test_relative_fallback_finds_repo_backend(self):
        """No NIWA_BACKEND_DIR, executor lives next to niwa-app/ in
        the repo. Backend dir resolution must succeed silently."""
        # Explicitly remove the env var inherited from the test
        # harness, if any.
        env = {"PATH": os.environ.get("PATH", ""), "HOME": "/tmp"}
        result = subprocess.run(
            [sys.executable, str(EXECUTOR)],
            capture_output=True, text=True, env=env, timeout=15,
        )
        assert "FATAL: niwa backend modules not found" not in result.stderr, (
            "relative fallback must resolve the backend dir when the "
            "executor is run from a repo checkout. stderr: "
            f"{result.stderr}"
        )
