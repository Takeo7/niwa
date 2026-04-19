"""Tests for PR-A5 HTTP endpoint — GET /api/readiness.

Covers:
  - All components green when creds, models and hosting are configured.
  - admin_ok=False when NIWA_APP_PASSWORD is the default 'change-me'.
  - Backend without any credential → has_credential=False, reachable=False.
  - Codex OAuth token in oauth_tokens counts as has_credential=True.
  - NIWA_HOSTING_DOMAIN env var alone is enough for hosting_ok=True.
  - No hosting hint → hosting_ok=False.
  - db_conn raising → db_ok=False, handler returns 200 (degrades).
  - Handler does NOT hit the network (no urlopen to external hosts).

External calls are patched in-process so the test is hermetic.

Run: pytest tests/test_readiness_endpoint.py -v
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


def _get(base, path):
    req = Request(f"{base}{path}", method="GET")
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
def server(monkeypatch):
    import sqlite3 as _sq
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    port = _free_port()
    monkeypatch.setenv("NIWA_DB_PATH", db_path)
    monkeypatch.setenv("NIWA_APP_PORT", str(port))
    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_APP_HOST", "127.0.0.1")
    # FIX-20260419: keep these tests hermetic. The live Claude CLI
    # probe added in readiness would otherwise spawn `claude` on any
    # box where the binary is installed; test_readiness_probe.py
    # exercises the probe separately against fake binaries.
    monkeypatch.setenv("NIWA_READINESS_PROBE_DISABLED", "1")
    # Start each test with no hosting hint unless the test sets it.
    monkeypatch.delenv("NIWA_HOSTING_DOMAIN", raising=False)
    # Admin creds: the env default is 'change-me'; clear to force the
    # test to opt-in by setting NIWA_APP_PASSWORD explicitly.
    monkeypatch.delenv("NIWA_APP_PASSWORD", raising=False)

    schema_sql = Path(ROOT_DIR, "niwa-app", "db", "schema.sql").read_text()
    _c = _sq.connect(db_path)
    _c.executescript(schema_sql)
    _c.commit()
    _c.close()

    if "app" in sys.modules:
        import app
        app.DB_PATH = Path(db_path)
    else:
        import app
    import health_service

    # Earlier test fixtures may have re-imported ``app`` and left
    # ``health_service._db_conn`` bound to a dead module's db_conn
    # (see test_pr58b2_health_check_revert.py which drops ``app`` from
    # sys.modules). Re-bind defensively so fetch_readiness always hits
    # the DB this fixture just set up.
    health_service._make_deps(app.db_conn)

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

    yield {"base": base, "app": app, "db_path": db_path}

    srv.shutdown()
    srv.server_close()
    try:
        os.unlink(db_path)
    except Exception:
        pass


def _set_setting(app_mod, key, value):
    with app_mod.db_conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        c.commit()


def _set_codex_model(app_mod, model):
    """backend_profiles seeds codex with default_model=NULL; bump it."""
    with app_mod.db_conn() as c:
        c.execute(
            "UPDATE backend_profiles SET default_model=? WHERE slug='codex'",
            (model,),
        )
        c.commit()


def _find_backend(out, slug):
    for b in out["backends"]:
        if b["slug"] == slug:
            return b
    raise AssertionError(f"slug {slug!r} not in backends: {out['backends']}")


# ── 1. All green ──────────────────────────────────────────────────────

def test_readiness_all_ok_returns_green(server, monkeypatch):
    app_mod = server["app"]
    monkeypatch.setenv("NIWA_APP_PASSWORD", "a-strong-password")
    monkeypatch.setenv("NIWA_HOSTING_DOMAIN", "niwa.example.com")
    monkeypatch.setenv("NIWA_LLM_COMMAND", "/usr/bin/claude")

    _set_setting(app_mod, "svc.llm.anthropic.auth_method", "setup_token")
    _set_setting(app_mod, "svc.llm.anthropic.setup_token", "sk-ant-oat01-xxx")
    _set_setting(app_mod, "svc.llm.openai.auth_method", "api_key")
    _set_setting(app_mod, "svc.llm.openai.api_key", "sk-xxx")
    _set_codex_model(app_mod, "gpt-5.4")

    status, out = _get(server["base"], "/api/readiness")
    assert status == 200, out
    assert set(out.keys()) >= {
        "docker_ok", "db_ok", "admin_ok", "admin_detail",
        "backends", "hosting_ok", "hosting_detail", "checked_at",
    }
    assert out["db_ok"] is True
    assert out["admin_ok"] is True
    assert out["hosting_ok"] is True

    claude = _find_backend(out, "claude_code")
    assert claude["has_credential"] is True
    assert claude["auth_mode"] == "setup_token"
    assert claude["model_present"] is True
    assert claude["default_model"]
    assert claude["reachable"] is True

    codex = _find_backend(out, "codex")
    assert codex["has_credential"] is True
    assert codex["auth_mode"] == "api_key"
    assert codex["model_present"] is True
    assert codex["default_model"] == "gpt-5.4"
    assert codex["reachable"] is True


# ── 2. Admin using default password ──────────────────────────────────

def test_readiness_missing_admin_password_flags_admin_not_ok(server, monkeypatch):
    monkeypatch.setenv("NIWA_APP_PASSWORD", "change-me")
    status, out = _get(server["base"], "/api/readiness")
    assert status == 200, out
    assert out["admin_ok"] is False
    assert "default" in out["admin_detail"].lower() \
        or "change-me" in out["admin_detail"].lower()


# ── 3. Backend without credential is not reachable ───────────────────

def test_readiness_backend_without_credential_is_not_reachable(server, monkeypatch):
    monkeypatch.setenv("NIWA_APP_PASSWORD", "secret")
    # No setup_token, no api_key for Claude; no LLM command either.
    monkeypatch.delenv("NIWA_LLM_COMMAND", raising=False)
    status, out = _get(server["base"], "/api/readiness")
    assert status == 200, out
    claude = _find_backend(out, "claude_code")
    assert claude["has_credential"] is False
    assert claude["reachable"] is False


# ── 4. OAuth token counts as credential for codex ────────────────────

def test_readiness_codex_oauth_token_counted_as_credential(server, monkeypatch):
    app_mod = server["app"]
    monkeypatch.setenv("NIWA_APP_PASSWORD", "secret")
    monkeypatch.setenv("NIWA_LLM_COMMAND", "/usr/bin/codex")
    _set_codex_model(app_mod, "gpt-5.4")
    _set_setting(app_mod, "svc.llm.openai.auth_method", "oauth")
    # Seed oauth_tokens directly (mirrors what oauth.py persists).
    with app_mod.db_conn() as c:
        c.execute(
            "INSERT INTO oauth_tokens (provider, access_token, refresh_token, "
            "expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("openai", "tok", "rtok", 9999999999,
             "2026-04-19T00:00:00Z", "2026-04-19T00:00:00Z"),
        )
        c.commit()

    status, out = _get(server["base"], "/api/readiness")
    assert status == 200, out
    codex = _find_backend(out, "codex")
    assert codex["has_credential"] is True
    assert codex["auth_mode"] == "oauth"
    assert codex["reachable"] is True


# ── 5. NIWA_HOSTING_DOMAIN alone → hosting_ok=True ───────────────────

def test_readiness_hosting_detects_domain_env(server, monkeypatch):
    monkeypatch.setenv("NIWA_APP_PASSWORD", "secret")
    monkeypatch.setenv("NIWA_HOSTING_DOMAIN", "niwa.example.com")
    status, out = _get(server["base"], "/api/readiness")
    assert status == 200, out
    assert out["hosting_ok"] is True


# ── 6. No domain, no caddyfile → hosting_ok=False ────────────────────

def test_readiness_hosting_false_when_nothing(server, monkeypatch):
    monkeypatch.setenv("NIWA_APP_PASSWORD", "secret")
    # Point NIWA_HOSTING_CADDYFILE at a path that does not exist.
    missing = os.path.join(tempfile.gettempdir(), "niwa-readiness-missing-caddy")
    try:
        os.unlink(missing)
    except FileNotFoundError:
        pass
    monkeypatch.setenv("NIWA_HOSTING_CADDYFILE", missing)
    status, out = _get(server["base"], "/api/readiness")
    assert status == 200, out
    assert out["hosting_ok"] is False


# ── 7. DB error is tolerated ─────────────────────────────────────────

def test_readiness_db_error_returns_db_ok_false(server, monkeypatch):
    """fetch_readiness must not 500 if the DB call fails — it should
    degrade and return db_ok=False so the widget can render the error."""
    import health_service
    monkeypatch.setenv("NIWA_APP_PASSWORD", "secret")

    def _boom():
        raise RuntimeError("db exploded")

    # Replace the internal factory with one that raises immediately.
    monkeypatch.setattr(health_service, "_db_conn", lambda: _boom())
    status, out = _get(server["base"], "/api/readiness")
    assert status == 200, out
    assert out["db_ok"] is False


# ── 8. Handler does not hit the network ──────────────────────────────

def test_readiness_does_not_call_external_apis(server, monkeypatch):
    """Widget is polled every N seconds — making real API calls from the
    handler would burn tokens per user. Assert no urlopen fires from
    health_service while /api/readiness is served."""
    import health_service
    calls = []
    real_urlopen = health_service.urllib.request.urlopen

    def _spy(url, *a, **kw):
        calls.append(str(url))
        return real_urlopen(url, *a, **kw)

    monkeypatch.setattr(health_service.urllib.request, "urlopen", _spy)
    monkeypatch.setenv("NIWA_APP_PASSWORD", "secret")
    status, _ = _get(server["base"], "/api/readiness")
    assert status == 200
    # No urlopen at all is fired by fetch_readiness.
    assert calls == [], f"unexpected urlopen calls: {calls}"
