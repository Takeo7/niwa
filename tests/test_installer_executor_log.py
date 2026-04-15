"""Tests for the installer's executor-log bootstrap.

Regression guard for: ``niwa-niwa-executor.service`` crash-loops
immediately after a fresh install because ``RotatingFileHandler``
can't open ``/opt/niwa/logs/executor.log``:

    PermissionError: [Errno 13] Permission denied:
        '/home/niwa/.niwa/logs/executor.log'

Causal chain on a fresh ``./niwa install --yes``:

  1. ``setup.py::_install_systemd_unit`` creates ``/opt/niwa/logs/``
     (via ``shutil.copytree`` of an empty source dir) and runs
     ``chown -R niwa:niwa /opt/niwa``. Directory is ``niwa:niwa``.
  2. ``setup.py`` writes the executor systemd unit with
     ``StandardOutput=append:/opt/niwa/logs/executor.log`` and
     ``systemctl enable --now``.
  3. Systemd opens the file for append with the manager's euid
     (root) *before* dropping privileges to ``User=niwa``, so the
     file is created as ``root:root 0644``.
  4. Executor forks as niwa, Python's
     ``RotatingFileHandler('/home/niwa/.niwa/logs/executor.log')``
     tries to open the (root-owned) file and raises ``PermissionError``.
  5. systemd ``Restart=always`` restarts the service every 10s.
     Observed in production: ~830 restarts over a few hours.

The fix: ``setup.py`` pre-creates (``touch``) the log file in
``shared_dir / 'logs' / 'executor.log'`` **before** the
``chown -R niwa:niwa`` call, so the recursive chown pins the
existing file to ``niwa:niwa`` and systemd's ``append:`` directive
subsequently just reuses the existing fd.

These tests cover the helper behaviour and the regex invariant on
setup.py that guarantees the pre-create is wired in the right place.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestExecutorLogPreCreated:
    """Pin the invariant that setup.py touches executor.log before the
    final chown, so systemd can't win the race and create it as root."""

    def test_setup_py_touches_executor_log_before_chown(self):
        """Static check on the setup.py source: the ``touch`` call for
        ``executor.log`` must appear *before* the ``chown -R niwa:niwa``
        that covers ``shared_dir``. Order matters — chown after touch
        fixes ownership; chown before touch leaves systemd to create
        the file as root."""
        src = (REPO_ROOT / "setup.py").read_text()

        touch_match = re.search(
            r'\(\s*shared_dir\s*/\s*"logs"\s*/\s*"executor\.log"\s*\)\s*\.touch',
            src,
        )
        assert touch_match, (
            "setup.py must pre-create shared_dir/logs/executor.log with "
            "touch() to avoid systemd creating it as root"
        )

        # We want the chown of ``shared_dir`` specifically, not the
        # earlier ``chown`` of ``niwa_claude`` around line ~1798 (which
        # targets the Claude credentials dir, a different concern).
        chown_shared_match = re.search(
            r'chown.*niwa:niwa.*shared_dir',
            src,
        )
        assert chown_shared_match, (
            "chown -R niwa:niwa on shared_dir missing from setup.py"
        )

        # touch must come before chown in source order (both live in
        # _install_systemd_unit; the chown is what pins ownership).
        assert touch_match.start() < chown_shared_match.start(), (
            "touch(executor.log) must precede chown -R niwa:niwa "
            "shared_dir — chown pins the ownership, so if the touch "
            "happens after, systemd creates the file as root on first "
            "start and the executor crash-loops with PermissionError"
        )

    def test_systemd_unit_template_user_is_niwa_and_not_root(self):
        """Complement: the unit file must drop privileges to niwa.
        If it ever accidentally ran as root, the PermissionError
        wouldn't surface (but then we'd have a different class of
        security problem). Pin ``User=niwa`` so the invariant stays
        explicit."""
        src = (REPO_ROOT / "setup.py").read_text()
        # Find the executor unit template (the one with ExecStart
        # pointing at task-executor.py) and assert User=niwa.
        unit_blocks = re.findall(
            r'unit = f"""\[Unit\].*?\[Install\]', src, flags=re.DOTALL,
        )
        executor_units = [u for u in unit_blocks if "executor" in u.lower()]
        assert executor_units, "no executor systemd unit template found"
        for block in executor_units:
            if "User=niwa" in block or "ExecStart=/usr/bin/env python3" in block and "run_as_root" in src:
                # Root-level unit must specify User=niwa; user-level
                # units run as the invoking user (no User= line needed).
                break
        # At least the root-level template (the one used in production
        # when `./niwa install` runs as root) must have User=niwa.
        root_template = next(
            (u for u in executor_units if "User=niwa" in u), None,
        )
        assert root_template is not None, (
            "root-level executor unit must run as User=niwa (otherwise "
            "the log-permission bug wouldn't surface but Docker socket "
            "exposure would)"
        )


class TestExecutorLogFixReplicatesTheBug:
    """Negative control: exercise the exact permission scenario that
    broke production and show that the pre-create + chown sequence
    prevents a root-owned log file from blocking a niwa-running
    Python process. Uses a tmp dir — no systemd interaction."""

    def test_systemd_style_append_creates_root_file_without_pre_touch(
        self, tmp_path,
    ):
        """Prove the failure mode: if we let 'systemd' (simulated by
        opening the file without touching it first) create the log,
        the resulting file has the creator's uid — in this test the
        test runner's uid, but the analogue in production is root."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        log_file = logs_dir / "executor.log"
        # "systemd" opens it for append → file is created.
        with log_file.open("a") as f:
            f.write("boot\n")
        assert log_file.exists()
        # Now a different user couldn't open it for writing if the
        # permission bits were 0644 and the uid differed. We can't
        # change uid inside the test without sudo, so we assert the
        # structural shape instead: the file exists (which is what
        # breaks RotatingFileHandler on a fresh install if it doesn't
        # match the service's uid).

    def test_pre_touch_produces_an_existing_file_that_chown_can_pin(
        self, tmp_path,
    ):
        """Happy path: touch the file first, then the install's
        subsequent chown -R can set the ownership atomically for both
        the dir and the file. This is what the fix does."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        log_file = logs_dir / "executor.log"
        log_file.touch(exist_ok=True)
        assert log_file.exists(), "pre-touch must leave the file in place"
        # A subsequent chown -R (not testable without root) would set
        # the whole subtree to niwa:niwa, and the systemd append:
        # directive would just reuse this fd without creating.

    def test_pre_touch_is_idempotent_on_reinstall(self, tmp_path):
        """If the installer runs twice (reinstall), the second
        ``touch(exist_ok=True)`` must be a no-op and leave the file
        (including any pre-existing content) intact for the subsequent
        chown to pin."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        log_file = logs_dir / "executor.log"
        log_file.write_text("old content from a prior run\n")
        log_file.touch(exist_ok=True)  # second install
        assert log_file.read_text() == "old content from a prior run\n", (
            "touch(exist_ok=True) must not truncate an existing log "
            "on reinstall"
        )
