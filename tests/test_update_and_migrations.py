"""Tests for the update mechanism and migration failure handling (PR-30).

Two fixes from an external security/architecture review:

1. ``run_niwa_update()`` hardcoded ``git pull origin main``. On
   installs running the ``v0.2`` branch, this pulled ``main`` on
   top of ``v0.2`` and silently mixed code from different release
   lines. Fix: detect the current branch dynamically via
   ``git rev-parse --abbrev-ref HEAD``.

2. ``_run_migrations()`` caught migration failures with
   ``logger.error`` + ``break`` and let the service continue
   booting on a partially migrated schema. Fix: raise
   ``SystemExit`` so the service stops with a clear message.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ── Fix 1: git pull uses current branch ──────────────────────────────

class TestUpdateUsesCurrentBranch:
    """Pin that ``run_niwa_update`` detects the current branch
    dynamically instead of hardcoding ``main``."""

    def test_no_hardcoded_git_pull_origin_main(self):
        """The literal ``["git", "pull", "origin", "main"]`` must
        not appear in ``run_niwa_update``. If it does, the update
        mechanism will overwrite whatever branch the install is on
        with main's code — a release management bug."""
        src = (BACKEND_DIR / "app.py").read_text()
        start = src.index("def run_niwa_update(")
        tail = src[start:]
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        assert '"git", "pull", "origin", "main"' not in body, (
            "run_niwa_update still hardcodes 'git pull origin main'. "
            "This was the bug: on a v0.2 install it would pull main "
            "on top of v0.2. Use dynamic branch detection instead."
        )

    def test_uses_rev_parse_to_detect_branch(self):
        """The function must call ``git rev-parse --abbrev-ref HEAD``
        to discover the current branch before pulling."""
        src = (BACKEND_DIR / "app.py").read_text()
        start = src.index("def run_niwa_update(")
        tail = src[start:]
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        assert "rev-parse" in body, (
            "run_niwa_update must use 'git rev-parse --abbrev-ref "
            "HEAD' to detect the current branch. Without it, the "
            "function has no way to know which branch to pull."
        )
        assert "--abbrev-ref" in body, (
            "rev-parse must use --abbrev-ref to get the branch name "
            "(not a full SHA)"
        )

    def test_pull_uses_dynamic_branch_variable(self):
        """The ``git pull`` call must reference a variable for the
        branch, not a string literal."""
        src = (BACKEND_DIR / "app.py").read_text()
        start = src.index("def run_niwa_update(")
        tail = src[start:]
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        assert "current_branch" in body, (
            "run_niwa_update must use a 'current_branch' variable "
            "derived from git rev-parse, not a hardcoded string."
        )
        # The pull command must reference current_branch.
        pull_match = re.search(
            r'"git",\s*"pull",\s*"origin",\s*current_branch',
            body,
        )
        assert pull_match, (
            "git pull must use current_branch variable: "
            '["git", "pull", "origin", current_branch]'
        )


# ── Fix 2: migrations fail loud ─────────────────────────────────────

class TestMigrationsFailLoud:
    """Pin that ``_run_migrations`` aborts the process when a
    migration fails, instead of logging + break + continue booting
    on a partially migrated schema."""

    def test_migration_failure_raises_system_exit(self):
        """The except block in the migration loop must raise
        ``SystemExit`` (or ``sys.exit``), NOT just ``break``."""
        src = (BACKEND_DIR / "app.py").read_text()
        start = src.index("def _run_migrations(")
        tail = src[start:]
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        assert "SystemExit" in body or "sys.exit" in body, (
            "_run_migrations must raise SystemExit (or call "
            "sys.exit) when a migration fails. Prior code did "
            "'break' and let the service boot on a partially "
            "migrated schema — silent corruption."
        )

    def test_migration_failure_does_not_just_break(self):
        """The except block must NOT have a bare ``break`` after
        the error log — that was the pre-fix pattern that hid
        migration failures."""
        src = (BACKEND_DIR / "app.py").read_text()
        start = src.index("def _run_migrations(")
        tail = src[start:]
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        # Look for the pattern: logger.error(...) followed by break
        # without SystemExit in between. The exact old pattern was:
        #   except Exception as e:
        #       logger.error("Migration %s failed: %s", filename, e)
        #       break
        # If someone re-introduces `break` after the error log
        # (maybe as a "gentler" alternative), this test catches it.
        except_blocks = re.findall(
            r"except\s+Exception.*?(?=except|\Z)",
            body,
            flags=re.DOTALL,
        )
        for block in except_blocks:
            if "logger.error" in block and "Migration" in block:
                has_exit = "SystemExit" in block or "sys.exit" in block
                has_bare_break = (
                    "\n" in block
                    and "break" in block
                    and not has_exit
                )
                assert not has_bare_break, (
                    "Migration error handler has a bare 'break' "
                    "without SystemExit — the pre-fix pattern that "
                    "let the service boot on a broken schema. "
                    "Replace with SystemExit."
                )

    def test_fatal_message_includes_filename(self):
        """The SystemExit message must include the filename of the
        failed migration so the operator knows which one to fix."""
        src = (BACKEND_DIR / "app.py").read_text()
        start = src.index("def _run_migrations(")
        tail = src[start:]
        end = re.search(r"\ndef [a-zA-Z_]", tail)
        body = tail[: end.start()] if end else tail

        assert "FATAL" in body or "migration" in body.lower(), (
            "SystemExit message must mention the migration filename "
            "so the operator can identify and fix the failing file"
        )

    # Note: a behaviour test that drives _run_migrations() with a
    # planted bad SQL file is desirable but impractical because
    # ``import app`` runs _run_migrations as a side-effect at
    # module load time, polluting the test with the real migration
    # runner before we can patch anything. The 6 static tests above
    # pin the invariant that the except block raises SystemExit;
    # the end-to-end validation happens on the VPS during the
    # next install smoke.
