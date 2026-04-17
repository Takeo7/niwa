"""Tests for PR-49 — GitHub PAT endpoints + obfuscation.

Covers:
  - encrypt_token / decrypt_token roundtrip
  - POST /api/github/token with invalid PAT → 401 (mocked GitHub)
  - POST /api/github/token with empty body → 400
  - POST /api/github/token happy path → 200 + row upserted + response
    shape does NOT leak the raw token
  - GET  /api/github/status reflects persisted state
  - DELETE /api/github/token clears the row

GitHub network is patched via ``github_client._api_get`` so the test is
hermetic.

Run: pytest tests/test_github_endpoints.py -v
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _request(base, path, *, method="GET", body=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{base}{path}", data=data, headers=h, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, {"raw": raw.decode("utf-8", errors="ignore")}


@pytest.fixture
def server():
    import sqlite3 as _sq
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    port = _free_port()
    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"
    # Deterministic obfuscation key so the test is stable.
    os.environ["NIWA_APP_SESSION_SECRET"] = "test-secret-github-pr49"

    # Apply schema so app's top-level _run_migrations doesn't crash on
    # a vanilla DB (same rationale as PR-47/48 tests).
    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    deployments_sql = Path(
        ROOT_DIR, "niwa-app", "db", "migrations", "003_deployments.sql"
    ).read_text()
    _c = _sq.connect(db_path)
    _c.executescript(schema_sql)
    _c.executescript(deployments_sql)
    _c.commit()
    _c.close()

    if "app" in sys.modules:
        import app
        app.DB_PATH = Path(db_path)
    else:
        import app
    import github_client

    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    srv = ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            urlopen(f"{base}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.1)

    yield {"base": base, "app": app, "gh": github_client, "db_path": db_path}

    srv.shutdown()
    srv.server_close()
    try:
        os.unlink(db_path)
    except Exception:
        pass


def test_encrypt_roundtrip_and_nonce_variation():
    import github_client as gh
    ct1 = gh.encrypt_token("ghp_ABC123")
    ct2 = gh.encrypt_token("ghp_ABC123")
    # Fresh nonce each call → different ciphertext even for the same plaintext.
    assert ct1 != ct2
    assert gh.decrypt_token(ct1) == "ghp_ABC123"
    assert gh.decrypt_token(ct2) == "ghp_ABC123"


def test_status_empty_when_no_token(server):
    status, out = _request(server["base"], "/api/github/status")
    assert status == 200
    assert out == {
        "connected": False,
        "username": None,
        "scopes": [],
        "updated_at": None,
    }


def test_post_token_empty_body_400(server):
    status, out = _request(
        server["base"], "/api/github/token", method="POST", body={"token": ""}
    )
    assert status == 400
    assert out["error"] == "empty_token"


def test_post_token_invalid_pat_returns_401(server, monkeypatch):
    gh = server["gh"]
    # Simulate GitHub 401 response for any token.
    monkeypatch.setattr(
        gh,
        "_api_get",
        lambda path, token, timeout=10.0: (401, {"message": "Bad credentials"}, {}),
    )
    status, out = _request(
        server["base"],
        "/api/github/token",
        method="POST",
        body={"token": "ghp_invalid"},
    )
    assert status == 401
    assert out["error"] == "unauthorized"
    # Nothing was persisted.
    _, state = _request(server["base"], "/api/github/status")
    assert state["connected"] is False


def test_post_token_happy_path_stores_and_does_not_leak(server, monkeypatch):
    gh = server["gh"]

    def _fake_api_get(path, token, timeout=10.0):
        assert path == "/user"
        assert token == "ghp_valid_token"
        return 200, {"login": "takeo7"}, {"X-OAuth-Scopes": "repo, workflow"}

    monkeypatch.setattr(gh, "_api_get", _fake_api_get)

    status, out = _request(
        server["base"],
        "/api/github/token",
        method="POST",
        body={"token": "ghp_valid_token"},
    )
    assert status == 200, out
    assert out["ok"] is True
    assert out["connected"] is True
    assert out["username"] == "takeo7"
    assert out["scopes"] == ["repo", "workflow"]
    # Response MUST NOT include the raw token.
    assert "token" not in out
    assert "ghp_valid_token" not in json.dumps(out)

    # Status endpoint reflects the persisted state.
    status, state = _request(server["base"], "/api/github/status")
    assert state["connected"] is True
    assert state["username"] == "takeo7"
    # DB row exists and token decrypts back to the original.
    assert gh.get_pat() == "ghp_valid_token"


def test_delete_token_clears_row(server, monkeypatch):
    gh = server["gh"]
    monkeypatch.setattr(
        gh, "_api_get",
        lambda path, token, timeout=10.0: (200, {"login": "takeo7"}, {}),
    )
    _request(
        server["base"], "/api/github/token", method="POST",
        body={"token": "ghp_will_clear"},
    )
    status, out = _request(server["base"], "/api/github/token", method="DELETE")
    assert status == 200
    assert out["ok"] is True
    _, state = _request(server["base"], "/api/github/status")
    assert state["connected"] is False
    assert gh.get_pat() is None


def test_fine_grained_pat_missing_scopes_header_yields_empty_list(server, monkeypatch):
    """Fine-grained PATs don't return ``X-OAuth-Scopes``. The adapter
    must not explode and must persist an empty scopes list."""
    gh = server["gh"]
    monkeypatch.setattr(
        gh, "_api_get",
        lambda path, token, timeout=10.0: (200, {"login": "takeo7"}, {}),
    )
    status, out = _request(
        server["base"], "/api/github/token", method="POST",
        body={"token": "github_pat_fg_example"},
    )
    assert status == 200
    assert out["scopes"] == []
