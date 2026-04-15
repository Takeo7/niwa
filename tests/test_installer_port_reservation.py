"""Tests for the installer's port reservation logic (PR-28, Bug 22).

Regression guard for **Bug 22** (docs/BUGS-FOUND.md): when the install
wizard picks four ports in sequence (gateway streaming, gateway SSE,
caddy, app), ``_quick_free_port`` used to consult only the operating
system via ``detect_port_free``. The OS check reports a port as free
if nothing is currently bound to it — but a port the wizard already
*assigned* to an earlier service in the same session has not yet
been bound by anyone. So when the default port of the first service
was occupied (e.g. an orphan container from a previous install),
the wizard would:

  1. Call ``_quick_free_port(18810)`` → occupied → scan offsets →
     return 18811 → assign to gateway streaming.
  2. Later call ``_quick_free_port(18811)`` for caddy → the kernel
     still reports 18811 free (gateway hasn't bound yet) → return
     18811 → caddy now collides with gateway on first start.

The fix threads a shared ``reserved: set[int]`` through every call,
so ``_quick_free_port`` skips ports the wizard already allocated
regardless of what the OS thinks.

These tests exercise the pure helper with a fake ``detect_port_free``
so they run without touching any real port.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import setup  # noqa: E402 — module under test


class TestQuickFreePortReservationSemantics:
    """Unit tests for the ``reserved`` parameter."""

    def test_default_returned_when_free_and_not_reserved(self, monkeypatch):
        """Happy path: nothing occupies the port, nothing is
        reserved, ``_quick_free_port`` returns the default."""
        monkeypatch.setattr(setup, "detect_port_free", lambda p: True)
        assert setup._quick_free_port(18810, set()) == 18810

    def test_default_skipped_when_already_reserved(self, monkeypatch):
        """If an earlier call in the same wizard session reserved
        the default, ``_quick_free_port`` must not return it —
        even if the OS reports it free."""
        monkeypatch.setattr(setup, "detect_port_free", lambda p: True)
        got = setup._quick_free_port(18810, {18810})
        assert got == 18811, (
            f"expected offset +1 when default is in the reserved "
            f"set, got {got}"
        )

    def test_offset_skips_reserved_candidates(self, monkeypatch):
        """If multiple candidates are reserved, skip them all."""
        monkeypatch.setattr(setup, "detect_port_free", lambda p: True)
        got = setup._quick_free_port(18810, {18810, 18811, 18812})
        assert got == 18813

    def test_reserved_takes_precedence_over_os_free(self, monkeypatch):
        """The OS might still say a port is free (nobody's bound
        it yet) but if the wizard reserved it, that wins. This is
        the actual Bug 22 scenario — the earlier call assigned it
        but didn't bind."""
        calls = []

        def fake_detect(port):
            calls.append(port)
            return True  # always "free" at OS level

        monkeypatch.setattr(setup, "detect_port_free", fake_detect)
        got = setup._quick_free_port(18811, {18811})
        assert got == 18812
        # detect_port_free should NOT have been invoked for 18811
        # since the reserved-check short-circuits first.
        assert 18811 not in calls, (
            "_quick_free_port asked the OS about a port that was "
            "explicitly reserved — that defeats the fix"
        )

    def test_os_busy_short_circuits_even_if_not_reserved(self, monkeypatch):
        """Conversely, an OS-busy port (real collision with an
        existing process) must still be skipped even if not in
        reserved."""
        monkeypatch.setattr(
            setup, "detect_port_free", lambda p: p != 18810,
        )
        got = setup._quick_free_port(18810, set())
        assert got == 18811

    def test_both_reserved_and_os_busy_combined(self, monkeypatch):
        """18810 reserved, 18811 OS-busy, 18812 free → returns 18812."""
        monkeypatch.setattr(
            setup, "detect_port_free", lambda p: p not in (18811,),
        )
        got = setup._quick_free_port(18810, {18810})
        assert got == 18812

    def test_none_reserved_defaults_to_empty_set(self, monkeypatch):
        """Backwards-compat: ``reserved=None`` and no second arg
        behave the same as an empty reserved set."""
        monkeypatch.setattr(setup, "detect_port_free", lambda p: True)
        assert setup._quick_free_port(18810) == 18810
        assert setup._quick_free_port(18810, None) == 18810

    def test_reserved_not_mutated(self, monkeypatch):
        """``_quick_free_port`` must not mutate the ``reserved`` set
        it receives — the caller owns the lifecycle. If the helper
        added its own return value to ``reserved`` internally, a
        caller that did ``reserved.add(got)`` would see duplicate
        book-keeping but more importantly we'd be obscuring whose
        responsibility the set is."""
        monkeypatch.setattr(setup, "detect_port_free", lambda p: True)
        reserved = {18810}
        before = set(reserved)
        setup._quick_free_port(18810, reserved)
        assert reserved == before, (
            "_quick_free_port mutated the reserved set — the caller "
            "owns it"
        )


class TestBug22RegressionScenario:
    """End-to-end repro of the exact sequence the wizard runs. The
    bug was: gateway and caddy both land on the same offset when the
    default port of the first one is occupied."""

    def test_full_four_port_sequence_with_first_default_busy(self, monkeypatch):
        """Reproduce the VPS failure: 18810 busy (orphan docker
        container), wizard picks ports in order. Without the fix,
        caddy (default 18811) collides with gateway_streaming
        (auto-bumped to 18811). With the fix, all four are
        distinct."""
        busy_at_os_level = {18810}
        monkeypatch.setattr(
            setup, "detect_port_free",
            lambda p: p not in busy_at_os_level,
        )

        reserved: set = set()

        gateway = setup._quick_free_port(18810, reserved)
        reserved.add(gateway)
        sse = setup._quick_free_port(18812, reserved)
        reserved.add(sse)
        caddy = setup._quick_free_port(18811, reserved)
        reserved.add(caddy)
        app = setup._quick_free_port(8080, reserved)
        reserved.add(app)

        picked = [gateway, sse, caddy, app]
        assert len(set(picked)) == 4, (
            f"four ports must be distinct, got {picked} (duplicates "
            f"indicate the reservation logic is broken — the very "
            f"bug we're regressing against)"
        )
        # Specifically: gateway and caddy must not collide even
        # though caddy's default of 18811 was what gateway auto-
        # bumped to.
        assert gateway != caddy, (
            f"gateway={gateway} and caddy={caddy} both picked the "
            f"same port — Bug 22 reproduced"
        )


class TestCallSitesUseReservedSet:
    """Static regex guard: ``build_quick_config`` (the wizard) must
    thread a reserved set through every ``_quick_free_port`` call.
    Pins the invariant against future copy-paste that forgets."""

    def test_every_wizard_quick_free_port_call_passes_reserved(self):
        import re

        src = (REPO_ROOT / "setup.py").read_text()
        # Extract the body of build_quick_config so we only scan
        # the wizard's port-allocation block, not any other callers
        # (the helper itself still has the `reserved=None` default
        # for backwards-compat and may be called with one arg in
        # other contexts, e.g. advanced-mode prompts).
        start = src.index("def build_quick_config(")
        tail = src[start:]
        end = re.search(r"\n(?=def [a-zA-Z_])", tail)
        body = tail[: end.start() + 1] if end else tail

        # Every call inside the wizard must supply the reserved set.
        calls = re.findall(r"_quick_free_port\((.+?)\)", body)
        assert calls, (
            "expected _quick_free_port calls in build_quick_config "
            "— the regex drifted or the wizard was refactored"
        )
        for call_args in calls:
            assert "_reserved_ports" in call_args or "reserved" in call_args, (
                f"_quick_free_port call in build_quick_config does "
                f"not pass a reserved set: args=({call_args}). "
                f"Without the second arg the Bug 22 race reopens."
            )
