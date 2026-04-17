"""GitHub PAT storage + validation (PR-49).

Stores the admin's GitHub personal access token obfuscated at rest.

The obfuscation is a stdlib-only HMAC-SHA256 keystream XOR:

  key        = sha256('niwa-github-pat-v1|' || NIWA_APP_SESSION_SECRET)
  keystream  = HMAC-SHA256(key, nonce || counter) repeated
  ciphertext = plaintext XOR keystream
  blob       = urlsafe_b64(nonce || ciphertext)

This is NOT AEAD. An attacker with the session secret AND the DB can
recover tokens. It is defense-in-depth against a DB-only leak. A proper
upgrade to pyca/cryptography Fernet or AES-GCM is tracked alongside
Bug 28 for v0.3.

Token validation happens live against GitHub's REST API (``GET /user``)
so we can capture the effective username + scopes and reject invalid
PATs before storing them.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def _db_path() -> str:
    return os.environ.get("NIWA_DB_PATH", "/data/niwa.sqlite3")


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def _obf_key() -> bytes:
    secret = os.environ.get("NIWA_APP_SESSION_SECRET", "niwa-dev-secret-change-me")
    return hashlib.sha256(f"niwa-github-pat-v1|{secret}".encode()).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(
            hmac.new(
                key, nonce + counter.to_bytes(4, "big"), hashlib.sha256
            ).digest()
        )
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, ks: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, ks))


def encrypt_token(plaintext: str) -> str:
    """Obfuscate ``plaintext``. Each call uses a fresh 16-byte nonce, so
    re-saving the same token produces a different blob (prevents
    known-plaintext shortcuts)."""
    key = _obf_key()
    nonce = os.urandom(16)
    pt = plaintext.encode("utf-8")
    ct = _xor(pt, _keystream(key, nonce, len(pt)))
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt_token(blob: str) -> str:
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    if len(raw) < 16:
        raise ValueError("invalid_blob")
    nonce, ct = raw[:16], raw[16:]
    key = _obf_key()
    pt = _xor(ct, _keystream(key, nonce, len(ct)))
    return pt.decode("utf-8")


def _api_get(path: str, token: str, timeout: float = 10.0) -> tuple[int, Any, dict]:
    """GET ``https://api.github.com{path}`` with the PAT. Returns
    ``(status, body, headers)``. Raises :class:`urllib.error.URLError`
    for network errors. HTTPError is caught and returned as (status, body,
    headers) so callers can inspect rate limits / unauthorized responses."""
    req = urllib.request.Request(
        f"{GITHUB_API_BASE}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "niwa-github-client/0.2",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode()) if r.length != 0 else {}
            return r.status, body, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"raw": raw.decode("utf-8", errors="ignore")}
        return e.code, body, dict(e.headers or {})


def validate_pat(token: str) -> dict:
    """Verify a PAT against GitHub's API.

    Returns ``{'login': str, 'scopes': list[str]}`` on success. Raises
    ``ValueError`` with a short code on failure:

      - ``empty_token``        — empty input
      - ``unauthorized``       — GitHub returned 401
      - ``forbidden``          — GitHub returned 403 (rate limit / IP block)
      - ``unexpected_status``  — any other non-2xx
    """
    if not token or not token.strip():
        raise ValueError("empty_token")
    status, body, headers = _api_get("/user", token.strip())
    if status == 401:
        raise ValueError("unauthorized")
    if status == 403:
        raise ValueError("forbidden")
    if not (200 <= status < 300):
        raise ValueError(f"unexpected_status:{status}")
    # GitHub returns scopes as a comma-separated header when the token is a
    # classic PAT. Fine-grained PATs omit this header — treat as [].
    scopes_header = (
        headers.get("X-OAuth-Scopes")
        or headers.get("x-oauth-scopes")
        or ""
    )
    scopes = [s.strip() for s in scopes_header.split(",") if s.strip()]
    return {"login": body.get("login", ""), "scopes": scopes}


def set_pat(token: str) -> dict:
    """Validate + persist the PAT. Returns the public status shape."""
    info = validate_pat(token)
    blob = encrypt_token(token.strip())
    with _db() as c:
        # Singleton row (id=1). Upsert.
        c.execute(
            "INSERT INTO github_tokens (id, token_encrypted, username, scopes, created_at, updated_at) "
            "VALUES (1, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'), "
            "strftime('%Y-%m-%dT%H:%M:%SZ','now')) "
            "ON CONFLICT(id) DO UPDATE SET "
            "token_encrypted=excluded.token_encrypted, "
            "username=excluded.username, "
            "scopes=excluded.scopes, "
            "updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')",
            (blob, info["login"], ",".join(info["scopes"])),
        )
        c.commit()
    return status()


def get_pat() -> str | None:
    """Return the plaintext PAT or None. Only the backend should call
    this — never send it to the client."""
    with _db() as c:
        row = c.execute(
            "SELECT token_encrypted FROM github_tokens WHERE id = 1"
        ).fetchone()
    if not row:
        return None
    try:
        return decrypt_token(row["token_encrypted"])
    except Exception:
        logger.exception("github_client: decrypt_token failed")
        return None


def clear_pat() -> None:
    with _db() as c:
        c.execute("DELETE FROM github_tokens WHERE id = 1")
        c.commit()


def status() -> dict:
    """Public shape for ``GET /api/github/status``. Never leaks the
    encrypted blob."""
    with _db() as c:
        row = c.execute(
            "SELECT username, scopes, updated_at FROM github_tokens WHERE id = 1"
        ).fetchone()
    if not row:
        return {
            "connected": False,
            "username": None,
            "scopes": [],
            "updated_at": None,
        }
    scopes = [s for s in (row["scopes"] or "").split(",") if s]
    return {
        "connected": True,
        "username": row["username"],
        "scopes": scopes,
        "updated_at": row["updated_at"],
    }
