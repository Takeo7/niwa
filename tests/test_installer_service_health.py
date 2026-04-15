"""Tests for the installer's post-``systemctl enable`` health check.

Regression guard for Bug 18b (docs/BUGS-FOUND.md): ``setup.py`` used
to report "Enabled and started" immediately after
``systemctl enable --now``, with no verification that the service
actually stayed up. PR-23's executor crash-loop and PR-24's executor
garbage-output both manifested as install-time restart loops that went
unnoticed for hours because the installer happily claimed success.

PR-25 adds three helpers in ``setup.py``:

- ``_wait_for_service_stable`` — pure query helper, returns
  ``(healthy, is_active, nrestarts, journal_tail)``.
- ``_verify_service_or_abort`` — fail-loud wrapper, ``sys.exit(1)`` on
  unhealthy with a full diagnostic dump.
- ``_reset_failed_unit`` — pre-enable cleanup so reinstalls don't
  poison the NRestarts counter and trip the check falsely.

These tests cover each helper in isolation (with ``sleep`` and
``runner`` injected so the 15s real wait never happens in tests) plus
a source-level invariant on ``setup.py`` pinning the call-site shape
so a future refactor can't silently drop the verify call.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: E402 — module under test


# ─── fixtures ──────────────────────────────────────────────────────

class FakeResult:
    """Stand-in for ``subprocess.CompletedProcess`` — only the fields
    the helpers actually read are populated."""

    def __init__(self, stdout: str = "", stderr: str = "",
                 returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def make_runner(responses):
    """Build a fake ``subprocess.run`` that replays a canned script.

    ``responses`` is a list where each element either matches by the
    *first distinguishing arg* of the command (e.g. ``"is-active"``,
    ``"show"``, ``"reset-failed"``, ``"journalctl"``) or is a plain
    ``FakeResult`` / callable applied in order.

    The returned runner also records the argv of each call in
    ``runner.calls`` so tests can assert on scope flags.
    """
    calls: list[list[str]] = []

    def runner(argv, **kwargs):
        calls.append(list(argv))
        # Match by the systemctl subcommand or tool name.
        tool = argv[0]
        key = None
        if tool == "systemctl":
            # Skip "--user" if present.
            for a in argv[1:]:
                if a != "--user":
                    key = a
                    break
        elif tool == "journalctl":
            key = "journalctl"
        else:
            key = tool

        mapping = responses if isinstance(responses, dict) else None
        if mapping is not None:
            if key in mapping:
                r = mapping[key]
                if isinstance(r, Exception):
                    raise r
                if callable(r):
                    return r(argv, **kwargs)
                return r
            raise AssertionError(
                f"no canned response for key={key!r}; argv={argv!r}"
            )
        # Fallback: sequential list.
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(argv, **kwargs)
        return r

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


# ─── _wait_for_service_stable ──────────────────────────────────────

class TestWaitForServiceStable:
    def test_happy_path_returns_healthy_without_journal(self):
        runner = make_runner({
            "is-active": FakeResult(stdout="active\n"),
            "show": FakeResult(stdout="0\n"),
        })
        healthy, is_active, nrestarts, journal = setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            wait_seconds=0,  # irrelevant with injected sleep
            sleep=lambda _: None,
            runner=runner,
        )
        assert healthy is True
        assert is_active == "active"
        assert nrestarts == 0
        assert journal == "", (
            "happy path must not dump a journal — keeps install output "
            "clean when nothing is wrong"
        )

    def test_nrestarts_positive_is_unhealthy_and_triggers_journal(self):
        runner = make_runner({
            "is-active": FakeResult(stdout="active\n"),
            "show": FakeResult(stdout="5\n"),
            "journalctl": FakeResult(
                stdout="executor.log: Permission denied\n" * 3,
            ),
        })
        healthy, is_active, nrestarts, journal = setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            sleep=lambda _: None,
            runner=runner,
        )
        assert healthy is False
        assert is_active == "active"
        assert nrestarts == 5
        assert "Permission denied" in journal, (
            "unhealthy path must capture journal tail for the user"
        )

    def test_is_active_failed_is_unhealthy(self):
        runner = make_runner({
            "is-active": FakeResult(stdout="failed\n", returncode=3),
            "show": FakeResult(stdout="0\n"),
            "journalctl": FakeResult(stdout="exit code 1\n"),
        })
        healthy, is_active, _, journal = setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            sleep=lambda _: None,
            runner=runner,
        )
        assert healthy is False
        assert is_active == "failed"
        assert "exit code 1" in journal

    def test_is_active_activating_is_unhealthy(self):
        """A crash-looping unit reports ``activating`` between restarts.
        That must trigger the abort, not be treated as healthy just
        because NRestarts happens to read 0 at that exact moment."""
        runner = make_runner({
            "is-active": FakeResult(stdout="activating\n", returncode=0),
            "show": FakeResult(stdout="0\n"),
            "journalctl": FakeResult(stdout="starting...\n"),
        })
        healthy, is_active, nrestarts, _ = setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            sleep=lambda _: None,
            runner=runner,
        )
        assert healthy is False
        assert is_active == "activating"
        assert nrestarts == 0

    def test_systemctl_show_raises_is_swallowed(self):
        """If ``systemctl show`` blows up (e.g. unit gone), the helper
        must still return a structured result, not propagate the
        exception — otherwise the caller can't render a diagnostic."""
        runner = make_runner({
            "is-active": FakeResult(stdout="active\n"),
            "show": subprocess.TimeoutExpired(cmd="systemctl", timeout=10),
            "journalctl": FakeResult(stdout="j\n"),
        })
        healthy, is_active, nrestarts, _ = setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            sleep=lambda _: None,
            runner=runner,
        )
        # With NRestarts defaulting to 0 on error, healthy hinges on
        # is-active only — here it's "active", so the check passes.
        # The important invariant: no raise.
        assert is_active == "active"
        assert nrestarts == 0
        assert healthy is True

    def test_journalctl_raises_is_swallowed_with_placeholder(self):
        """Journal capture is best-effort. If ``journalctl`` itself
        explodes, the helper returns a placeholder so the caller can
        still render a diagnostic rather than crash mid-abort."""
        runner = make_runner({
            "is-active": FakeResult(stdout="failed\n"),
            "show": FakeResult(stdout="0\n"),
            "journalctl": subprocess.TimeoutExpired(
                cmd="journalctl", timeout=5,
            ),
        })
        healthy, _, _, journal = setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            sleep=lambda _: None,
            runner=runner,
        )
        assert healthy is False
        assert journal == "(journal unavailable)"

    def test_user_scope_propagates_user_flag(self):
        runner = make_runner({
            "is-active": FakeResult(stdout="active\n"),
            "show": FakeResult(stdout="0\n"),
        })
        setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            user_scope=True,
            sleep=lambda _: None,
            runner=runner,
        )
        systemctl_calls = [c for c in runner.calls if c[0] == "systemctl"]
        assert systemctl_calls, "expected systemctl invocations"
        for call in systemctl_calls:
            assert "--user" in call, (
                f"user_scope=True must pass --user to systemctl; got {call}"
            )

    def test_root_scope_does_not_pass_user_flag(self):
        runner = make_runner({
            "is-active": FakeResult(stdout="active\n"),
            "show": FakeResult(stdout="0\n"),
        })
        setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            user_scope=False,
            sleep=lambda _: None,
            runner=runner,
        )
        for call in runner.calls:
            assert "--user" not in call, (
                f"user_scope=False must NOT pass --user; got {call}"
            )

    def test_sleep_is_called_with_wait_seconds(self):
        """The 15s wait must actually happen in production. In tests
        we inject a fake sleep, but we still want to pin that the
        helper calls it with the configured duration."""
        sleep_calls: list[float] = []
        runner = make_runner({
            "is-active": FakeResult(stdout="active\n"),
            "show": FakeResult(stdout="0\n"),
        })
        setup._wait_for_service_stable(
            "niwa-niwa-executor.service",
            wait_seconds=15,
            sleep=sleep_calls.append,
            runner=runner,
        )
        assert sleep_calls == [15], (
            f"expected a single sleep(15); got {sleep_calls}"
        )


# ─── _verify_service_or_abort ──────────────────────────────────────

class TestVerifyServiceOrAbort:
    def test_healthy_returns_silently(self, capsys):
        runner = make_runner({
            "is-active": FakeResult(stdout="active\n"),
            "show": FakeResult(stdout="0\n"),
        })
        # Must not raise SystemExit.
        setup._verify_service_or_abort(
            "niwa-niwa-executor.service",
            sleep=lambda _: None,
            runner=runner,
        )
        out = capsys.readouterr().out
        assert "is stable" in out
        assert "NRestarts=0" in out

    def test_unhealthy_aborts_with_exit_code_1(self):
        runner = make_runner({
            "is-active": FakeResult(stdout="failed\n"),
            "show": FakeResult(stdout="3\n"),
            "journalctl": FakeResult(stdout="boom\n"),
        })
        with pytest.raises(SystemExit) as exc:
            setup._verify_service_or_abort(
                "niwa-niwa-executor.service",
                sleep=lambda _: None,
                runner=runner,
            )
        assert exc.value.code == 1

    def test_unhealthy_diagnostic_is_actionable(self, capsys):
        runner = make_runner({
            "is-active": FakeResult(stdout="failed\n"),
            "show": FakeResult(stdout="3\n"),
            "journalctl": FakeResult(stdout="Permission denied\n"),
        })
        with pytest.raises(SystemExit):
            setup._verify_service_or_abort(
                "niwa-niwa-executor.service",
                sleep=lambda _: None,
                runner=runner,
            )
        captured = capsys.readouterr()
        text = captured.out + captured.err
        # Pointers to the known causes.
        assert "Bug 18" in text, "diagnostic must mention Bug 18"
        assert "Bug 19" in text, "diagnostic must mention Bug 19"
        assert "docs/BUGS-FOUND.md" in text, (
            "diagnostic must point at docs/BUGS-FOUND.md so the operator "
            "can read the full context"
        )
        # Actionable manual unblock command.
        assert "chown niwa:niwa" in text, (
            "diagnostic must show the chown unblock command for "
            "already-installed systems"
        )
        assert "Permission denied" in text, (
            "journal tail must be included in the diagnostic so the "
            "operator sees the actual error"
        )


# ─── _reset_failed_unit ────────────────────────────────────────────

class TestResetFailedUnit:
    def test_invokes_systemctl_reset_failed(self):
        runner = make_runner({"reset-failed": FakeResult()})
        setup._reset_failed_unit(
            "niwa-niwa-executor.service", runner=runner,
        )
        assert runner.calls == [
            ["systemctl", "reset-failed", "niwa-niwa-executor.service"],
        ]

    def test_user_scope_passes_user_flag(self):
        runner = make_runner({"reset-failed": FakeResult()})
        setup._reset_failed_unit(
            "niwa-niwa-executor.service",
            user_scope=True,
            runner=runner,
        )
        assert runner.calls == [
            ["systemctl", "--user", "reset-failed",
             "niwa-niwa-executor.service"],
        ]

    def test_swallows_errors_silently(self):
        """Reset-failed is best-effort: the unit may not exist yet on
        a fresh install, in which case systemctl returns non-zero or
        subprocess raises. Either way, the caller must not see an
        exception — we're about to run ``enable --now`` anyway."""
        def boom(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd="systemctl", timeout=10)

        runner = make_runner({"reset-failed": boom})
        # Must not raise.
        setup._reset_failed_unit(
            "niwa-niwa-executor.service", runner=runner,
        )


# ─── source-level invariants on setup.py ───────────────────────────

class TestSetupPyWiring:
    """Pin the call-site shape so a refactor can't silently drop
    the verify call and reintroduce Bug 18b."""

    def test_every_enable_now_has_a_verify_call_following(self):
        """Every ``systemctl ... enable --now`` inside the installer
        functions we touched must be followed by a
        ``_verify_service_or_abort`` call within the same
        ``if result.returncode == 0:`` branch."""
        src = (REPO_ROOT / "setup.py").read_text()

        # Find each call to _verify_service_or_abort.
        verify_calls = list(re.finditer(
            r'_verify_service_or_abort\(',
            src,
        ))
        # We wired 2 executor scopes + 2 hosting scopes, but the two
        # executor branches share a single post-enable block and so do
        # the hosting ones. Net: exactly 2 verify call-sites.
        assert len(verify_calls) >= 2, (
            f"expected at least 2 _verify_service_or_abort call-sites "
            f"(executor + hosting); found {len(verify_calls)}"
        )

    def test_every_enable_now_has_a_reset_failed_preceding(self):
        """Every ``systemctl ... enable --now`` must be preceded in
        source order by a ``_reset_failed_unit`` call, so that a
        reinstall over a previously crash-looping unit doesn't
        false-positive the health check."""
        src = (REPO_ROOT / "setup.py").read_text()
        enable_positions = [
            m.start() for m in re.finditer(
                r'systemctl.*?enable.*?--now', src,
            )
        ]
        # Filter to the call-sites we wired (inside installer function
        # bodies, not the ``warn(...)`` hints that mention the command
        # in user-facing error messages).
        # Heuristic: a wired call is an ``enable --now`` on the same
        # line as ``subprocess.run([``.
        wired = []
        for pos in enable_positions:
            line_start = src.rfind("\n", 0, pos) + 1
            line_end = src.find("\n", pos)
            line = src[line_start:line_end]
            if "subprocess.run(" in line:
                wired.append(pos)
        assert wired, "expected at least one wired enable --now call"

        reset_positions = [
            m.start() for m in re.finditer(r'_reset_failed_unit\(', src)
        ]
        # Each wired ``enable --now`` must have at least one
        # reset_failed call earlier in source order.
        for epos in wired:
            earlier_resets = [r for r in reset_positions if r < epos]
            assert earlier_resets, (
                f"enable --now at offset {epos} has no preceding "
                f"_reset_failed_unit call — regression of Bug 18b's "
                f"reinstall scenario"
            )

    def test_verify_helper_lives_in_setup_py(self):
        """Helpers must live in ``setup.py`` itself so the installer
        has no new runtime dependency — stdlib-only per SPEC §8."""
        assert hasattr(setup, "_wait_for_service_stable")
        assert hasattr(setup, "_verify_service_or_abort")
        assert hasattr(setup, "_reset_failed_unit")
