"""Tests for PR-10d HTTP endpoints — project capability profile.

Covers:
  - GET /api/projects/:id/capability-profile
      · project with persisted row → is_default=False
      · project without row         → is_default=True, defaults returned
      · lookup by slug or id
      · missing project → 404
  - PUT /api/projects/:id/capability-profile
      · valid payload creates row from DEFAULT + overrides
      · valid payload updates existing row
      · enum validation (repo_mode, shell_mode, web_mode, network_mode)
      · JSON validation (shell_whitelist_json, *_scope_json,
        resource_budget_json)
      · unknown_field rejection (e.g. name, project_id)
      · missing project → 404

Run: pytest tests/test_capability_profile_endpoints.py -v
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


def _request(base, path, *, method="GET", body=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
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


def _get(base, path):
    return _request(base, path, method="GET")


def _put(base, path, body):
    return _request(base, path, method="PUT", body=body)


@pytest.fixture
def server():
    """Per-test server with two projects: one seeded standard profile,
    one without any capability row."""
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

    conn = app.db_conn()
    now = app.now_iso()

    # Project A: created BEFORE init_db seed, so seed_capability_profiles
    # is idempotent — but we'll delete any row to start clean.
    project_a = str(uuid.uuid4())
    project_b = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, "
        "updated_at) VALUES (?, 'proj-a', 'Proj A', 'proyecto', ?, ?)",
        (project_a, now, now),
    )
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, "
        "updated_at) VALUES (?, 'proj-b', 'Proj B', 'proyecto', ?, ?)",
        (project_b, now, now),
    )
    conn.commit()

    # Seed capability profile for project_a only (simulates an existing
    # row that the UI should edit in place).  Project B stays without
    # a row so the fallback/upsert paths are covered.
    import capability_service
    capability_service.seed_capability_profiles(conn)
    # Remove project_b's row if seed created one.
    conn.execute(
        "DELETE FROM project_capability_profiles WHERE project_id = ?",
        (project_b,),
    )
    conn.commit()
    conn.close()

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
        "project_a": project_a,
        "project_a_slug": "proj-a",
        "project_b": project_b,
        "project_b_slug": "proj-b",
        "db_path": db_path,
    }

    srv.shutdown()
    os.close(fd)
    os.unlink(db_path)


# ── GET ─────────────────────────────────────────────────────────

class TestGetCapabilityProfile:

    def test_returns_persisted_profile_by_id(self, server):
        status, body = _get(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
        )
        assert status == 200
        assert body["is_default"] is False
        assert body["project_id"] == server["project_a"]
        p = body["profile"]
        assert p["repo_mode"] == "read-write"
        assert p["shell_mode"] == "whitelist"

    def test_returns_persisted_profile_by_slug(self, server):
        status, body = _get(
            server["base"],
            f"/api/projects/{server['project_a_slug']}/capability-profile",
        )
        assert status == 200
        assert body["is_default"] is False
        assert body["project_id"] == server["project_a"]

    def test_returns_default_when_no_row(self, server):
        status, body = _get(
            server["base"],
            f"/api/projects/{server['project_b']}/capability-profile",
        )
        assert status == 200
        assert body["is_default"] is True
        assert body["project_id"] == server["project_b"]
        p = body["profile"]
        # Matches DEFAULT_CAPABILITY_PROFILE
        assert p["repo_mode"] == "read-write"
        assert p["shell_mode"] == "whitelist"
        assert p["web_mode"] == "off"
        assert p["network_mode"] == "off"

    def test_missing_project_404(self, server):
        status, body = _get(
            server["base"],
            f"/api/projects/{uuid.uuid4()}/capability-profile",
        )
        assert status == 404
        assert body["error"] == "project_not_found"


# ── PUT ─────────────────────────────────────────────────────────

class TestPutCapabilityProfile:

    def test_put_creates_row_when_missing(self, server):
        # Project B has no row — PUT must create from defaults and
        # apply the override.
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_b']}/capability-profile",
            {"shell_mode": "disabled"},
        )
        assert status == 200
        assert body["is_default"] is False
        assert body["profile"]["shell_mode"] == "disabled"
        # Untouched fields fell back to DEFAULT_CAPABILITY_PROFILE.
        assert body["profile"]["repo_mode"] == "read-write"

        # Subsequent GET should now return is_default=False.
        status2, body2 = _get(
            server["base"],
            f"/api/projects/{server['project_b']}/capability-profile",
        )
        assert status2 == 200
        assert body2["is_default"] is False
        assert body2["profile"]["shell_mode"] == "disabled"

    def test_put_updates_existing_row(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"web_mode": "on", "network_mode": "restricted"},
        )
        assert status == 200
        assert body["profile"]["web_mode"] == "on"
        assert body["profile"]["network_mode"] == "restricted"
        # Fields not in payload remained.
        assert body["profile"]["shell_mode"] == "whitelist"

    def test_put_supports_slug_lookup(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a_slug']}/capability-profile",
            {"web_mode": "on"},
        )
        assert status == 200
        assert body["project_id"] == server["project_a"]

    def test_put_rejects_invalid_repo_mode(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"repo_mode": "chaos"},
        )
        assert status == 400
        assert body["error"] == "invalid_enum"
        assert body["field"] == "repo_mode"

    def test_put_rejects_invalid_shell_mode(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"shell_mode": "unlimited"},
        )
        assert status == 400
        assert body["error"] == "invalid_enum"
        assert body["field"] == "shell_mode"

    def test_put_rejects_invalid_web_mode(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"web_mode": "maybe"},
        )
        assert status == 400
        assert body["field"] == "web_mode"

    def test_put_rejects_invalid_network_mode(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"network_mode": "firewalled"},
        )
        assert status == 400
        assert body["field"] == "network_mode"

    def test_put_rejects_shell_whitelist_non_string_elements(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"shell_whitelist_json": json.dumps(["ls", 42, "cat"])},
        )
        assert status == 400
        assert body["error"] == "invalid_json"
        assert body["field"] == "shell_whitelist_json"

    def test_put_rejects_shell_whitelist_not_a_list(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"shell_whitelist_json": json.dumps({"ls": True})},
        )
        assert status == 400
        assert body["field"] == "shell_whitelist_json"

    def test_put_rejects_invalid_filesystem_scope_json(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"filesystem_scope_json": "{not valid json"},
        )
        assert status == 400
        assert body["error"] == "invalid_json"
        assert body["field"] == "filesystem_scope_json"

    def test_put_rejects_invalid_resource_budget_json(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"resource_budget_json": "not-json-at-all"},
        )
        assert status == 400
        assert body["field"] == "resource_budget_json"

    def test_put_accepts_valid_json_payloads(self, server):
        fs = {"allow": ["<workspace>", "/tmp/niwa"], "deny": []}
        secrets = {"allow": ["GITHUB_TOKEN"]}
        budget = {"max_cost_usd": 2.5, "max_duration_ms": 300000}
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {
                "filesystem_scope_json": json.dumps(fs),
                "secrets_scope_json": json.dumps(secrets),
                "resource_budget_json": json.dumps(budget),
                "shell_whitelist_json": json.dumps(["ls", "cat"]),
            },
        )
        assert status == 200
        assert json.loads(body["profile"]["filesystem_scope_json"]) == fs
        assert json.loads(body["profile"]["secrets_scope_json"]) == secrets
        assert json.loads(body["profile"]["resource_budget_json"]) == budget
        assert json.loads(
            body["profile"]["shell_whitelist_json"]
        ) == ["ls", "cat"]

    def test_put_rejects_unknown_field(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"name": "custom"},
        )
        assert status == 400
        assert body["error"] == "unknown_field"
        assert body["field"] == "name"

    def test_put_rejects_project_id_edit(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {"project_id": "other"},
        )
        assert status == 400
        assert body["error"] == "unknown_field"

    def test_put_missing_project_404(self, server):
        status, body = _put(
            server["base"],
            f"/api/projects/{uuid.uuid4()}/capability-profile",
            {"web_mode": "on"},
        )
        assert status == 404
        assert body["error"] == "project_not_found"

    def test_put_empty_payload_is_noop_on_existing(self, server):
        """Empty PUT on an existing row returns current state
        untouched — useful for idempotent UI submits."""
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_a']}/capability-profile",
            {},
        )
        assert status == 200
        assert body["is_default"] is False

    def test_put_empty_payload_on_missing_creates_defaults(self, server):
        """Per PR-05 Dec 4: editing a project without a row has to
        CREATE the row before persisting.  Empty payload still
        materializes the defaults."""
        status, body = _put(
            server["base"],
            f"/api/projects/{server['project_b']}/capability-profile",
            {},
        )
        assert status == 200
        assert body["is_default"] is False
        assert body["profile"]["repo_mode"] == "read-write"
