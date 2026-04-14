"""Tests for PR-10b HTTP endpoints — approvals read + resolve.

Covers:
  - GET  /api/approvals                     (optional ?status filter)
  - GET  /api/tasks/:id/approvals           (all statuses for a task)
  - GET  /api/approvals/:id                 (single enriched approval)
  - POST /api/approvals/:id/resolve         (approve / reject)

Each endpoint tested for: auth enforcement, 404 on missing resource,
happy path with joined shape, edge cases of the resolve flow
(idempotency, conflict, invalid decision, 400 / 409 semantics).

Run: pytest tests/test_approvals_endpoints.py -v
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


def _post(base, path, body, **kw):
    return _request(base, path, method="POST", body=body, **kw)


@pytest.fixture
def server():
    """Per-test server so each test gets a fresh DB.

    Approvals mutate state (resolve → status change) and we want
    every test to start from the same seed without relying on the
    ordering of the pytest runner.
    """
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
    # Force-override: NIWA_APP_AUTH_REQUIRED is read at import time.
    app.NIWA_APP_AUTH_REQUIRED = False
    app.init_db()

    # Seed: project, two tasks, two runs (one approval pre-routing
    # without backend_run_id, one runtime approval with backend_run_id),
    # a resolved approval and a second pending.
    import approval_service
    conn = app.db_conn()
    now = app.now_iso()

    project_id = str(uuid.uuid4())
    task_a = str(uuid.uuid4())
    task_b = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO projects (id, slug, name, area, created_at, "
        "updated_at) VALUES (?, 'p', 'P', 'proyecto', ?, ?)",
        (project_id, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, "
        "created_at, updated_at) "
        "VALUES (?, 'Task A', 'proyecto', 'en_progreso', 'media', ?, ?)",
        (task_a, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, "
        "created_at, updated_at) "
        "VALUES (?, 'Task B', 'proyecto', 'pendiente', 'media', ?, ?)",
        (task_b, now, now),
    )
    conn.execute("DELETE FROM backend_profiles")
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, "
        "backend_kind, runtime_kind, enabled, priority, "
        "capabilities_json, created_at, updated_at) "
        "VALUES (?, 'claude_code', 'Claude Code', 'claude_code', "
        "'cli', 1, 10, '{}', ?, ?)",
        (profile_id, now, now),
    )
    conn.execute(
        "INSERT INTO routing_decisions (id, task_id, decision_index, "
        "selected_profile_id, created_at) VALUES (?, ?, 0, ?, ?)",
        (rd_id, task_a, profile_id, now),
    )
    conn.execute(
        "INSERT INTO backend_runs (id, task_id, routing_decision_id, "
        "backend_profile_id, backend_kind, runtime_kind, status, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'claude_code', 'cli', 'waiting_approval', "
        "        ?, ?)",
        (run_id, task_a, rd_id, profile_id, now, now),
    )
    conn.commit()

    # Three approvals:
    #   runtime_pending  — task_a, has backend_run_id, newest
    #   pre_routing      — task_a, backend_run_id=None (PR-06 Dec 5)
    #   resolved_other   — task_b, already approved
    runtime_ap = approval_service.request_approval(
        task_a, run_id, "shell_not_whitelisted",
        "Se intentó ejecutar 'rm -rf /tmp/cache' fuera de la whitelist. "
        "El agente necesita purgar el cache antes del build.",
        "high", conn,
    )
    time.sleep(1.1)
    pre_routing_ap = approval_service.request_approval(
        task_a, None, "quota_risk_high",
        "El router estimó quota_risk=high antes de seleccionar backend.",
        "medium", conn,
    )
    time.sleep(1.1)
    other_ap = approval_service.request_approval(
        task_b, None, "deletion",
        "Borrado de artifact fuera de workspace.",
        "low", conn,
    )
    approval_service.resolve_approval(
        other_ap["id"], "approved", "tester", conn,
        resolution_note="Aprobado para el test",
    )
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
        "task_a": task_a,
        "task_b": task_b,
        "run_id": run_id,
        "runtime_ap": runtime_ap["id"],
        "pre_routing_ap": pre_routing_ap["id"],
        "other_ap": other_ap["id"],
        "db_path": db_path,
    }

    srv.shutdown()
    os.close(fd)
    os.unlink(db_path)


# ── GET /api/approvals ───────────────────────────────────────────────


class TestListApprovalsEndpoint:

    def test_returns_all_approvals_newest_first(self, server):
        status, body = _get(server["base"], "/api/approvals")
        assert status == 200
        # Three seeded approvals, ordered requested_at DESC.
        ids = [a["id"] for a in body]
        assert set(ids) == {
            server["runtime_ap"], server["pre_routing_ap"],
            server["other_ap"],
        }
        # other_ap was created last → comes first.
        assert ids[0] == server["other_ap"]

    def test_filter_by_status_pending(self, server):
        status, body = _get(
            server["base"], "/api/approvals?status=pending",
        )
        assert status == 200
        ids = {a["id"] for a in body}
        assert ids == {server["runtime_ap"], server["pre_routing_ap"]}
        for a in body:
            assert a["status"] == "pending"

    def test_filter_by_status_approved(self, server):
        status, body = _get(
            server["base"], "/api/approvals?status=approved",
        )
        assert status == 200
        assert len(body) == 1
        assert body[0]["id"] == server["other_ap"]
        assert body[0]["status"] == "approved"
        assert body[0]["resolved_by"] == "tester"

    def test_empty_status_param_behaves_like_no_filter(self, server):
        status, body = _get(server["base"], "/api/approvals?status=")
        assert status == 200
        assert len(body) == 3

    def test_payload_includes_task_join(self, server):
        status, body = _get(server["base"], "/api/approvals")
        assert status == 200
        by_id = {a["id"]: a for a in body}
        assert by_id[server["runtime_ap"]]["task_title"] == "Task A"
        assert by_id[server["pre_routing_ap"]]["task_title"] == "Task A"
        assert by_id[server["other_ap"]]["task_title"] == "Task B"

    def test_pre_routing_approval_has_null_run(self, server):
        # PR-06 Decisión 5: approvals pre-routing carry
        # backend_run_id=None.  The UI contract must preserve that.
        status, body = _get(server["base"], "/api/approvals")
        assert status == 200
        pre = next(
            a for a in body if a["id"] == server["pre_routing_ap"]
        )
        assert pre["backend_run_id"] is None

    def test_runtime_approval_carries_run(self, server):
        status, body = _get(server["base"], "/api/approvals")
        assert status == 200
        runtime = next(
            a for a in body if a["id"] == server["runtime_ap"]
        )
        assert runtime["backend_run_id"] == server["run_id"]


# ── GET /api/tasks/:id/approvals ─────────────────────────────────────


class TestTaskApprovalsEndpoint:

    def test_returns_approvals_for_task(self, server):
        status, body = _get(
            server["base"],
            f"/api/tasks/{server['task_a']}/approvals",
        )
        assert status == 200
        ids = {a["id"] for a in body}
        assert ids == {server["runtime_ap"], server["pre_routing_ap"]}

    def test_includes_resolved_approvals(self, server):
        status, body = _get(
            server["base"],
            f"/api/tasks/{server['task_b']}/approvals",
        )
        assert status == 200
        assert len(body) == 1
        assert body[0]["id"] == server["other_ap"]
        assert body[0]["status"] == "approved"

    def test_404_for_missing_task(self, server):
        status, body = _get(
            server["base"], "/api/tasks/nope/approvals",
        )
        assert status == 404
        assert body["error"] == "task_not_found"

    def test_empty_for_task_without_approvals(self, server):
        # Create a third task with no approvals via the DB directly.
        import app
        conn = app.db_conn()
        now = app.now_iso()
        empty_task = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tasks (id, title, area, status, priority, "
            "created_at, updated_at) VALUES "
            "(?, 'Empty', 'proyecto', 'pendiente', 'media', ?, ?)",
            (empty_task, now, now),
        )
        conn.commit()
        conn.close()
        status, body = _get(
            server["base"],
            f"/api/tasks/{empty_task}/approvals",
        )
        assert status == 200
        assert body == []


# ── GET /api/approvals/:id ──────────────────────────────────────────


class TestGetApprovalEndpoint:

    def test_returns_enriched_approval(self, server):
        status, body = _get(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}",
        )
        assert status == 200
        assert body["id"] == server["runtime_ap"]
        assert body["task_title"] == "Task A"
        assert body["status"] == "pending"
        assert body["backend_run_id"] == server["run_id"]

    def test_404_for_missing(self, server):
        status, body = _get(server["base"], "/api/approvals/missing-id")
        assert status == 404
        assert body["error"] == "approval_not_found"


# ── POST /api/approvals/:id/resolve ─────────────────────────────────


class TestResolveApprovalEndpoint:

    def test_approve_pending_approval(self, server):
        status, body = _post(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}/resolve",
            {"decision": "approve", "resolution_note": "OK, procede"},
        )
        assert status == 200
        assert body["id"] == server["runtime_ap"]
        assert body["status"] == "approved"
        assert body["resolution_note"] == "OK, procede"
        assert body["resolved_at"] is not None
        # resolved_by is the session user (NIWA_APP_USERNAME).
        assert body["resolved_by"]

    def test_reject_pending_approval(self, server):
        status, body = _post(
            server["base"],
            f"/api/approvals/{server['pre_routing_ap']}/resolve",
            {"decision": "reject"},
        )
        assert status == 200
        assert body["status"] == "rejected"
        # resolution_note is optional; omitting sends null.
        assert body["resolution_note"] is None

    def test_invalid_decision_returns_400(self, server):
        status, body = _post(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}/resolve",
            {"decision": "maybe"},
        )
        assert status == 400
        assert body["error"] == "invalid_decision"

    def test_missing_decision_returns_400(self, server):
        status, body = _post(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}/resolve",
            {},
        )
        assert status == 400
        assert body["error"] == "invalid_decision"

    def test_resolving_missing_approval_returns_404(self, server):
        status, body = _post(
            server["base"],
            "/api/approvals/does-not-exist/resolve",
            {"decision": "approve"},
        )
        assert status == 404
        assert body["error"] == "approval_not_found"

    def test_double_resolve_same_decision_is_idempotent(self, server):
        # First resolution.
        status1, body1 = _post(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}/resolve",
            {"decision": "approve"},
        )
        assert status1 == 200
        # Repeat with same decision — should succeed without error
        # (approval_service.resolve_approval is idempotent).
        status2, body2 = _post(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}/resolve",
            {"decision": "approve"},
        )
        assert status2 == 200
        assert body2["status"] == "approved"
        assert body2["resolved_at"] == body1["resolved_at"]

    def test_conflict_when_changing_resolution(self, server):
        # Resolve as approved first.
        status1, _ = _post(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}/resolve",
            {"decision": "approve"},
        )
        assert status1 == 200
        # Attempting to reject afterwards conflicts.
        status2, body2 = _post(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}/resolve",
            {"decision": "reject"},
        )
        assert status2 == 409
        assert body2["error"] == "approval_conflict"

    def test_whitespace_only_note_is_normalised_to_null(self, server):
        status, body = _post(
            server["base"],
            f"/api/approvals/{server['runtime_ap']}/resolve",
            {"decision": "approve", "resolution_note": "   "},
        )
        assert status == 200
        assert body["resolution_note"] is None


# ── Auth enforcement ────────────────────────────────────────────────


class TestAuthRequired:
    """When NIWA_APP_AUTH_REQUIRED=1 all endpoints reject anon."""

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
        import app as _app
        _app.NIWA_APP_AUTH_REQUIRED = False
        os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"

    def test_list_requires_auth(self, auth_server):
        status, body = _get(auth_server["base"], "/api/approvals")
        assert status == 401
        assert body["error"] == "unauthorized"

    def test_task_list_requires_auth(self, auth_server):
        status, body = _get(
            auth_server["base"], "/api/tasks/anything/approvals",
        )
        assert status == 401

    def test_get_requires_auth(self, auth_server):
        status, body = _get(
            auth_server["base"], "/api/approvals/anything",
        )
        assert status == 401

    def test_resolve_requires_auth(self, auth_server):
        status, body = _post(
            auth_server["base"],
            "/api/approvals/anything/resolve",
            {"decision": "approve"},
        )
        assert status == 401
