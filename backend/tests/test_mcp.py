"""Tests for Phase 7 MCP server — auth, tools/list, project/task tools."""

from __future__ import annotations

import os

import pytest


PROJECT_PAYLOAD = {
    "slug": "demo",
    "name": "Demo",
    "kind": "web-deployable",
    "local_path": "/tmp/demo",
}

_RPC = {"jsonrpc": "2.0", "id": 1}


def _call(client, method: str, params: dict = {}, *, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/api/mcp",
        json={**_RPC, "method": method, "params": params},
        headers=headers,
    ).json()


# ── Auth ───────────────────────────────────────────────────────────────────────


def test_ping_requires_no_auth(client) -> None:
    resp = _call(client, "ping")
    assert resp["result"]["pong"] is True
    assert "version" in resp["result"]


def test_project_list_requires_token(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIWA_MCP_TOKEN", raising=False)
    resp = _call(client, "project_list")
    assert "error" in resp
    assert resp["error"]["code"] == -32001


def test_env_token_grants_all_scopes(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "secret-test-token")
    resp = _call(client, "project_list", token="secret-test-token")
    assert "result" in resp


def test_invalid_token_returns_error(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIWA_MCP_TOKEN", raising=False)
    resp = _call(client, "project_list", token="niwa_badtoken")
    assert "error" in resp


def test_db_token_with_read_scope(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIWA_MCP_TOKEN", raising=False)
    from app.api.deps import get_session
    from app.auth.token_store import create_token
    db = next(client.app.dependency_overrides[get_session]())
    raw, _ = create_token(db, "test", ["read"])
    resp = _call(client, "project_list", token=raw)
    assert "result" in resp


def test_token_without_write_scope_denied(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIWA_MCP_TOKEN", raising=False)
    from app.api.deps import get_session
    from app.auth.token_store import create_token
    db = next(client.app.dependency_overrides[get_session]())
    raw, _ = create_token(db, "readonly", ["read"])
    resp = _call(client, "task_create",
                 {"project_slug": "demo", "title": "t"},
                 token=raw)
    assert "error" in resp
    assert "403" in str(resp["error"]["code"]) or "task:create" in resp["error"]["message"]


# ── tools/list ─────────────────────────────────────────────────────────────────


def test_tools_list(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "tools/list", token="tok")
    names = [t["name"] for t in resp["result"]["tools"]]
    assert "ping" in names
    assert "project_list" in names
    assert "task_create" in names
    assert "task_respond" in names


# ── project tools ─────────────────────────────────────────────────────────────


def test_project_list_empty(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "project_list", token="tok")
    assert resp["result"] == []


def test_project_create_and_get_via_mcp(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    client.post("/api/projects", json=PROJECT_PAYLOAD)
    resp = _call(client, "project_get", {"slug": "demo"}, token="tok")
    assert resp["result"]["slug"] == "demo"
    assert resp["result"]["name"] == "Demo"


def test_project_get_not_found(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "project_get", {"slug": "nope"}, token="tok")
    assert "error" in resp
    assert "not found" in resp["error"]["message"].lower()


# ── task tools ─────────────────────────────────────────────────────────────────


def test_task_create_and_status(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    client.post("/api/projects", json=PROJECT_PAYLOAD)

    resp = _call(client, "task_create",
                 {"project_slug": "demo", "title": "Fix bug", "description": "desc"},
                 token="tok")
    assert resp["result"]["title"] == "Fix bug"
    task_id = resp["result"]["id"]

    status_resp = _call(client, "task_status", {"task_id": task_id}, token="tok")
    assert status_resp["result"]["id"] == task_id
    assert status_resp["result"]["status"] in ("queued", "inbox")


def test_task_list_for_project(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    client.post("/api/projects", json=PROJECT_PAYLOAD)
    _call(client, "task_create", {"project_slug": "demo", "title": "T1"}, token="tok")
    _call(client, "task_create", {"project_slug": "demo", "title": "T2"}, token="tok")

    resp = _call(client, "task_list", {"project_slug": "demo"}, token="tok")
    assert len(resp["result"]) == 2


def test_task_cancel(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    client.post("/api/projects", json=PROJECT_PAYLOAD)
    resp = _call(client, "task_create", {"project_slug": "demo", "title": "Cancel me"}, token="tok")
    task_id = resp["result"]["id"]

    cancel = _call(client, "task_cancel", {"task_id": task_id}, token="tok")
    assert cancel["result"]["status"] == "cancelled"


def test_task_retry_after_cancel(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    client.post("/api/projects", json=PROJECT_PAYLOAD)
    resp = _call(client, "task_create", {"project_slug": "demo", "title": "Retry me"}, token="tok")
    task_id = resp["result"]["id"]
    _call(client, "task_cancel", {"task_id": task_id}, token="tok")

    retry = _call(client, "task_retry", {"task_id": task_id}, token="tok")
    assert retry["result"]["status"] == "queued"


# ── pull tools (MCP-10/11) ─────────────────────────────────────────────────────


def test_pull_list_includes_in_tools_list(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "tools/list", token="tok")
    names = {t["name"] for t in resp["result"]["tools"]}
    assert "pull_list" in names
    assert "pull_merge" in names


def test_pull_list_requires_git_remote(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    client.post("/api/projects", json=PROJECT_PAYLOAD)  # no git_remote
    resp = _call(client, "pull_list", {"project_slug": "demo"}, token="tok")
    assert "error" in resp
    assert "git_remote" in resp["error"]["message"].lower()


def test_pull_list_404_when_project_missing(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "pull_list", {"project_slug": "ghost"}, token="tok")
    assert "error" in resp
    assert "not found" in resp["error"]["message"].lower()


def test_pull_merge_requires_merge_scope(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NIWA_MCP_TOKEN", raising=False)
    from app.api.deps import get_session
    from app.auth.token_store import create_token
    db = next(client.app.dependency_overrides[get_session]())
    raw, _ = create_token(db, "noscope", ["read"])  # no merge scope
    client.post("/api/projects", json=PROJECT_PAYLOAD)
    resp = _call(client, "pull_merge",
                 {"project_slug": "demo", "number": 1}, token=raw)
    assert "error" in resp
    assert "merge" in resp["error"]["message"].lower()


def test_unknown_method_returns_error(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "nonexistent_method", token="tok")
    assert "error" in resp


def test_missing_required_param_returns_error(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "project_get", {}, token="tok")
    assert "error" in resp


def test_tools_call_dispatch(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "tools/call",
                 {"name": "project_list", "arguments": {}},
                 token="tok")
    assert "result" in resp
