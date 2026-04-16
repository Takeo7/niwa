"""Tests for PR-40 / Bug 29 — ``Secure`` flag on session cookie.

Bug 29 (docs/BUGS-FOUND.md:494): the session cookie was emitted with
``HttpOnly; SameSite=Lax`` but no ``Secure``. Niwa's default Caddyfile
has ``auto_https off`` (Caddy is an internal reverse proxy — TLS
terminates at cloudflared / external nginx). If the operator forgets
to front Niwa with TLS at all, the cookie rides in the clear over
the internet and can be captured by a MITM.

PR-40 computes the flag **per request** with three signals, first
match wins:

1. ``NIWA_APP_COOKIE_SECURE=1`` explicit override.
2. ``NIWA_APP_PUBLIC_BASE_URL`` starts with ``https://``.
3. ``X-Forwarded-Proto: https`` from a trusted proxy (same
   trust rule as ``client_ip``: the header is only honoured if
   the TCP peer is in ``NIWA_TRUSTED_PROXIES``, otherwise a rogue
   client could forge it).

This matters because the default ``NIWA_APP_PUBLIC_BASE_URL`` is
``http://127.0.0.1:<port>`` and many operators leave it as-is while
deploying Niwa behind cloudflared / nginx / traefik with TLS.
Without the proxy-proto signal, those deployments would leak the
cookie in the clear.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "niwa-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


DB_DIR = REPO_ROOT / "niwa-app" / "db"


@pytest.fixture()
def fresh_app(monkeypatch, tmp_path):
    """Reimport ``app`` with a pristine env. Module-level
    ``_COOKIE_FORCE_SECURE`` and ``_COOKIE_BASE_URL_IS_HTTPS`` are
    evaluated at import time, so the caller sets env vars before
    invoking the returned factory.

    Seeds a SQLite DB with the current ``schema.sql`` so
    ``_run_migrations()`` at module-level import doesn't SystemExit.
    """
    import sqlite3 as _sq3
    db_path = tmp_path / "x.sqlite3"
    with _sq3.connect(str(db_path)) as c:
        c.executescript((DB_DIR / "schema.sql").read_text())
        c.commit()

    monkeypatch.setenv("NIWA_APP_AUTH_REQUIRED", "0")
    monkeypatch.setenv("NIWA_DB_PATH", str(db_path))
    monkeypatch.setenv("NIWA_DATA_DIR", str(tmp_path))

    def _reimport():
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        return importlib.import_module("app")

    return _reimport


def _mock_handler(*, xfp: str | None = None,
                  client_addr: str = "10.0.0.1"):
    """Build a fake handler exposing the two attributes
    ``_cookie_secure_attr`` reads: ``.headers`` (dict-like) and
    ``.client_address`` (tuple)."""
    h = MagicMock()
    headers = {}
    if xfp is not None:
        headers["X-Forwarded-Proto"] = xfp
    # ``get`` is the only method _cookie_secure_attr uses on headers.
    h.headers = MagicMock()
    h.headers.get = lambda key, default="": headers.get(key, default)
    h.client_address = (client_addr, 12345)
    return h


class TestSecureFromEnvVars:

    def test_https_public_url_sets_secure(self, fresh_app, monkeypatch):
        monkeypatch.setenv(
            "NIWA_APP_PUBLIC_BASE_URL", "https://niwa.example.com",
        )
        monkeypatch.delenv("NIWA_APP_COOKIE_SECURE", raising=False)
        app = fresh_app()
        h = _mock_handler()
        assert app._cookie_secure_attr(h) == "Secure; "

    def test_http_public_url_omits_secure(self, fresh_app, monkeypatch):
        """Dev local over plain http: Secure would make the browser
        silently drop the cookie — no login possible."""
        monkeypatch.setenv(
            "NIWA_APP_PUBLIC_BASE_URL", "http://127.0.0.1:8080",
        )
        monkeypatch.delenv("NIWA_APP_COOKIE_SECURE", raising=False)
        app = fresh_app()
        h = _mock_handler()
        assert app._cookie_secure_attr(h) == ""

    def test_force_secure_env_flips_on(self, fresh_app, monkeypatch):
        """Deployment with TLS at the reverse proxy and plain http
        back to Niwa, operator doesn't want to change the public URL:
        the override must win."""
        monkeypatch.setenv(
            "NIWA_APP_PUBLIC_BASE_URL", "http://127.0.0.1:8080",
        )
        monkeypatch.setenv("NIWA_APP_COOKIE_SECURE", "1")
        app = fresh_app()
        h = _mock_handler()
        assert app._cookie_secure_attr(h) == "Secure; "

    def test_force_secure_zero_does_not_force(self, fresh_app, monkeypatch):
        monkeypatch.setenv(
            "NIWA_APP_PUBLIC_BASE_URL", "http://127.0.0.1:8080",
        )
        monkeypatch.setenv("NIWA_APP_COOKIE_SECURE", "0")
        app = fresh_app()
        h = _mock_handler()
        assert app._cookie_secure_attr(h) == ""


class TestSecureFromForwardedProto:
    """The scheme-based approach leaves leaks when the operator
    leaves ``NIWA_APP_PUBLIC_BASE_URL`` as the 127.0.0.1 default
    (common: the quick installer always writes http://127.0.0.1).
    If we're behind a trusted proxy that says ``X-Forwarded-Proto:
    https``, that's a stronger signal than the env var."""

    def test_trusted_proxy_xfp_https_flips_secure(
        self, fresh_app, monkeypatch,
    ):
        monkeypatch.setenv(
            "NIWA_APP_PUBLIC_BASE_URL", "http://127.0.0.1:8080",
        )
        monkeypatch.delenv("NIWA_APP_COOKIE_SECURE", raising=False)
        monkeypatch.setenv("NIWA_TRUSTED_PROXIES", "10.0.0.1")
        app = fresh_app()
        h = _mock_handler(xfp="https", client_addr="10.0.0.1")
        assert app._cookie_secure_attr(h) == "Secure; ", (
            "A trusted proxy that announces X-Forwarded-Proto: https "
            "must flip the flag on even if the public URL env var "
            "is the default http://127.0.0.1."
        )

    def test_untrusted_peer_xfp_https_ignored(
        self, fresh_app, monkeypatch,
    ):
        """Never honour X-Forwarded-Proto from an untrusted peer —
        a rogue client could set it to https over plain http and
        trick us into emitting Secure, causing the browser to store
        a cookie it'll refuse to ever resend (session breaks). More
        importantly, it breaks the security assumption of the flag
        (the client could as easily set it to http on a https
        connection to downgrade us)."""
        monkeypatch.setenv(
            "NIWA_APP_PUBLIC_BASE_URL", "http://127.0.0.1:8080",
        )
        monkeypatch.delenv("NIWA_APP_COOKIE_SECURE", raising=False)
        monkeypatch.setenv(
            "NIWA_TRUSTED_PROXIES", "10.0.0.1",
        )
        app = fresh_app()
        h = _mock_handler(xfp="https", client_addr="203.0.113.99")
        assert app._cookie_secure_attr(h) == "", (
            "X-Forwarded-Proto from a random internet peer must NOT "
            "be trusted — same rule client_ip() applies to "
            "X-Forwarded-For."
        )

    def test_trusted_proxy_xfp_http_stays_off(
        self, fresh_app, monkeypatch,
    ):
        monkeypatch.setenv(
            "NIWA_APP_PUBLIC_BASE_URL", "http://127.0.0.1:8080",
        )
        monkeypatch.delenv("NIWA_APP_COOKIE_SECURE", raising=False)
        monkeypatch.setenv("NIWA_TRUSTED_PROXIES", "10.0.0.1")
        app = fresh_app()
        h = _mock_handler(xfp="http", client_addr="10.0.0.1")
        assert app._cookie_secure_attr(h) == ""


class TestSetCookieStringsIncludeAttr:
    """Static source guards: the two ``Set-Cookie`` headers in app.py
    must call ``_cookie_secure_attr(self)`` so a refactor can't
    silently drop the flag."""

    def test_login_set_cookie_calls_helper(self):
        src = (BACKEND_DIR / "app.py").read_text()
        matching = [
            line for line in src.splitlines()
            if "Set-Cookie" in line and "={token}" in line
        ]
        assert matching, "could not locate the login Set-Cookie line."
        for line in matching:
            assert "_cookie_secure_attr(self)" in line, (
                f"login Set-Cookie must invoke the helper: {line}"
            )

    def test_logout_set_cookie_calls_helper(self):
        src = (BACKEND_DIR / "app.py").read_text()
        matching = [
            line for line in src.splitlines()
            if "Set-Cookie" in line and "Max-Age=0" in line
        ]
        assert matching, "could not locate the logout Set-Cookie line."
        for line in matching:
            assert "_cookie_secure_attr(self)" in line, (
                f"logout Set-Cookie must invoke the helper: {line}"
            )
