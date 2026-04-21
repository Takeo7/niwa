"""HTTP tests for ``GET /api/readiness`` (PR-V1-18)."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest


def _stub_which(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str | None]) -> None:
    monkeypatch.setattr(
        "app.services.readiness_checks.shutil.which",
        lambda name: mapping.get(name),
    )


def _stub_git_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, *_a: Any, **_k: Any):  # type: ignore[no-untyped-def]
        assert cmd[:2] == ["git", "--version"]
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout="git version 2.43.0", stderr=""
        )

    monkeypatch.setattr("app.services.readiness_checks.subprocess.run", fake_run)


def test_all_checks_ok(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_which(monkeypatch, {"claude": "/usr/local/bin/claude", "gh": "/usr/local/bin/gh"})
    _stub_git_version(monkeypatch)

    body = client.get("/api/readiness").json()
    assert body["db_ok"] and body["claude_cli_ok"] and body["git_ok"] and body["gh_ok"]
    d = body["details"]
    assert d["claude_cli"] == {"path": "/usr/local/bin/claude", "found": True}
    assert d["git"]["version"].startswith("git version")
    assert d["gh"]["found"] is True
    assert d["db"]["reachable"] is True


def test_claude_cli_missing(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_which(monkeypatch, {"gh": "/usr/local/bin/gh"})
    _stub_git_version(monkeypatch)

    body = client.get("/api/readiness").json()
    assert body["claude_cli_ok"] is False
    assert body["details"]["claude_cli"] == {"path": None, "found": False}


def test_gh_missing_hints_install(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_which(monkeypatch, {"claude": "/usr/local/bin/claude"})
    _stub_git_version(monkeypatch)

    body = client.get("/api/readiness").json()
    assert body["gh_ok"] is False
    assert body["details"]["gh"]["found"] is False
    assert "github.com/cli/cli" in body["details"]["gh"]["hint"]


def test_git_exception_captured(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_which(monkeypatch, {"claude": "/usr/local/bin/claude", "gh": "/usr/local/bin/gh"})

    def boom(*_a: Any, **_k: Any):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("git not found")

    monkeypatch.setattr("app.services.readiness_checks.subprocess.run", boom)
    body = client.get("/api/readiness").json()
    assert body["git_ok"] is False
    assert body["details"]["git"].get("error")


def test_db_unreachable_returns_false(client, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_which(monkeypatch, {"claude": "/usr/local/bin/claude", "gh": "/usr/local/bin/gh"})
    _stub_git_version(monkeypatch)

    # Patch the helper so the endpoint composition path is exercised without
    # having to wire a broken session through the DI override.
    from app.services import readiness_checks as svc

    monkeypatch.setattr(
        svc,
        "check_db_via_session",
        lambda _session: (False, {"reachable": False, "error": "synthetic failure"}),
    )
    body = client.get("/api/readiness").json()
    assert body["db_ok"] is False
    assert body["details"]["db"]["reachable"] is False
    assert "synthetic failure" in body["details"]["db"]["error"]


def test_check_db_via_session_catches_exception() -> None:
    """Unit test: exercise the real ``except`` branch of ``check_db_via_session``."""

    from sqlalchemy.exc import OperationalError

    from app.services.readiness_checks import check_db_via_session

    class _BoomSession:
        def execute(self, *_a: Any, **_k: Any):  # type: ignore[no-untyped-def]
            raise OperationalError("SELECT 1", {}, Exception("boom"))

    ok, details = check_db_via_session(_BoomSession())  # type: ignore[arg-type]
    assert ok is False
    assert details["reachable"] is False
    assert "error" in details
    assert "boom" in details["error"]
