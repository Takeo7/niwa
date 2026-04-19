"""Tests for PR-C2 — POST/DELETE /api/hosting/domain and
``hosting._current_domain()`` / ``hosting.save_domain()``.

Covers:
  - Save with validation failing + no ``force`` → 400 and no persist.
  - Save with ``force=true`` → persists even when probes fail, triggers
    a single Caddyfile regeneration + reload.
  - Save on happy path (DNS, wildcard, HTTP all ok) → persists and
    Caddyfile contains the wildcard block.
  - Save rejects private / bare-IP hosts even with ``force=true``
    (SSRF defense-in-depth parity with ``/api/hosting/status``).
  - ``generate_caddyfile()`` prefers DB over ``NIWA_HOSTING_DOMAIN``.
  - Legacy env fallback still works when DB setting is empty.
  - DELETE ``/api/hosting/domain`` clears the setting and regenerates
    a Caddyfile without the wildcard block.

External probes are patched in-process; ``_reload_caddy`` is a no-op
counter.

Run: pytest tests/test_hosting_domain_save.py -v
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
    headers = {"Content-Type": "application/json"} if body is not None else {}
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
            out = json.loads(raw) if raw else {}
            return resp.status, out
    except HTTPError as e:
        raw = e.read()
        try:
            out = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            out = {"raw": raw.decode("utf-8", errors="ignore")}
        return e.code, out


@pytest.fixture
def server():
    import sqlite3 as _sq
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    caddy_path = tempfile.mktemp(suffix="-Caddyfile")

    port = _free_port()
    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"
    os.environ["NIWA_HOSTING_CADDYFILE"] = caddy_path

    # Schema + deployments migration (same pattern as
    # test_deployments_endpoints.py + test_hosting_status_endpoint.py).
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
    import hosting

    # Make tests hermetic: tmp caddyfile, counter for reloads.
    hosting.CADDYFILE_PATH = Path(caddy_path)
    reload_calls = {"n": 0}
    hosting._reload_caddy = lambda: reload_calls.__setitem__("n", reload_calls["n"] + 1)

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

    yield {
        "base": base,
        "app": app,
        "hosting": hosting,
        "db_path": db_path,
        "caddy_path": caddy_path,
        "reload_calls": reload_calls,
    }

    srv.shutdown()
    srv.server_close()
    try:
        os.unlink(db_path)
    except Exception:
        pass
    try:
        os.unlink(caddy_path)
    except Exception:
        pass


def _patch_probes(h, monkeypatch, *, dns=None, wildcard=None, http_ok=False):
    """Patch DNS + HTTP probes in the ``hosting`` module.

    ``dns`` / ``wildcard`` are the A records returned for the exact
    domain / ``niwa-probe.<domain>`` host. ``None`` → empty list.
    """
    def _fake_dns(host):
        if host and dns and host == dns["host"]:
            return list(dns["ips"])
        if host and wildcard and host == wildcard["host"]:
            return list(wildcard["ips"])
        return []
    monkeypatch.setattr(h, "_resolve_a_records", _fake_dns)
    monkeypatch.setattr(
        h, "_http_probe",
        lambda url, timeout=5.0: (
            {"ok": True, "status": 200, "error": None}
            if http_ok else {"ok": False, "status": None, "error": "mock"}
        ),
    )
    monkeypatch.setattr(h, "_detect_public_ip", lambda timeout=3.0: "1.2.3.4")
    monkeypatch.setattr(h, "_port_listening", lambda host, p, timeout=2.0: False)


def _get_setting(app_mod, key):
    with app_mod.db_conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


# ────────────────────────────── validation ──────────────────────────────

def test_save_domain_rejects_when_dns_fails_without_force(server, monkeypatch):
    h = server["hosting"]
    _patch_probes(h, monkeypatch)  # all probes fail
    status, out = _request(
        server["base"], "/api/hosting/domain",
        method="POST", body={"domain": "example.com"},
    )
    assert status == 400, out
    assert out["ok"] is False
    assert out["validation"] == {
        "dns_ok": False,
        "wildcard_ok": False,
        "http_ok": False,
    }
    # Nothing persisted, no reload.
    assert _get_setting(server["app"], "svc.hosting.domain") in (None, "")
    assert server["reload_calls"]["n"] == 0


def test_save_domain_with_force_persists_and_reloads(server, monkeypatch):
    h = server["hosting"]
    _patch_probes(h, monkeypatch)  # all probes fail
    status, out = _request(
        server["base"], "/api/hosting/domain",
        method="POST", body={"domain": "example.com", "force": True},
    )
    assert status == 200, out
    assert out["ok"] is True
    assert _get_setting(server["app"], "svc.hosting.domain") == "example.com"
    assert server["reload_calls"]["n"] == 1


def test_save_domain_happy_path(server, monkeypatch):
    h = server["hosting"]
    _patch_probes(
        h, monkeypatch,
        dns={"host": "example.com", "ips": ["1.2.3.4"]},
        wildcard={"host": "niwa-probe.example.com", "ips": ["1.2.3.4"]},
        http_ok=True,
    )
    status, out = _request(
        server["base"], "/api/hosting/domain",
        method="POST", body={"domain": "example.com"},
    )
    assert status == 200, out
    assert out["ok"] is True
    assert out["validation"] == {
        "dns_ok": True,
        "wildcard_ok": True,
        "http_ok": True,
    }
    assert _get_setting(server["app"], "svc.hosting.domain") == "example.com"
    caddy = Path(server["caddy_path"]).read_text()
    assert "*.example.com:" in caddy
    assert server["reload_calls"]["n"] == 1


def test_save_domain_rejects_private_host_even_with_force(server, monkeypatch):
    h = server["hosting"]
    # DNS resolves to a private IP — must be refused regardless of force.
    _patch_probes(
        h, monkeypatch,
        dns={"host": "internal.example.com", "ips": ["10.0.0.5"]},
    )
    status, out = _request(
        server["base"], "/api/hosting/domain",
        method="POST",
        body={"domain": "internal.example.com", "force": True},
    )
    assert status == 400, out
    assert out["ok"] is False
    assert out["error"] == "private_or_invalid_host"
    assert _get_setting(server["app"], "svc.hosting.domain") in (None, "")
    assert server["reload_calls"]["n"] == 0


def test_save_domain_rejects_bare_ip(server, monkeypatch):
    h = server["hosting"]
    _patch_probes(h, monkeypatch)
    status, out = _request(
        server["base"], "/api/hosting/domain",
        method="POST", body={"domain": "8.8.8.8", "force": True},
    )
    assert status == 400, out
    assert out["error"] == "private_or_invalid_host"


def test_save_domain_requires_non_empty(server, monkeypatch):
    h = server["hosting"]
    _patch_probes(h, monkeypatch)
    status, out = _request(
        server["base"], "/api/hosting/domain",
        method="POST", body={"domain": "   "},
    )
    assert status == 400
    assert out["error"] == "domain_required"


# ──────────────────────── Caddyfile / env fallback ──────────────────────

def test_generate_caddyfile_uses_db_domain_over_env(server, monkeypatch):
    h = server["hosting"]
    # DB domain wins over env var.
    monkeypatch.setenv("NIWA_HOSTING_DOMAIN", "legacy-env.com")
    with server["app"].db_conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES ('svc.hosting.domain', 'db-wins.com') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        c.commit()
    h.generate_caddyfile()
    caddy = Path(server["caddy_path"]).read_text()
    assert "*.db-wins.com:" in caddy
    assert "legacy-env.com" not in caddy


def test_generate_caddyfile_falls_back_to_env(server, monkeypatch):
    h = server["hosting"]
    # DB empty, env var present → Caddyfile uses the env var (retro-compat).
    monkeypatch.setenv("NIWA_HOSTING_DOMAIN", "legacy-env.com")
    with server["app"].db_conn() as c:
        c.execute("DELETE FROM settings WHERE key='svc.hosting.domain'")
        c.commit()
    h.generate_caddyfile()
    caddy = Path(server["caddy_path"]).read_text()
    assert "*.legacy-env.com:" in caddy


# ────────────────────────────── DELETE ──────────────────────────────────

def test_clear_domain_regenerates_path_based_only(server, monkeypatch):
    h = server["hosting"]
    monkeypatch.delenv("NIWA_HOSTING_DOMAIN", raising=False)
    with server["app"].db_conn() as c:
        c.execute(
            "INSERT INTO settings (key, value) VALUES ('svc.hosting.domain', 'was-set.com') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        c.commit()
    status, out = _request(
        server["base"], "/api/hosting/domain", method="DELETE",
    )
    assert status == 200, out
    assert out["ok"] is True
    assert _get_setting(server["app"], "svc.hosting.domain") in (None, "")
    caddy = Path(server["caddy_path"]).read_text()
    assert "*.was-set.com:" not in caddy
    # Path-based block must still be there.
    assert ":8880 {" in caddy or ":" in caddy  # port block present
    assert server["reload_calls"]["n"] == 1
