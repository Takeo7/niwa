"""Auth/scope coverage for critical product routers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api.deps import get_session
from app.auth.hashing import hash_password
from app.auth.password_file import set_password_hash
from app.auth.token_store import create_token


def _enable_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))
    set_password_hash(hash_password("testpass123"))


def _token_headers(client, scopes: list[str]) -> dict[str, str]:
    db = next(client.app.dependency_overrides[get_session]())
    raw, _ = create_token(db, "scope-test", scopes)
    return {"Authorization": f"Bearer {raw}"}


def _project_payload(tmp_path: Path, slug: str = "demo") -> dict:
    root = tmp_path / slug
    (root / "dist").mkdir(parents=True, exist_ok=True)
    (root / "dist" / "index.html").write_text("ok\n", encoding="utf-8")
    return {
        "slug": slug,
        "name": slug.title(),
        "kind": "web-deployable",
        "local_path": str(root),
        "deploy_type": "static",
        "dist_dir": "dist",
    }


def test_project_routes_require_auth_and_admin_scope(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_auth(tmp_path, monkeypatch)
    payload = _project_payload(tmp_path)

    assert client.get("/api/projects").status_code == 401
    assert client.get(
        "/api/projects", headers=_token_headers(client, ["read"])
    ).status_code == 200
    assert client.post(
        "/api/projects",
        json=payload,
        headers=_token_headers(client, ["read"]),
    ).status_code == 403
    resp = client.post(
        "/api/projects",
        json=payload,
        headers=_token_headers(client, ["admin"]),
    )
    assert resp.status_code == 201


def test_task_create_and_write_scopes(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_auth(tmp_path, monkeypatch)
    client.post(
        "/api/projects",
        json=_project_payload(tmp_path),
        headers=_token_headers(client, ["admin"]),
    )

    assert client.post(
        "/api/projects/demo/tasks",
        json={"title": "Needs create scope"},
        headers=_token_headers(client, ["read"]),
    ).status_code == 403
    created = client.post(
        "/api/projects/demo/tasks",
        json={"title": "Scoped task"},
        headers=_token_headers(client, ["task:create"]),
    )
    assert created.status_code == 201
    task_id = created.json()["id"]

    assert client.get(
        f"/api/tasks/{task_id}",
        headers=_token_headers(client, ["read"]),
    ).status_code == 200
    assert client.post(
        f"/api/tasks/{task_id}/cancel",
        headers=_token_headers(client, ["read"]),
    ).status_code == 403
    cancelled = client.post(
        f"/api/tasks/{task_id}/cancel",
        headers=_token_headers(client, ["task:write"]),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_deploy_and_static_routes_are_scoped_unless_public(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_auth(tmp_path, monkeypatch)
    client.post(
        "/api/projects",
        json=_project_payload(tmp_path),
        headers=_token_headers(client, ["admin"]),
    )

    assert client.post(
        "/api/projects/demo/deployments",
        headers=_token_headers(client, ["read"]),
    ).status_code == 403
    deployed = client.post(
        "/api/projects/demo/deployments",
        headers=_token_headers(client, ["deploy"]),
    )
    assert deployed.status_code == 201

    assert client.get("/api/deploy/demo/").status_code == 401
    public = client.get(
        "/api/deploy/demo/",
        headers=_token_headers(client, ["read"]),
    )
    assert public.status_code == 200
    assert "ok" in public.text

    public_payload = _project_payload(tmp_path, slug="public")
    public_payload["public_enabled"] = True
    client.post(
        "/api/projects",
        json=public_payload,
        headers=_token_headers(client, ["admin"]),
    )
    exposed = client.get("/api/deploy/public/")
    assert exposed.status_code == 200
    assert "ok" in exposed.text


def test_metrics_and_pull_merge_scopes(
    client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_auth(tmp_path, monkeypatch)
    payload = _project_payload(tmp_path)
    payload["git_remote"] = "https://github.com/example/demo.git"
    client.post(
        "/api/projects",
        json=payload,
        headers=_token_headers(client, ["admin"]),
    )

    assert client.get("/api/metrics").status_code == 401
    assert client.get(
        "/api/metrics",
        headers=_token_headers(client, ["read"]),
    ).status_code == 200
    assert client.post(
        "/api/projects/demo/pulls/1/merge",
        json={"method": "squash"},
        headers=_token_headers(client, ["read"]),
    ).status_code == 403
