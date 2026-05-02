"""Tests for Phase 7 MCP server — auth, tools/list, project/task tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api.deps import get_session
from app.models import AuditEvent


PROJECT_PAYLOAD = {
    "slug": "demo",
    "name": "Demo",
    "kind": "web-deployable",
    "local_path": "/tmp/demo",
}

_RPC = {"jsonrpc": "2.0", "id": 1}
EXPECTED_TOOLS = {
    "ping",
    "project_list",
    "project_get",
    "task_list",
    "task_create",
    "task_attach",
    "task_status",
    "task_respond",
    "task_cancel",
    "task_retry",
    "pull_list",
    "pull_merge",
    "deploy_trigger",
    "deployment_status",
}


def _call(client, method: str, params: dict = {}, *, token: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/api/mcp",
        json={**_RPC, "method": method, "params": params},
        headers=headers,
    ).json()


def _web_project_payload(tmp_path: Path, slug: str = "demo") -> dict:
    root = tmp_path / slug
    (root / "dist").mkdir(parents=True)
    (root / "dist" / "index.html").write_text("ok\n", encoding="utf-8")
    return {
        **PROJECT_PAYLOAD,
        "slug": slug,
        "name": slug.title(),
        "local_path": str(root),
        "deploy_type": "static",
        "dist_dir": "dist",
    }


# ── Auth ───────────────────────────────────────────────────────────────────────


def test_ping_requires_no_auth(client) -> None:
    resp = _call(client, "ping")
    assert resp["result"]["pong"] is True
    assert "version" in resp["result"]


def test_initialize_requires_no_auth(client) -> None:
    resp = _call(client, "initialize")
    assert resp["result"]["serverInfo"]["name"] == "niwa"
    assert resp["result"]["capabilities"]["tools"]["listChanged"] is False


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
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == EXPECTED_TOOLS
    for tool in resp["result"]["tools"]:
        assert "inputSchema" in tool


def test_openclaw_doc_lists_every_tool(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    documented = (Path(__file__).resolve().parents[2] / "docs/integrations/OPENCLAW.md").read_text()
    resp = _call(client, "tools/list", token="tok")
    for tool in resp["result"]["tools"]:
        assert f"`{tool['name']}`" in documented


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


def test_task_create_queue_limit_returns_stable_error(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    monkeypatch.setenv("NIWA_MAX_QUEUED_TASKS_PER_PROJECT", "1")
    client.post("/api/projects", json=PROJECT_PAYLOAD)
    first = _call(
        client,
        "task_create",
        {"project_slug": "demo", "title": "first"},
        token="tok",
    )
    assert "result" in first

    second = _call(
        client,
        "task_create",
        {"project_slug": "demo", "title": "second"},
        token="tok",
    )
    assert second["error"]["code"] == -32009
    assert "queue limit" in second["error"]["message"].lower()


def test_task_attach_uses_attachment_service_and_redacts_audit_payload(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    client.post("/api/projects", json=_web_project_payload(tmp_path))
    task = _call(
        client,
        "task_create",
        {"project_slug": "demo", "title": "Attach spec"},
        token="tok",
    )["result"]

    resp = _call(
        client,
        "task_attach",
        {
            "task_id": task["id"],
            "filename": "spec.md",
            "content": "secret-body",
            "content_type": "text/markdown",
        },
        token="tok",
    )

    assert resp["result"]["filename"] == "spec.md"
    expected = tmp_path / "demo" / ".niwa" / "attachments" / f"task-{task['id']}" / "spec.md"
    assert expected.read_text(encoding="utf-8") == "secret-body"

    db = next(client.app.dependency_overrides[get_session]())
    event = db.query(AuditEvent).filter(AuditEvent.action == "mcp.task_attach").one()
    assert "secret-body" not in (event.payload_json or "")
    assert "REDACTED_ATTACHMENT_CONTENT" in (event.payload_json or "")


def test_task_attach_size_limit_returns_stable_error(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    monkeypatch.setenv("NIWA_MAX_ATTACHMENT_BYTES", "3")
    client.post("/api/projects", json=_web_project_payload(tmp_path))
    task = _call(
        client,
        "task_create",
        {"project_slug": "demo", "title": "Attach spec"},
        token="tok",
    )["result"]

    resp = _call(
        client,
        "task_attach",
        {
            "task_id": task["id"],
            "filename": "too-big.txt",
            "content": "1234",
        },
        token="tok",
    )

    assert resp["error"]["code"] == -32013
    assert "attachment exceeds 3 bytes" in resp["error"]["message"]


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


def test_deploy_trigger_and_status_tools(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    client.post("/api/projects", json=_web_project_payload(tmp_path))

    deployed = _call(
        client,
        "deploy_trigger",
        {"project_slug": "demo"},
        token="tok",
    )["result"]

    assert deployed["status"] == "healthy"
    by_id = _call(
        client,
        "deployment_status",
        {"deployment_id": deployed["id"]},
        token="tok",
    )
    assert by_id["result"]["id"] == deployed["id"]
    by_project = _call(
        client,
        "deployment_status",
        {"project_slug": "demo"},
        token="tok",
    )
    assert by_project["result"]["id"] == deployed["id"]


def test_deploy_trigger_requires_deploy_scope(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NIWA_MCP_TOKEN", raising=False)
    from app.auth.token_store import create_token

    db = next(client.app.dependency_overrides[get_session]())
    raw, _ = create_token(db, "readonly", ["read"])
    client.post("/api/projects", json=_web_project_payload(tmp_path))

    resp = _call(client, "deploy_trigger", {"project_slug": "demo"}, token=raw)
    assert "error" in resp
    assert resp["error"]["code"] == -32003
    assert "deploy" in resp["error"]["message"]


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
    assert resp["error"]["code"] == -32601


def test_missing_required_param_returns_error(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "project_get", {}, token="tok")
    assert "error" in resp
    assert resp["error"]["code"] == -32602
    assert "Missing param" in resp["error"]["message"]


def test_tools_call_dispatch(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_MCP_TOKEN", "tok")
    resp = _call(client, "tools/call",
                 {"name": "project_list", "arguments": {}},
                 token="tok")
    assert "result" in resp
