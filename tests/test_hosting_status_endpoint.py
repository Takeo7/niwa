"""Tests for PR-48 HTTP endpoint — GET /api/hosting/status.

Covers:
  - No domain configured → shape degrades gracefully
  - Domain configured but DNS fails → empty ips, http ok=False, no raise
  - Domain configured with mocked DNS + HTTP → fields populated,
    suggested_records returned with the detected public IP.
  - _detect_public_ip failure is tolerated (returns None).

The external HTTP/DNS calls are patched in-process so the test is
hermetic — no outbound network allowed.

Run: pytest tests/test_hosting_status_endpoint.py -v
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
def server():
    import sqlite3 as _sq
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    port = _free_port()
    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"

    # See test_deployments_endpoints.py rationale.
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

    yield {"base": base, "app": app, "hosting": hosting, "db_path": db_path}

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


def test_status_without_domain_returns_empty_shape(server, monkeypatch):
    h = server["hosting"]
    monkeypatch.setattr(h, "_detect_public_ip", lambda timeout=3.0: None)
    monkeypatch.setattr(h, "_port_listening", lambda host, p, timeout=2.0: False)
    status, out = _get(server["base"], "/api/hosting/status")
    assert status == 200, out
    assert out["domain"] == ""
    assert out["public_ip"] is None
    assert out["caddy_listening"] is False
    assert out["dns"] == {"host": "", "ips": []}
    assert out["wildcard"] == {"host": "", "ips": []}
    assert out["http"]["ok"] is False
    assert out["suggested_records"] == []


def test_status_with_domain_and_mocks(server, monkeypatch):
    h = server["hosting"]
    _set_setting(server["app"], "svc.hosting.domain", "example.com")
    monkeypatch.setattr(h, "_detect_public_ip", lambda timeout=3.0: "1.2.3.4")
    monkeypatch.setattr(h, "_port_listening", lambda host, p, timeout=2.0: True)

    def _fake_dns(host):
        if host == "example.com":
            return ["1.2.3.4"]
        if host == "niwa-probe.example.com":
            return ["1.2.3.4"]
        return []

    monkeypatch.setattr(h, "_resolve_a_records", _fake_dns)
    monkeypatch.setattr(
        h,
        "_http_probe",
        lambda url, timeout=5.0: {"ok": True, "status": 200, "error": None}
        if url.startswith("https://")
        else {"ok": False, "status": None, "error": "not tried"},
    )

    status, out = _get(server["base"], "/api/hosting/status")
    assert status == 200, out
    assert out["domain"] == "example.com"
    assert out["public_ip"] == "1.2.3.4"
    assert out["caddy_listening"] is True
    assert out["dns"] == {"host": "example.com", "ips": ["1.2.3.4"]}
    assert out["wildcard"] == {
        "host": "niwa-probe.example.com",
        "ips": ["1.2.3.4"],
    }
    assert out["http"]["ok"] is True
    assert out["http"]["status"] == 200
    assert out["http"]["url"] == "https://example.com/"
    # The suggested records must both point to the detected public IP.
    assert out["suggested_records"] == [
        {"type": "A", "name": "@", "value": "1.2.3.4", "proxied": True},
        {"type": "A", "name": "*", "value": "1.2.3.4", "proxied": True},
    ]


def test_status_dns_failures_degrade_gracefully(server, monkeypatch):
    h = server["hosting"]
    _set_setting(server["app"], "svc.hosting.domain", "bogus.example")
    monkeypatch.setattr(h, "_detect_public_ip", lambda timeout=3.0: "1.2.3.4")
    monkeypatch.setattr(h, "_port_listening", lambda host, p, timeout=2.0: False)
    monkeypatch.setattr(h, "_resolve_a_records", lambda host: [])
    monkeypatch.setattr(
        h, "_http_probe",
        lambda url, timeout=5.0: {"ok": False, "status": None, "error": "timeout"},
    )
    status, out = _get(server["base"], "/api/hosting/status")
    assert status == 200, out
    assert out["dns"]["ips"] == []
    assert out["wildcard"]["ips"] == []
    assert out["http"]["ok"] is False
    # Both https and http were tried before giving up.
    assert out["http"]["tried"] == [
        "https://bogus.example/",
        "http://bogus.example/",
    ]
    # Still suggests the records so the user can fix DNS.
    assert len(out["suggested_records"]) == 2


def test_status_refuses_to_http_probe_private_ips(server, monkeypatch):
    """SSRF defense: if the configured domain resolves to a private /
    loopback / link-local IP, the HTTP probe is skipped and the status
    surfaces ``error='private_or_invalid_host'``. Prevents an admin from
    using the endpoint to probe internal services (metadata endpoints,
    RFC1918, etc.).
    """
    h = server["hosting"]
    _set_setting(server["app"], "svc.hosting.domain", "internal.example.com")
    monkeypatch.setattr(h, "_detect_public_ip", lambda timeout=3.0: "1.2.3.4")
    monkeypatch.setattr(h, "_port_listening", lambda host, p, timeout=2.0: False)
    # Resolves to a private RFC1918 address — MUST be rejected.
    monkeypatch.setattr(h, "_resolve_a_records", lambda host: ["10.0.0.5"])

    probe_called = {"n": 0}

    def _should_not_be_called(url, timeout=5.0):
        probe_called["n"] += 1
        return {"ok": True, "status": 200, "error": None}

    monkeypatch.setattr(h, "_http_probe", _should_not_be_called)
    status, out = _get(server["base"], "/api/hosting/status")
    assert status == 200
    assert probe_called["n"] == 0
    assert out["http"]["ok"] is False
    assert out["http"]["error"] == "private_or_invalid_host"
    # DNS info is still returned so the wizard can explain the failure.
    assert out["dns"]["ips"] == ["10.0.0.5"]


def test_status_refuses_bare_ip_as_domain(server, monkeypatch):
    """A bare IP address as ``svc.hosting.domain`` is never a legitimate
    hosting domain — reject."""
    h = server["hosting"]
    _set_setting(server["app"], "svc.hosting.domain", "8.8.8.8")
    monkeypatch.setattr(h, "_detect_public_ip", lambda timeout=3.0: None)
    monkeypatch.setattr(h, "_port_listening", lambda host, p, timeout=2.0: False)
    monkeypatch.setattr(h, "_resolve_a_records", lambda host: [])
    probe_called = {"n": 0}
    monkeypatch.setattr(
        h, "_http_probe",
        lambda url, timeout=5.0: (probe_called.__setitem__("n", probe_called["n"] + 1)
                                  or {"ok": True, "status": 200, "error": None}),
    )
    status, out = _get(server["base"], "/api/hosting/status")
    assert status == 200
    assert probe_called["n"] == 0
    assert out["http"]["error"] == "private_or_invalid_host"


def test_status_tolerates_public_ip_detection_failure(server, monkeypatch):
    """Security/UX: if both echo services fail, public_ip is None but the
    response is still a valid 200 — the UI degrades by showing
    '<tu IP>' instead of crashing."""
    h = server["hosting"]
    _set_setting(server["app"], "svc.hosting.domain", "example.org")
    monkeypatch.setattr(h, "_detect_public_ip", lambda timeout=3.0: None)
    monkeypatch.setattr(h, "_port_listening", lambda host, p, timeout=2.0: False)
    monkeypatch.setattr(h, "_resolve_a_records", lambda host: [])
    monkeypatch.setattr(
        h, "_http_probe",
        lambda url, timeout=5.0: {"ok": False, "status": None, "error": "err"},
    )
    status, out = _get(server["base"], "/api/hosting/status")
    assert status == 200
    assert out["public_ip"] is None
    # Without a detected IP, we don't try to suggest useless records.
    assert out["suggested_records"] == []
