"""Tests for PR-10d HTTP endpoints — backend profiles read + patch.

Covers:
  - GET   /api/backend-profiles                 (sorted by priority DESC)
  - GET   /api/backend-profiles/:id             (single row, 404 missing)
  - PATCH /api/backend-profiles/:id             (enabled/priority/default_model)

Each endpoint tested for: auth enforcement where applicable, 404, happy
path payload shape, and the validation rules documented in
``backend_registry.validate_backend_profile_patch``.

Run: pytest tests/test_backend_profiles_endpoints.py -v
"""
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
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


def _request(base, path, *, method="GET", body=None, headers=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    if headers:
        h.update(headers)
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{base}{path}", data=data, headers=h, method=method)
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


def _get(base, path, **kw):
    return _request(base, path, method="GET", **kw)


def _patch(base, path, body, **kw):
    return _request(base, path, method="PATCH", body=body, **kw)


@pytest.fixture
def server():
    """Per-test server with a fresh DB and seeded backend profiles."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    port = _free_port()
    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"
    os.environ["NIWA_APP_HOST"] = "127.0.0.1"

    if "app" in sys.modules:
        import app
        from pathlib import Path
        app.DB_PATH = Path(db_path)
    else:
        import app

    app.HOST = "127.0.0.1"
    app.PORT = port
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    # init_db already seeds claude_code (priority 10) and codex (priority 5).
    # Look up the IDs so tests can target them.
    conn = app.db_conn()
    rows = conn.execute(
        "SELECT id, slug, enabled, priority "
        "FROM backend_profiles ORDER BY slug"
    ).fetchall()
    conn.close()
    by_slug = {r["slug"]: dict(r) for r in rows}

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
        "claude_id": by_slug["claude_code"]["id"],
        "codex_id": by_slug["codex"]["id"],
        "db_path": db_path,
    }

    srv.shutdown()
    os.close(fd)
    os.unlink(db_path)


# ── GET ─────────────────────────────────────────────────────────

class TestListBackendProfiles:

    def test_returns_two_seeded_profiles_sorted_by_priority(self, server):
        status, body = _get(server["base"], "/api/backend-profiles")
        assert status == 200
        assert isinstance(body, list)
        assert len(body) == 2
        # priority DESC, so claude_code (10) before codex (5).
        assert body[0]["slug"] == "claude_code"
        assert body[1]["slug"] == "codex"
        # Each profile exposes the columns the UI consumes.
        for p in body:
            for key in (
                "id", "slug", "display_name", "backend_kind",
                "runtime_kind", "default_model", "command_template",
                "capabilities_json", "enabled", "priority",
                "created_at", "updated_at",
            ):
                assert key in p, f"missing {key} in {p}"

    def test_get_single_profile_ok(self, server):
        status, body = _get(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
        )
        assert status == 200
        assert body["slug"] == "claude_code"

    def test_get_single_profile_404(self, server):
        status, body = _get(
            server["base"],
            f"/api/backend-profiles/{uuid.uuid4()}",
        )
        assert status == 404
        assert body["error"] == "backend_profile_not_found"


# ── PATCH ───────────────────────────────────────────────────────

class TestPatchBackendProfile:

    def test_patch_enabled_bool_ok(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {"enabled": False},
        )
        assert status == 200
        # DB stores as 0/1 but the shape preserves int; UI coerces.
        assert body["enabled"] == 0
        assert body["slug"] == "claude_code"

    def test_patch_enabled_rejects_int(self, server):
        # Accepting 1/0 would silently normalize truthy values; we
        # reject so typos surface.
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {"enabled": 1},
        )
        assert status == 400
        assert body["error"] == "invalid_type"
        assert body["field"] == "enabled"

    def test_patch_enabled_rejects_string(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {"enabled": "true"},
        )
        assert status == 400
        assert body["error"] == "invalid_type"

    def test_patch_priority_ok(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['codex_id']}",
            {"priority": 20},
        )
        assert status == 200
        assert body["priority"] == 20

    def test_patch_priority_rejects_float(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['codex_id']}",
            {"priority": 1.5},
        )
        assert status == 400
        assert body["error"] == "invalid_type"
        assert body["field"] == "priority"

    def test_patch_priority_rejects_bool(self, server):
        # bool is a subclass of int in Python — must be rejected
        # explicitly to avoid True collapsing to 1.
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['codex_id']}",
            {"priority": True},
        )
        assert status == 400
        assert body["error"] == "invalid_type"

    def test_patch_default_model_ok(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {"default_model": "claude-opus-4-6"},
        )
        assert status == 200
        assert body["default_model"] == "claude-opus-4-6"

    def test_patch_default_model_null_ok(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {"default_model": None},
        )
        assert status == 200
        assert body["default_model"] is None

    def test_patch_default_model_rejects_non_string(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {"default_model": 42},
        )
        assert status == 400
        assert body["error"] == "invalid_type"

    def test_patch_rejects_unknown_field(self, server):
        # capabilities_json and command_template are read-only in v0.2.
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {"capabilities_json": "{}"},
        )
        assert status == 400
        assert body["error"] == "unknown_field"
        assert body["field"] == "capabilities_json"

    def test_patch_rejects_slug_change(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {"slug": "different"},
        )
        assert status == 400
        assert body["error"] == "unknown_field"

    def test_patch_combines_multiple_valid_fields(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['codex_id']}",
            {"enabled": False, "priority": 0,
             "default_model": "codex-v1"},
        )
        assert status == 200
        assert body["enabled"] == 0
        assert body["priority"] == 0
        assert body["default_model"] == "codex-v1"

    def test_patch_missing_profile_404(self, server):
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{uuid.uuid4()}",
            {"enabled": True},
        )
        assert status == 404
        assert body["error"] == "backend_profile_not_found"

    def test_patch_empty_payload_is_noop(self, server):
        # Empty dict is valid; nothing changes but we return the
        # current row so the UI can refresh its view.
        status, body = _patch(
            server["base"],
            f"/api/backend-profiles/{server['claude_id']}",
            {},
        )
        assert status == 200
        assert body["slug"] == "claude_code"

    def test_patch_freezes_codex_upgrade(self, server):
        """After a manual PATCH, upgrade_codex_profile must no-op.

        PR-07 Dec 4: the conditional UPDATE only fires when the row
        still has ``enabled=0 AND priority=0`` (PR-03 defaults).
        Once the UI touches the row, those are no longer the values,
        so a subsequent upgrade call never re-enables/re-prioritizes.
        Guards the semantic the SPEC / DECISIONS-LOG promise.
        """
        import backend_registry
        import app

        # Move codex to a user-picked state.
        _patch(
            server["base"],
            f"/api/backend-profiles/{server['codex_id']}",
            {"enabled": False, "priority": 99},
        )

        conn = app.db_conn()
        upgraded = backend_registry.upgrade_codex_profile(conn)
        conn.commit()
        row = conn.execute(
            "SELECT enabled, priority FROM backend_profiles "
            "WHERE id = ?", (server["codex_id"],),
        ).fetchone()
        conn.close()

        assert upgraded is False, (
            "upgrade_codex_profile must not touch a manually edited row"
        )
        assert row["enabled"] == 0
        assert row["priority"] == 99
