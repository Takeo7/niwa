"""Tests for the installer's hosting-server path swap (PR-26).

Regression guard for **Bug 21** (docs/BUGS-FOUND.md): the hosting
``systemd`` unit ran as ``User=niwa`` but its ``ExecStart`` pointed at
``/root/.<instance>/bin/hosting-server.py``. ``/root`` is ``drwx------``,
so the niwa user can't traverse it and Python exits with
``can't open file '/root/...': [Errno 13] Permission denied`` before
even importing. On a fresh ``./niwa install --quick --mode assistant
--yes`` with ``sudo`` the hosting service crash-looped forever.

The fix mirrors the executor's pre-existing pattern in
``_install_systemd_unit``: copy the binary into
``/home/niwa/.<instance>/bin/hosting-server.py`` (niwa-readable),
``chown niwa:niwa`` that copy, and re-point the unit's ``ExecStart``
at it.

These tests also cover **sub-bug 18a**: pre-create ``hosting.log``
with ``touch(exist_ok=True)`` + ``chown niwa:niwa`` before systemd
opens it for append, so a future Python-level logger in hosting
can't reproduce the Bug 18 crash-loop silently.

Static regex checks on ``setup.py``, no subprocess — same pattern
as ``tests/test_installer_executor_log.py``.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestHostingBinaryPathSwap:
    """Pin the invariant that hosting-server.py is copied into
    /home/niwa/.<instance>/bin/ when installing as root, and that the
    systemd unit's ExecStart points at that path — not at the
    root-owned install_dir copy."""

    def _hosting_root_block(self) -> str:
        """Extract the root-branch body of install_hosting_server."""
        src = (REPO_ROOT / "setup.py").read_text()
        start = src.index("def install_hosting_server(")
        # Stop at the next top-level ``def`` (column 0). Use a regex
        # lookahead so we capture everything up to the function break.
        tail = src[start:]
        m = re.search(r"\n(?=def [a-zA-Z_])", tail)
        assert m is not None, "couldn't locate end of install_hosting_server"
        func_src = tail[: m.start() + 1]

        # The linux/root sub-branch starts with a ``run_as_root = ...``
        # and an ``if run_as_root:`` header. Slice from there to the
        # matching ``else:`` at the same indent (8 spaces).
        run_idx = func_src.index("if run_as_root:")
        after = func_src[run_idx:]
        # Match the first ``else:`` preceded by exactly 8 spaces — the
        # else of the root/user branch.
        else_match = re.search(r"\n {8}else:\n", after)
        assert else_match is not None, (
            "couldn't find the user-scope else branch in "
            "install_hosting_server — structure changed?"
        )
        return after[: else_match.start()]

    def test_hosting_binary_copied_into_niwa_home(self):
        """``shutil.copy`` into ``/home/niwa/.<instance>/bin/``
        must happen before the systemd unit is written, so
        ``ExecStart=... {dest}`` resolves to the niwa-readable path."""
        root_block = self._hosting_root_block()

        copy_match = re.search(
            r"shutil\.copy\(\s*str\(dest\)\s*,\s*str\(niwa_hosting_dest\)\s*\)",
            root_block,
        )
        assert copy_match, (
            "root branch must copy the hosting binary into "
            "niwa_hosting_dest (mirror of the executor pattern)"
        )

        niwa_home_match = re.search(
            r'niwa_home\s*=\s*Path\("/home/niwa"\)\s*/\s*f"\.\{cfg\.instance_name\}"',
            root_block,
        )
        assert niwa_home_match, (
            "root branch must compute niwa_home = /home/niwa/.<instance>"
        )
        assert niwa_home_match.start() < copy_match.start(), (
            "niwa_home must be computed before copying into it"
        )

    def test_hosting_binary_chowned_to_niwa(self):
        """The copied binary must be ``chown niwa:niwa``-ed so it's
        readable when systemd drops privileges to ``User=niwa``."""
        root_block = self._hosting_root_block()
        chown_match = re.search(
            r'"chown",\s*"niwa:niwa",\s*str\(niwa_hosting_dest\)',
            root_block,
        )
        assert chown_match, (
            "chown niwa:niwa niwa_hosting_dest missing — the copied "
            "binary must be owned by the niwa user or ExecStart will "
            "fail with Permission denied under User=niwa"
        )

    def test_dest_reassigned_before_unit_written(self):
        """``dest = niwa_hosting_dest`` must happen before the unit
        template so ``ExecStart=... {dest}`` bakes in the niwa path."""
        root_block = self._hosting_root_block()
        reassign = re.search(r"\n\s+dest\s*=\s*niwa_hosting_dest\b", root_block)
        assert reassign, "dest must be reassigned to niwa_hosting_dest"
        unit_template = re.search(
            r"unit\s*=\s*f\"\"\"\[Unit\]", root_block
        )
        assert unit_template, "unit template not found in root branch"
        assert reassign.start() < unit_template.start(), (
            "dest reassignment must precede the unit template or "
            "ExecStart will point at the root-owned path again"
        )

    def test_execstart_does_not_point_at_root_path(self):
        """Static guard: the root-branch unit template must not bake
        in ``/root/`` anywhere inside ExecStart. Cheap insurance in
        case someone re-introduces the bug by copy-paste."""
        root_block = self._hosting_root_block()
        unit_match = re.search(
            r'unit\s*=\s*f"""(.+?)"""', root_block, flags=re.DOTALL,
        )
        assert unit_match, "unit template missing in root branch"
        unit_body = unit_match.group(1)
        assert "/root/" not in unit_body, (
            "hosting unit template must not reference /root/ in any "
            "form — User=niwa cannot traverse it. Path must resolve "
            "under /home/niwa or /opt/<instance>."
        )


class TestHostingLogPreCreated:
    """Defense in depth for **sub-bug 18a**: pre-create hosting.log so
    systemd's ``append:`` doesn't race to create it as root."""

    def _hosting_root_block(self) -> str:
        return TestHostingBinaryPathSwap()._hosting_root_block()

    def test_hosting_log_touched_and_chowned(self):
        root_block = self._hosting_root_block()

        touch_match = re.search(
            r'hosting_log\s*=\s*shared_dir\s*/\s*"logs"\s*/\s*"hosting\.log"',
            root_block,
        )
        assert touch_match, (
            "hosting_log = shared_dir/logs/hosting.log must be "
            "computed in the root branch (mirrors executor.log in "
            "_install_systemd_unit from PR-23)"
        )

        touch_call = re.search(
            r"hosting_log\.touch\(exist_ok=True\)", root_block
        )
        assert touch_call, (
            "hosting_log.touch(exist_ok=True) missing — without the "
            "pre-create, systemd will open the file for append as "
            "root on first start and a Python-level logger added "
            "later would crash with PermissionError (Bug 18 replay)"
        )

        chown_match = re.search(
            r'"chown",\s*"niwa:niwa",\s*str\(hosting_log\)', root_block
        )
        assert chown_match, (
            "chown niwa:niwa hosting_log missing — touch alone "
            "leaves the file root-owned; the chown pins it to niwa."
        )

        # Order: touch before chown (chown on a missing file is a no-op).
        assert touch_call.start() < chown_match.start(), (
            "touch must precede chown for the hosting_log"
        )

    def test_hosting_log_idempotent_on_reinstall(self, tmp_path):
        """Structural: ``touch(exist_ok=True)`` is idempotent and does
        not truncate existing content. Mirrors the executor.log test
        in tests/test_installer_executor_log.py."""
        logs = tmp_path / "logs"
        logs.mkdir()
        f = logs / "hosting.log"
        f.write_text("old content from a prior install\n")
        f.touch(exist_ok=True)  # simulate reinstall
        assert f.read_text() == "old content from a prior install\n"


class TestHostingServiceHealthCheckStillWired:
    """PR-25 added ``_verify_service_or_abort`` after the hosting
    ``systemctl enable --now``. Pin that the PR-26 refactor did not
    accidentally drop the fail-loud wiring — the whole point of PR-25
    was that this bug would otherwise hide as a crash-loop."""

    def test_verify_service_or_abort_called_for_hosting(self):
        src = (REPO_ROOT / "setup.py").read_text()
        # Locate install_hosting_server body and assert the helper is
        # invoked there. This is a regression guard against future
        # copy-paste that forgets the verify step.
        start = src.index("def install_hosting_server(")
        tail = src[start:]
        m = re.search(r"\n(?=def [a-zA-Z_])", tail)
        body = tail[: m.start() + 1] if m else tail
        assert "_verify_service_or_abort(unit_name" in body, (
            "install_hosting_server must call _verify_service_or_abort "
            "after systemctl enable --now (PR-25 invariant)"
        )
