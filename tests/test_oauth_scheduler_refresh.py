"""Tests for PR-A7 — proactive OAuth token refresher in scheduler.

The scheduler thread exposes ``_refresh_expiring_oauth_tokens`` that
iterates ``oauth_tokens`` and refreshes any row whose ``expires_at``
is within a configurable margin (10 min). Refreshed tokens overwrite
access_token, refresh_token (if a new one is returned), and
expires_at in the same DB row.

Covered:

* Fresh tokens (expires far in the future) are not refreshed.
* Expiring tokens (within the margin) are refreshed and persisted.
* Refresh failures are logged and swallowed — DB state is left
  intact and subsequent ticks can retry.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT_DIR / "niwa-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture
def temp_db():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE oauth_tokens (
            provider    TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            id_token    TEXT,
            expires_at  INTEGER,
            email       TEXT,
            account_id  TEXT,
            metadata    TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()

    def db_conn_fn():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    yield db_path, db_conn_fn
    os.unlink(db_path)


def _insert_token(db_conn_fn, *, provider, expires_at, refresh_token="rt"):
    with db_conn_fn() as c:
        c.execute(
            "INSERT INTO oauth_tokens "
            "(provider, access_token, refresh_token, id_token, expires_at, "
            " email, account_id, metadata, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                provider,
                "old_access",
                refresh_token,
                "",
                expires_at,
                "user@example.com",
                "",
                "{}",
                "2026-04-19T00:00:00Z",
                "2026-04-19T00:00:00Z",
            ),
        )
        c.commit()


def _fetch_row(db_conn_fn, provider):
    with db_conn_fn() as c:
        return c.execute(
            "SELECT * FROM oauth_tokens WHERE provider=?", (provider,)
        ).fetchone()


def test_fresh_token_not_refreshed(temp_db):
    """A token that expires in >margin should not be refreshed."""
    from scheduler import _refresh_expiring_oauth_tokens

    _, db_conn_fn = temp_db
    now = int(time.time())
    _insert_token(db_conn_fn, provider="openai", expires_at=now + 3600)

    with patch("oauth.refresh_access_token") as mock_refresh:
        _refresh_expiring_oauth_tokens(db_conn_fn, margin_seconds=600)

    assert mock_refresh.call_count == 0
    row = _fetch_row(db_conn_fn, "openai")
    assert row["access_token"] == "old_access"


def test_expiring_token_is_refreshed_and_persisted(temp_db):
    """A token expiring within margin should be refreshed and the new
    access_token / refresh_token / expires_at should land in the DB."""
    from scheduler import _refresh_expiring_oauth_tokens

    _, db_conn_fn = temp_db
    now = int(time.time())
    _insert_token(db_conn_fn, provider="openai", expires_at=now + 120)

    new_expires = now + 86400
    with patch(
        "oauth.refresh_access_token",
        return_value={
            "access_token": "new_access",
            "refresh_token": "new_rt",
            "id_token": "",
            "expires_at": new_expires,
            "email": "user@example.com",
            "provider": "openai",
        },
    ) as mock_refresh:
        _refresh_expiring_oauth_tokens(db_conn_fn, margin_seconds=600)

    assert mock_refresh.call_count == 1
    # provider + refresh_token are passed positionally or by keyword
    args, kwargs = mock_refresh.call_args
    call_args = list(args) + [kwargs.get("provider"), kwargs.get("refresh_token")]
    assert "openai" in call_args
    assert "rt" in call_args

    row = _fetch_row(db_conn_fn, "openai")
    assert row["access_token"] == "new_access"
    assert row["refresh_token"] == "new_rt"
    assert row["expires_at"] == new_expires


def test_refresh_error_is_swallowed_and_row_unchanged(temp_db):
    """If the provider refuses the refresh, the scheduler must not
    raise or corrupt the row. The next tick can retry."""
    from scheduler import _refresh_expiring_oauth_tokens

    _, db_conn_fn = temp_db
    now = int(time.time())
    _insert_token(db_conn_fn, provider="openai", expires_at=now + 60)

    with patch(
        "oauth.refresh_access_token",
        return_value={"error": "HTTP 401 unauthorized"},
    ):
        # No exception should escape
        _refresh_expiring_oauth_tokens(db_conn_fn, margin_seconds=600)

    row = _fetch_row(db_conn_fn, "openai")
    assert row["access_token"] == "old_access"
    assert row["refresh_token"] == "rt"


def test_row_without_refresh_token_is_skipped(temp_db):
    """If the stored row has no refresh_token we can't refresh it —
    skip it without raising."""
    from scheduler import _refresh_expiring_oauth_tokens

    _, db_conn_fn = temp_db
    now = int(time.time())
    _insert_token(
        db_conn_fn, provider="openai", expires_at=now + 60, refresh_token=""
    )

    with patch("oauth.refresh_access_token") as mock_refresh:
        _refresh_expiring_oauth_tokens(db_conn_fn, margin_seconds=600)

    assert mock_refresh.call_count == 0
