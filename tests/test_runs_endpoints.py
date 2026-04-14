"""Tests for PR-10a/10c HTTP endpoints — runs + routing + artifacts.

Covers:
  - GET /api/tasks/:id/runs                   (PR-10a)
  - GET /api/tasks/:id/routing-decision       (PR-10a)
  - GET /api/runs/:id                         (PR-10a)
  - GET /api/runs/:id/events                  (PR-10a)
  - GET /api/runs/:id/artifacts               (PR-10c)

Each endpoint tested for: auth enforcement, 404 on missing resource,
happy path with joined shape.

Run: pytest tests/test_runs_endpoints.py -v
"""
import json
import os
import sqlite3
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


def _get(base, path, *, headers=None):
    req = Request(f"{base}{path}", headers=headers or {}, method="GET")
    try:
        with urlopen(req, timeout=10) as resp:
            raw = resp.read()
            body = json.loads(raw) if raw else {}
            return resp.status, body
    except HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {"raw": raw.decode("utf-8", errors="ignore")}
        return e.code, body


@pytest.fixture(scope="module")
def server():
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
    # Force-override: NIWA_APP_AUTH_REQUIRED is read from env only at
    # module import time, so if another test already imported ``app``
    # the env var we just set won't take effect.  Pin the attribute.
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    # Seed: project, task, two backend_profiles, a routing decision,
    # two backend_runs (the second being a fallback), and a handful
    # of backend_run_events on the first run.
    conn = app.db_conn()
    now = app.now_iso()

    project_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    other_task_id = str(uuid.uuid4())
    claude_id = str(uuid.uuid4())
    codex_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    run1_id = str(uuid.uuid4())
    run2_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO projects (id, slug, name, area, description, "
        "active, created_at, updated_at) "
        "VALUES (?, 'p', 'P', 'proyecto', '', 1, ?, ?)",
        (project_id, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, "
        "created_at, updated_at) "
        "VALUES (?, 'Test', 'proyecto', 'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, "
        "created_at, updated_at) "
        "VALUES (?, 'Other', 'proyecto', 'pendiente', 'media', ?, ?)",
        (other_task_id, now, now),
    )
    # Overwrite the two seed profiles added by init_db with known ids.
    conn.execute("DELETE FROM backend_profiles")
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, "
        "backend_kind, runtime_kind, enabled, priority, "
        "capabilities_json, created_at, updated_at) "
        "VALUES (?, 'claude_code', 'Claude Code', 'claude_code', "
        "'cli', 1, 10, '{}', ?, ?)",
        (claude_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, "
        "backend_kind, runtime_kind, enabled, priority, "
        "capabilities_json, created_at, updated_at) "
        "VALUES (?, 'codex', 'Codex', 'codex', 'cli', 1, 5, "
        "'{}', ?, ?)",
        (codex_id, now, now),
    )
    conn.execute(
        "INSERT INTO routing_decisions "
        "(id, task_id, decision_index, requested_profile_id, "
        " selected_profile_id, reason_summary, matched_rules_json, "
        " fallback_chain_json, contract_version, created_at) "
        "VALUES (?, ?, 0, NULL, ?, ?, ?, ?, ?, ?)",
        (
            rd_id, task_id, claude_id,
            "Rule 'complex_to_claude' matched",
            json.dumps([
                {"rule": "routing_rule", "rule_name": "complex_to_claude",
                 "position": 10, "slug": "claude_code",
                 "profile_id": claude_id},
            ]),
            json.dumps([claude_id, codex_id]),
            "v02-assistant",
            now,
        ),
    )
    conn.execute(
        "INSERT INTO backend_runs "
        "(id, task_id, routing_decision_id, backend_profile_id, "
        " backend_kind, runtime_kind, status, "
        " created_at, updated_at, started_at) "
        "VALUES (?, ?, ?, ?, 'claude_code', 'cli', 'succeeded', "
        "        ?, ?, ?)",
        (run1_id, task_id, rd_id, claude_id, now, now, now),
    )
    time.sleep(1.1)
    now2 = app.now_iso()
    conn.execute(
        "INSERT INTO backend_runs "
        "(id, task_id, routing_decision_id, previous_run_id, "
        " relation_type, backend_profile_id, backend_kind, "
        " runtime_kind, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'fallback', ?, 'codex', 'cli', "
        "        'running', ?, ?)",
        (run2_id, task_id, rd_id, run1_id, codex_id, now2, now2),
    )
    for i, etype in enumerate([
        "system_init", "assistant_message", "tool_use",
        "tool_result", "result",
    ]):
        conn.execute(
            "INSERT INTO backend_run_events "
            "(id, backend_run_id, event_type, message, "
            " payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), run1_id, etype,
                f"{etype} step {i}",
                json.dumps({"idx": i}),
                app.now_iso(),
            ),
        )
    # Artifacts on run1 (PR-10c) — paths are relative to artifact_root.
    art_specs = [
        ("code", "src/main.py", 1024,
         "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        ("document", "README.md", 256,
         "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
        ("log", "run.log", 2048, None),  # sha256 NULL — Bug 8 tolerance.
    ]
    art_ids = []
    for atype, apath, size, sha in art_specs:
        aid = str(uuid.uuid4())
        art_ids.append(aid)
        conn.execute(
            "INSERT INTO artifacts "
            "(id, task_id, backend_run_id, artifact_type, path, "
            " size_bytes, sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, task_id, run1_id, atype, apath, size, sha,
             app.now_iso()),
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
        "task_id": task_id,
        "other_task_id": other_task_id,
        "claude_id": claude_id,
        "codex_id": codex_id,
        "rd_id": rd_id,
        "run1_id": run1_id,
        "run2_id": run2_id,
        "db_path": db_path,
        "artifact_ids": art_ids,
    }

    srv.shutdown()
    os.close(fd)
    os.unlink(db_path)


# ── GET /api/tasks/:id/runs ─────────────────────────────────────────


class TestListRunsEndpoint:

    def test_returns_runs_oldest_first(self, server):
        status, body = _get(
            server["base"], f"/api/tasks/{server['task_id']}/runs",
        )
        assert status == 200
        assert [r["id"] for r in body] == [
            server["run1_id"], server["run2_id"],
        ]

    def test_runs_include_backend_profile_slug(self, server):
        status, body = _get(
            server["base"], f"/api/tasks/{server['task_id']}/runs",
        )
        assert status == 200
        assert body[0]["backend_profile_slug"] == "claude_code"
        assert body[0]["backend_profile_display_name"] == "Claude Code"
        assert body[1]["backend_profile_slug"] == "codex"

    def test_fallback_relation_visible(self, server):
        status, body = _get(
            server["base"], f"/api/tasks/{server['task_id']}/runs",
        )
        assert status == 200
        assert body[1]["relation_type"] == "fallback"
        assert body[1]["previous_run_id"] == server["run1_id"]

    def test_empty_for_task_without_runs(self, server):
        status, body = _get(
            server["base"],
            f"/api/tasks/{server['other_task_id']}/runs",
        )
        assert status == 200
        assert body == []

    def test_404_for_missing_task(self, server):
        status, body = _get(server["base"], "/api/tasks/nope/runs")
        assert status == 404
        assert body["error"] == "task_not_found"


# ── GET /api/runs/:id ───────────────────────────────────────────────


class TestGetRunEndpoint:

    def test_returns_run_with_profile(self, server):
        status, body = _get(
            server["base"], f"/api/runs/{server['run1_id']}",
        )
        assert status == 200
        assert body["id"] == server["run1_id"]
        assert body["status"] == "succeeded"
        assert body["backend_profile_slug"] == "claude_code"
        assert body["task_id"] == server["task_id"]

    def test_404_for_missing_run(self, server):
        status, body = _get(server["base"], "/api/runs/missing-id")
        assert status == 404
        assert body["error"] == "run_not_found"


# ── GET /api/runs/:id/events ────────────────────────────────────────


class TestRunEventsEndpoint:

    def test_returns_all_events_oldest_first(self, server):
        status, body = _get(
            server["base"],
            f"/api/runs/{server['run1_id']}/events",
        )
        assert status == 200
        assert [e["event_type"] for e in body] == [
            "system_init", "assistant_message", "tool_use",
            "tool_result", "result",
        ]
        # payload_json should survive as raw string
        assert isinstance(body[0]["payload_json"], str)

    def test_limit_param_caps_output(self, server):
        status, body = _get(
            server["base"],
            f"/api/runs/{server['run1_id']}/events?limit=2",
        )
        assert status == 200
        assert len(body) == 2
        assert body[0]["event_type"] == "system_init"

    def test_404_for_missing_run(self, server):
        status, body = _get(server["base"], "/api/runs/nope/events")
        assert status == 404
        assert body["error"] == "run_not_found"


# ── GET /api/tasks/:id/routing-decision ─────────────────────────────


class TestRoutingDecisionEndpoint:

    def test_returns_decision_with_resolved_chain(self, server):
        status, body = _get(
            server["base"],
            f"/api/tasks/{server['task_id']}/routing-decision",
        )
        assert status == 200
        assert body["id"] == server["rd_id"]
        assert body["selected_backend_slug"] == "claude_code"
        assert body["selected_backend_display_name"] == "Claude Code"
        assert body["reason_summary"] == (
            "Rule 'complex_to_claude' matched"
        )
        assert body["contract_version"] == "v02-assistant"
        assert [p["slug"] for p in body["fallback_chain"]] == [
            "claude_code", "codex",
        ]
        assert body["matched_rules"][0]["rule_name"] == (
            "complex_to_claude"
        )
        assert body["approval_required"] is False

    def test_404_when_no_decision(self, server):
        status, body = _get(
            server["base"],
            f"/api/tasks/{server['other_task_id']}/routing-decision",
        )
        assert status == 404
        assert body["error"] == "no_decision"

    def test_404_for_missing_task(self, server):
        status, body = _get(
            server["base"], "/api/tasks/nope/routing-decision",
        )
        assert status == 404
        assert body["error"] == "task_not_found"


# ── GET /api/runs/:id/artifacts (PR-10c) ────────────────────────────


class TestRunArtifactsEndpoint:

    def test_returns_all_artifacts_oldest_first(self, server):
        status, body = _get(
            server["base"],
            f"/api/runs/{server['run1_id']}/artifacts",
        )
        assert status == 200
        assert len(body) == 3
        assert [a["artifact_type"] for a in body] == [
            "code", "document", "log",
        ]
        # Order matches insertion (created_at + rowid tie-breaker).
        assert [a["id"] for a in body] == server["artifact_ids"]

    def test_paths_are_relative_not_absolute(self, server):
        """UI contract: paths must NEVER expose the host filesystem."""
        status, body = _get(
            server["base"],
            f"/api/runs/{server['run1_id']}/artifacts",
        )
        assert status == 200
        for a in body:
            assert not a["path"].startswith("/"), (
                f"path leaked absolute filesystem: {a['path']!r}"
            )

    def test_artifact_shape_includes_size_and_hash(self, server):
        status, body = _get(
            server["base"],
            f"/api/runs/{server['run1_id']}/artifacts",
        )
        assert status == 200
        first = body[0]
        assert first["size_bytes"] == 1024
        assert first["sha256"] == "a" * 64
        assert first["path"] == "src/main.py"
        assert first["backend_run_id"] == server["run1_id"]
        assert first["task_id"] == server["task_id"]
        assert isinstance(first["created_at"], str)

    def test_sha256_null_is_tolerated(self, server):
        """Bug 8 (sha256 may be NULL on early failure) — endpoint must
        still return the row without crashing."""
        status, body = _get(
            server["base"],
            f"/api/runs/{server['run1_id']}/artifacts",
        )
        assert status == 200
        log_row = next(a for a in body if a["artifact_type"] == "log")
        assert log_row["sha256"] is None
        assert log_row["size_bytes"] == 2048

    def test_empty_for_run_without_artifacts(self, server):
        """run2 has zero artifacts seeded."""
        status, body = _get(
            server["base"],
            f"/api/runs/{server['run2_id']}/artifacts",
        )
        assert status == 200
        assert body == []

    def test_404_for_missing_run(self, server):
        status, body = _get(
            server["base"], "/api/runs/nope/artifacts",
        )
        assert status == 404
        assert body["error"] == "run_not_found"


# ── Auth enforcement ────────────────────────────────────────────────


class TestAuthRequired:
    """When NIWA_APP_AUTH_REQUIRED=1 the endpoints must reject anon."""

    @pytest.fixture(scope="class")
    def auth_server(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        port = _free_port()
        os.environ["NIWA_DB_PATH"] = db_path
        os.environ["NIWA_APP_PORT"] = str(port)
        os.environ["NIWA_APP_AUTH_REQUIRED"] = "1"

        import app
        from pathlib import Path
        app.DB_PATH = Path(db_path)
        app.HOST = "127.0.0.1"
        app.PORT = port
        # Opposite of the module fixture: turn auth ON directly.
        app.NIWA_APP_AUTH_REQUIRED = True
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

        yield {"base": base}

        srv.shutdown()
        os.close(fd)
        os.unlink(db_path)
        # Restore auth-off for any later consumer of the app module.
        import app as _app
        _app.NIWA_APP_AUTH_REQUIRED = False
        os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"

    def test_list_runs_requires_auth(self, auth_server):
        status, body = _get(
            auth_server["base"], "/api/tasks/anything/runs",
        )
        assert status == 401
        assert body["error"] == "unauthorized"

    def test_get_run_requires_auth(self, auth_server):
        status, body = _get(auth_server["base"], "/api/runs/anything")
        assert status == 401

    def test_events_require_auth(self, auth_server):
        status, body = _get(
            auth_server["base"], "/api/runs/anything/events",
        )
        assert status == 401

    def test_routing_decision_requires_auth(self, auth_server):
        status, body = _get(
            auth_server["base"],
            "/api/tasks/anything/routing-decision",
        )
        assert status == 401

    def test_artifacts_require_auth(self, auth_server):
        status, body = _get(
            auth_server["base"], "/api/runs/anything/artifacts",
        )
        assert status == 401
