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

from app.services.github_pulls import collapse_check_state


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
    monkeypatch: pytest.MonkeyPatch,
    payload: list[dict[str, Any]] | str,
    rc: int = 0,
    stderr: str = "",
) -> list[list[str]]:
    calls: list[list[str]] = []
    stdout = payload if isinstance(payload, str) else json.dumps(payload)

    def fake_run(args, *a, **kw):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, rc, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("app.services.github_pulls.subprocess.run", fake_run)
    return calls


def _stub_gh_raises(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    def fake_run(*a, **kw):
        raise exc

    monkeypatch.setattr("app.services.github_pulls.subprocess.run", fake_run)


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
    # Wire contract: snake_case fields, `checks.state` collapsed.
    sample = body["pulls"][0]
    assert "head_ref_name" in sample and "headRefName" not in sample
    assert "created_at" in sample and "createdAt" not in sample
    assert sample["checks"] == {"state": "none"}
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


def test_list_pulls_returns_warning_when_remote_not_github(client) -> None:
    # Non-github remote (gitlab, self-hosted) parses to None → 200 +
    # ``invalid_remote``; never shells out.
    payload = {
        **PROJECT_PAYLOAD,
        "git_remote": "git@gitlab.example.com:owner/repo.git",
    }
    assert client.post("/api/projects", json=payload).status_code == 201

    response = client.get("/api/projects/demo/pulls")
    assert response.status_code == 200, response.text
    assert response.json() == {"warning": "invalid_remote", "pulls": []}


def test_list_pulls_returns_503_when_gh_missing(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {**PROJECT_PAYLOAD, "git_remote": "https://github.com/owner/repo.git"}
    assert client.post("/api/projects", json=payload).status_code == 201

    _gh_installed(monkeypatch, installed=False)

    response = client.get("/api/projects/demo/pulls")
    assert response.status_code == 503, response.text
    assert response.json() == {"error": "gh_missing"}


def test_list_pulls_returns_502_when_gh_exits_nonzero(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {**PROJECT_PAYLOAD, "git_remote": "https://github.com/owner/repo.git"}
    assert client.post("/api/projects", json=payload).status_code == 201
    _gh_installed(monkeypatch)
    _stub_gh(monkeypatch, [], rc=1, stderr="auth required")

    response = client.get("/api/projects/demo/pulls")
    assert response.status_code == 502, response.text
    body = response.json()
    assert body["error"] == "gh_failed"
    assert "auth required" in body["detail"]


def test_list_pulls_returns_502_when_gh_returns_non_json(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {**PROJECT_PAYLOAD, "git_remote": "https://github.com/owner/repo.git"}
    assert client.post("/api/projects", json=payload).status_code == 201
    _gh_installed(monkeypatch)
    _stub_gh(monkeypatch, "not actually json", rc=0)

    response = client.get("/api/projects/demo/pulls")
    assert response.status_code == 502, response.text
    body = response.json()
    assert body["error"] == "gh_failed"
    assert "non-JSON" in body["detail"]


def test_list_pulls_returns_504_when_gh_times_out(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {**PROJECT_PAYLOAD, "git_remote": "https://github.com/owner/repo.git"}
    assert client.post("/api/projects", json=payload).status_code == 201
    _gh_installed(monkeypatch)
    _stub_gh_raises(
        monkeypatch, subprocess.TimeoutExpired(cmd="gh pr list", timeout=15),
    )

    response = client.get("/api/projects/demo/pulls")
    assert response.status_code == 504, response.text
    body = response.json()
    assert body["error"] == "gh_timeout"


@pytest.mark.parametrize(
    "rollup, expected",
    [
        ([], "none"),
        (None, "none"),
        (
            [
                {"conclusion": "SUCCESS", "status": "COMPLETED"},
                {"conclusion": "SUCCESS", "status": "COMPLETED"},
            ],
            "passing",
        ),
        (
            [
                {"conclusion": "SUCCESS", "status": "COMPLETED"},
                {"conclusion": "FAILURE", "status": "COMPLETED"},
            ],
            "failing",
        ),
        (
            [
                {"conclusion": "SUCCESS", "status": "COMPLETED"},
                {"conclusion": None, "status": "IN_PROGRESS"},
            ],
            "pending",
        ),
    ],
    ids=["empty", "none-payload", "all-passing", "one-failing", "mix-pending"],
)
def test_collapse_check_state_priority(rollup: Any, expected: str) -> None:
    assert collapse_check_state(rollup) == expected
