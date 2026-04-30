"""Tests for Phase 5 auth — password hashing, sessions, API tokens, endpoints."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.auth.hashing import hash_password, verify_password
from app.auth.password_file import get_password_hash, is_auth_enabled, set_password_hash
from app.auth.token_store import create_token, list_tokens, revoke_token, validate_token
from app.models import ApiToken, NiwaSession


# ── Hashing ───────────────────────────────────────────────────────────────────


def test_hash_and_verify_password() -> None:
    h = hash_password("s3cr3t!")
    assert verify_password("s3cr3t!", h)
    assert not verify_password("wrong", h)


def test_hash_produces_different_salts() -> None:
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2


# ── Password file ─────────────────────────────────────────────────────────────


def test_is_auth_enabled_false_when_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))
    assert not is_auth_enabled()


def test_set_and_get_password_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))
    h = hash_password("mypassword")
    set_password_hash(h)
    assert is_auth_enabled()
    stored = get_password_hash()
    assert stored == h
    assert verify_password("mypassword", stored)


# ── API token store ───────────────────────────────────────────────────────────


def test_create_and_validate_token(client) -> None:
    from app.api.deps import get_session
    db = next(client.app.dependency_overrides[get_session]())

    raw, token = create_token(db, name="test", scopes=["read"])
    assert raw.startswith("niwa_")

    found = validate_token(db, raw)
    assert found is not None
    assert found.id == token.id
    assert found.last_used_at is not None


def test_validate_invalid_token_returns_none(client) -> None:
    from app.api.deps import get_session
    db = next(client.app.dependency_overrides[get_session]())

    result = validate_token(db, "niwa_notavalidtoken")
    assert result is None


def test_revoke_token(client) -> None:
    from app.api.deps import get_session
    db = next(client.app.dependency_overrides[get_session]())

    raw, token = create_token(db, name="revokeme", scopes=["read"])
    revoke_token(db, token.id)

    found = validate_token(db, raw)
    assert found is None


def test_list_tokens_excludes_revoked(client) -> None:
    from app.api.deps import get_session
    db = next(client.app.dependency_overrides[get_session]())

    _, tok1 = create_token(db, name="active", scopes=["read"])
    raw2, tok2 = create_token(db, name="revoked", scopes=["read"])
    revoke_token(db, tok2.id)

    active = list_tokens(db)
    ids = {t.id for t in active}
    assert tok1.id in ids
    assert tok2.id not in ids


# ── Auth API endpoints ────────────────────────────────────────────────────────


def test_auth_status_disabled(client) -> None:
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}


def test_login_when_auth_disabled_returns_400(client) -> None:
    resp = client.post("/api/auth/login", json={"password": "whatever"})
    assert resp.status_code == 400


def test_me_accessible_when_auth_disabled(client) -> None:
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True


def test_login_logout_flow(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))

    h = hash_password("testpass123")
    set_password_hash(h)

    resp = client.post("/api/auth/login", json={"password": "testpass123"})
    assert resp.status_code == 200
    assert "niwa_session" in resp.cookies

    resp2 = client.post("/api/auth/logout")
    assert resp2.status_code == 200


def test_login_wrong_password_returns_401(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))
    set_password_hash(hash_password("realpass"))

    resp = client.post("/api/auth/login", json={"password": "wrongpass"})
    assert resp.status_code == 401


def test_token_create_and_list_when_auth_disabled(client) -> None:
    resp = client.post("/api/auth/tokens", json={"name": "ci", "scopes": ["read"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "ci"
    assert "token" in body
    assert body["token"].startswith("niwa_")

    resp2 = client.get("/api/auth/tokens")
    assert resp2.status_code == 200
    assert len(resp2.json()) == 1


def test_token_create_invalid_scope_returns_422(client) -> None:
    resp = client.post("/api/auth/tokens", json={"name": "bad", "scopes": ["not_a_scope"]})
    assert resp.status_code == 422


def test_token_revoke(client) -> None:
    resp = client.post("/api/auth/tokens", json={"name": "todel", "scopes": ["read"]})
    tok_id = resp.json()["id"]

    resp2 = client.delete(f"/api/auth/tokens/{tok_id}")
    assert resp2.status_code == 204

    resp3 = client.get("/api/auth/tokens")
    assert all(t["id"] != tok_id for t in resp3.json())


def test_bearer_token_auth_when_auth_enabled(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))
    set_password_hash(hash_password("pass123"))

    from app.api.deps import get_session
    db = next(client.app.dependency_overrides[get_session]())
    raw, _ = create_token(db, name="ci-token", scopes=["read", "admin"])

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 200


def test_unauthorized_when_auth_enabled_and_no_creds(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NIWA_HOME", str(tmp_path))
    set_password_hash(hash_password("pass123"))

    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
