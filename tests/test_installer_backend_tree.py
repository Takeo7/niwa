"""Tests for the installer's backend-tree copy (PR-27, Bug 20).

Companion to ``tests/test_task_executor_backend_dir.py``. Those
tests cover the executor side; this file pins the installer side:
``setup.py::_install_systemd_unit`` must (a) copy
``niwa-app/backend/`` to a niwa-readable location and (b) export
``NIWA_BACKEND_DIR`` in both systemd unit templates so the executor
finds the modules at runtime.

Static regex-only checks. No subprocess execution against systemd
or chown — same pattern as ``tests/test_installer_executor_log.py``
and ``tests/test_installer_hosting_path.py``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_PY = REPO_ROOT / "setup.py"
BACKEND_REPO = REPO_ROOT / "niwa-app" / "backend"


class TestBackendTreeCopy:
    """The installer must replicate niwa-app/backend/ into a
    location the niwa user can read."""

    def test_repo_has_backend_tree_to_copy(self):
        """Sanity check the source of the copy actually exists in
        the repo. If this ever fails, the whole assumption of PR-27
        is invalid and we need to rethink."""
        assert BACKEND_REPO.is_dir(), (
            f"repo backend dir missing at {BACKEND_REPO}; PR-27's "
            f"copy step would have nothing to source from"
        )
        # Spot-check a few files PR-27 actually needs at runtime.
        for module in (
            "routing_service.py",
            "runs_service.py",
            "backend_registry.py",
            "state_machines.py",
        ):
            assert (BACKEND_REPO / module).is_file(), (
                f"{module} missing from {BACKEND_REPO} — PR-27 "
                f"assumes these are present for the executor to "
                f"import after copy"
            )
        assert (BACKEND_REPO / "backend_adapters").is_dir()

    def test_setup_copies_backend_in_root_branch(self):
        """Root-scope install: copytree from REPO_ROOT/niwa-app/backend
        into shared_dir/niwa-app/backend, with __pycache__ filtered."""
        src = SETUP_PY.read_text()
        # The copy must appear inside the root branch of
        # _install_systemd_unit. We check the structural pieces
        # rather than a single regex to make failure messages
        # actionable.
        assert "shared_dir / \"niwa-app\" / \"backend\"" in src, (
            "shared_dir / 'niwa-app' / 'backend' not referenced — "
            "the installer must compute a niwa-readable backend path"
        )
        copy_match = re.search(
            r'shutil\.copytree\(\s*str\(REPO_ROOT\s*/\s*"niwa-app"\s*/\s*"backend"\)',
            src,
        )
        assert copy_match, (
            "shutil.copytree(REPO_ROOT/niwa-app/backend, ...) missing — "
            "the installer must source the copy from the repo"
        )
        # __pycache__ must be filtered to avoid carrying stale
        # bytecode + bloating the install.
        assert 'ignore_patterns("__pycache__"' in src, (
            "shutil.copytree must filter __pycache__ via "
            "shutil.ignore_patterns to avoid stale bytecode"
        )

    def test_setup_idempotent_on_reinstall(self):
        """Reinstalls must not fail with FileExistsError. The
        installer either rmtree-s the target before copytree or
        passes ``dirs_exist_ok=True``. We accept either."""
        src = SETUP_PY.read_text()
        rmtree_first = "shutil.rmtree(str(backend_runtime_dir))" in src
        dirs_exist_ok = "dirs_exist_ok=True" in src
        assert rmtree_first or dirs_exist_ok, (
            "backend tree copy must be idempotent on reinstall — "
            "either shutil.rmtree(target) before copy OR "
            "dirs_exist_ok=True in copytree"
        )


class TestBackendDirEnvInUnit:
    """Both unit templates (root-scope and user-scope) must export
    ``NIWA_BACKEND_DIR`` so the executor's env-var lookup succeeds."""

    def _executor_unit_blocks(self):
        """Extract the two ExecStart-bearing unit templates from
        ``_install_systemd_unit``."""
        src = SETUP_PY.read_text()
        start = src.index("def _install_systemd_unit(")
        tail = src[start:]
        end = re.search(r"\n(?=def [a-zA-Z_])", tail)
        body = tail[: end.start() + 1] if end else tail
        # Two ``unit = f\"\"\"[Unit]`` blocks expected, one per scope.
        blocks = re.findall(
            r'unit\s*=\s*f"""\[Unit\].*?WantedBy=\S+\n"""',
            body,
            flags=re.DOTALL,
        )
        return blocks

    def test_two_unit_templates_present(self):
        """Sanity: there should be exactly two unit templates in
        _install_systemd_unit (root and user scopes)."""
        blocks = self._executor_unit_blocks()
        assert len(blocks) == 2, (
            f"expected 2 unit templates in _install_systemd_unit, "
            f"got {len(blocks)} — the test extraction is stale or "
            f"the installer structure changed"
        )

    def test_both_units_export_niwa_backend_dir(self):
        """Both root-scope and user-scope units must contain an
        Environment= line for NIWA_BACKEND_DIR. Without this the
        executor falls back to the relative path resolution and
        Bug 20 reproduces."""
        blocks = self._executor_unit_blocks()
        for i, block in enumerate(blocks):
            assert 'Environment="NIWA_BACKEND_DIR=' in block, (
                f"unit template #{i} missing "
                f'Environment="NIWA_BACKEND_DIR=...". Without it the '
                f"executor falls back to a path that doesn't exist "
                f"in production (Bug 20). Block:\n{block}"
            )


class TestExecutorFailLoudOnMissingBackend:
    """Pin that the executor source still has the fail-loud
    sys.exit(2) for missing backend dir — PR-25's health check
    relies on this signal to surface install-time misconfigurations."""

    def test_executor_source_has_fail_loud_block(self):
        src = (REPO_ROOT / "bin" / "task-executor.py").read_text()
        # Look for the marker line + sys.exit(2). We don't pin the
        # exact wording of the error message (operators may want to
        # rephrase) but we DO pin the structural contract.
        assert "FATAL: niwa backend modules not found" in src, (
            "fail-loud message must mention 'FATAL: niwa backend "
            "modules not found' so operators recognise it"
        )
        assert "sys.exit(2)" in src, (
            "executor must sys.exit(2) when backend dir is missing — "
            "PR-25's _verify_service_or_abort relies on the systemd "
            "service crash-restarting to flag the misconfiguration"
        )

    def test_executor_prefers_env_var_over_relative_path(self):
        src = (REPO_ROOT / "bin" / "task-executor.py").read_text()
        assert 'os.environ.get("NIWA_BACKEND_DIR")' in src, (
            "executor must check NIWA_BACKEND_DIR env var first "
            "before falling back to relative path"
        )
        # The env-var lookup must lexically precede the
        # __file__-relative computation, otherwise the env var has
        # no effect.
        env_idx = src.index('os.environ.get("NIWA_BACKEND_DIR")')
        rel_idx = src.index(
            'Path(__file__).resolve().parent.parent / "niwa-app" / "backend"'
        )
        assert env_idx < rel_idx, (
            "NIWA_BACKEND_DIR env var lookup must precede the "
            "relative-path fallback in resolution order"
        )
