"""Tests for FIX-20260419 — probe_claude_cli in health_service.

Covers the four observable states the MVP surfaces in AuthPanel:
  - ``ok``: binary emits at least one informative event.
  - ``no_cli``: binary not found / not executable.
  - ``credential_missing``: binary responds empty AND there is no
    credential configured in settings.
  - ``credential_expired``: binary responds empty AND a credential
    IS configured in settings (i.e. the user thinks they're
    authenticated but the CLI disagrees).

The adapter-level fix (tests/test_claude_adapter_empty_stream.py)
routes individual tasks to waiting_input; this probe lets the UI
warn the user BEFORE they run a task.

Tests spawn real subprocesses against hermetic fake binaries
(tests/fixtures/fake_claude_probe_*.py) so no network and no real
``claude`` CLI is required.

Run: pytest tests/test_readiness_probe.py -v
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FIXTURES_DIR = os.path.join(ROOT_DIR, "tests", "fixtures")


def _shim(tmp_path: str, name: str, target: str) -> str:
    """Install a ``<tmp_path>/<name>`` shell shim that execs *target*.

    Lets the probe find ``claude`` on PATH pointing at our fake.
    """
    shim_path = os.path.join(tmp_path, name)
    with open(shim_path, "w", encoding="utf-8") as f:
        f.write(f"#!/bin/sh\nexec {sys.executable} {target} \"$@\"\n")
    os.chmod(
        shim_path,
        os.stat(shim_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH,
    )
    return shim_path


@pytest.fixture
def clean_probe(monkeypatch):
    """Reset the module-level probe cache between tests."""
    import health_service
    monkeypatch.setattr(health_service, "_CLAUDE_PROBE_CACHE",
                        {"value": None, "at": 0.0}, raising=False)
    monkeypatch.delenv("NIWA_LLM_COMMAND", raising=False)
    yield


def test_probe_ok_when_cli_emits_events(tmp_path, monkeypatch, clean_probe):
    """Fake CLI that emits ``system_init`` + ``result`` → status=ok."""
    import health_service
    shim = _shim(
        str(tmp_path), "claude",
        os.path.join(FIXTURES_DIR, "fake_claude_probe_ok.py"),
    )
    monkeypatch.setenv("NIWA_LLM_COMMAND", shim)
    result = health_service.probe_claude_cli(timeout=10.0)
    assert result["status"] == "ok", result
    assert result.get("checked_at")


def test_probe_no_cli_when_binary_missing(tmp_path, monkeypatch, clean_probe):
    """NIWA_LLM_COMMAND points at a path that does not exist → no_cli."""
    import health_service
    missing = os.path.join(str(tmp_path), "does-not-exist")
    monkeypatch.setenv("NIWA_LLM_COMMAND", missing)
    # Also clear PATH so shutil.which("claude") can't find a real one.
    monkeypatch.setenv("PATH", str(tmp_path))
    result = health_service.probe_claude_cli(timeout=5.0)
    assert result["status"] == "no_cli", result


def test_probe_credential_missing_when_empty_and_no_credential(
    tmp_path, monkeypatch, clean_probe,
):
    """Empty-stream CLI + no credential configured → credential_missing.

    Verified through ``classify_claude_probe``: the raw probe returns
    ``credential_error``; the classifier matches it against
    ``has_credential=False`` and escalates to ``credential_missing``."""
    import health_service
    shim = _shim(
        str(tmp_path), "claude",
        os.path.join(FIXTURES_DIR, "fake_claude_probe_empty.py"),
    )
    monkeypatch.setenv("NIWA_LLM_COMMAND", shim)
    raw = health_service.probe_claude_cli(timeout=10.0)
    assert raw["status"] == "credential_error"
    classified = health_service.classify_claude_probe(
        raw, has_credential=False,
    )
    assert classified["status"] == "credential_missing"


def test_probe_credential_expired_when_empty_and_has_credential(
    tmp_path, monkeypatch, clean_probe,
):
    """Empty-stream CLI + credential configured → credential_expired."""
    import health_service
    shim = _shim(
        str(tmp_path), "claude",
        os.path.join(FIXTURES_DIR, "fake_claude_probe_empty.py"),
    )
    monkeypatch.setenv("NIWA_LLM_COMMAND", shim)
    raw = health_service.probe_claude_cli(timeout=10.0)
    assert raw["status"] == "credential_error"
    classified = health_service.classify_claude_probe(
        raw, has_credential=True,
    )
    assert classified["status"] == "credential_expired"


def test_probe_cache_hits_within_ttl(tmp_path, monkeypatch, clean_probe):
    """The probe is a subprocess spawn — cache the result inside the
    TTL window so repeated ``/api/readiness`` polls don't fork a
    subprocess every time."""
    import health_service
    shim = _shim(
        str(tmp_path), "claude",
        os.path.join(FIXTURES_DIR, "fake_claude_probe_ok.py"),
    )
    monkeypatch.setenv("NIWA_LLM_COMMAND", shim)
    calls = []
    real_run = health_service.subprocess.run

    def _spy(*a, **kw):
        calls.append(1)
        return real_run(*a, **kw)

    monkeypatch.setattr(health_service.subprocess, "run", _spy)
    a = health_service.probe_claude_cli(timeout=10.0)
    b = health_service.probe_claude_cli(timeout=10.0)
    assert a["status"] == b["status"] == "ok"
    assert len(calls) == 1, f"cache miss — fork count={len(calls)}"


def test_probe_cache_bypass_on_force(tmp_path, monkeypatch, clean_probe):
    """Passing ``force=True`` refreshes the cached value — lets an
    operator click a 'Refresh' button without waiting 30 s."""
    import health_service
    shim = _shim(
        str(tmp_path), "claude",
        os.path.join(FIXTURES_DIR, "fake_claude_probe_ok.py"),
    )
    monkeypatch.setenv("NIWA_LLM_COMMAND", shim)
    calls = []
    real_run = health_service.subprocess.run

    def _spy(*a, **kw):
        calls.append(1)
        return real_run(*a, **kw)

    monkeypatch.setattr(health_service.subprocess, "run", _spy)
    health_service.probe_claude_cli(timeout=10.0)
    health_service.probe_claude_cli(timeout=10.0, force=True)
    assert len(calls) == 2, f"force did not bypass cache — {len(calls)}"
