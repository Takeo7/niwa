"""Tests for ``app.services.github_pulls`` + ``GET /api/projects/{slug}/pulls``.

All cases stub ``subprocess.run`` + ``shutil.which`` via monkeypatch so
no real ``gh`` ever executes — the service shells out to the CLI and we
want fast, hermetic tests.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest


PROJECT_PAYLOAD: dict[str, Any] = {
    "slug": "demo", "name": "Demo", "kind": "library", "local_path": "/tmp/demo",
}


def _gh_installed(monkeypatch: pytest.MonkeyPatch, installed: bool = True) -> None:
    path = "/usr/bin/gh" if installed else None
    monkeypatch.setattr(
        "app.services.github_pulls.shutil.which",
        lambda name: path if name == "gh" else None,
    )


def _stub_gh(
    monkeypatch: pytest.MonkeyPatch, payload: list[dict[str, Any]], rc: int = 0
) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(args, *a, **kw):
        calls.append(list(args))
        return subprocess.CompletedProcess(
            args, rc, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr("app.services.github_pulls.subprocess.run", fake_run)
    return calls


def _pr(num: int, head: str, state: str = "OPEN") -> dict[str, Any]:
    return {
        "number": num, "title": f"T{num}", "state": state, "url": f"u{num}",
        "mergeable": "MERGEABLE", "statusCheckRollup": [],
        "createdAt": "2026-04-26T00:00:00Z", "updatedAt": "2026-04-26T00:00:00Z",
        "headRefName": head,
    }


def test_list_pulls_filters_to_niwa_branches(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {**PROJECT_PAYLOAD, "git_remote": "git@github.com:owner/repo.git"}
    assert client.post("/api/projects", json=payload).status_code == 201

    _gh_installed(monkeypatch)
    pulls = [
        _pr(1, "niwa/task-1-foo"),
        _pr(2, "feature/x"),
        _pr(3, "niwa/task-2-bar"),
        _pr(4, "bugfix/y", state="CLOSED"),
        _pr(5, "niwa/task-3-baz"),
    ]
    calls = _stub_gh(monkeypatch, pulls)

    response = client.get("/api/projects/demo/pulls")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["pulls"]) == 3
    assert {p["number"] for p in body["pulls"]} == {1, 3, 5}
    # gh was invoked once with --repo owner/repo.
    assert len(calls) == 1
    argv = calls[0]
    assert argv[:3] == ["gh", "pr", "list"]
    assert "--repo" in argv and "owner/repo" in argv


def test_list_pulls_returns_warning_when_no_remote(client) -> None:
    # `git_remote` defaults to NULL → endpoint must short-circuit.
    assert client.post("/api/projects", json=PROJECT_PAYLOAD).status_code == 201

    response = client.get("/api/projects/demo/pulls")
    assert response.status_code == 200, response.text
    assert response.json() == {"warning": "no_remote", "pulls": []}


def test_list_pulls_returns_503_when_gh_missing(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {**PROJECT_PAYLOAD, "git_remote": "https://github.com/owner/repo.git"}
    assert client.post("/api/projects", json=payload).status_code == 201

    _gh_installed(monkeypatch, installed=False)

    response = client.get("/api/projects/demo/pulls")
    assert response.status_code == 503, response.text
    assert response.json() == {"error": "gh_missing"}
