"""Tests for PR-10a — contract between backend_run_events and the
frontend Timeline.

Verifies that the seven canonical event_types documented in PR-04
Decisión 7 (system_init, assistant_message, tool_use, tool_result,
result, error, raw_output) arrive via GET /api/runs/:id/events with
the payload shape the frontend's extractTitle() relies on, and that
the helper never returns an empty string for any of them.

``extractTitle_py`` below is a Python port of
``niwa-app/frontend/src/features/runs/components/RunTimeline.tsx``
(``extractTitle``).  Any change to the TS rules must be mirrored
here — the test acts as a contract pin.

Payloads are modelled after the real stream-json shapes captured in
``tests/fixtures/fake_claude.py`` (PR-04), with minor additions for
event_types the fixture does not emit (error, raw_output,
fallback_escalation).

Run: pytest tests/test_run_events_contract.py -v
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

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


# ── Python mirror of extractTitle (frontend) ────────────────────────
#
# IMPORTANT: Keep in sync with
# niwa-app/frontend/src/features/runs/components/RunTimeline.tsx
# The two constants and per-type branches must mirror the TS rules
# exactly — this test is the contract pin between them.

RAW_SENTINEL = "(raw event)"
UNPARSABLE_SENTINEL = "(unparsable payload)"


def _str(v):
    return v if isinstance(v, str) and len(v) > 0 else None


def extract_title_py(event_type: str, payload_json: str | None):
    if event_type == "raw_output":
        return None
    if not payload_json:
        return RAW_SENTINEL
    try:
        parsed = json.loads(payload_json)
    except (ValueError, TypeError):
        return UNPARSABLE_SENTINEL
    if not isinstance(parsed, dict):
        return RAW_SENTINEL
    p = parsed

    if event_type.startswith("system"):
        subtype = _str(p.get("subtype"))
        model = _str(p.get("model"))
        session = _str(p.get("session_id"))
        if subtype and model:
            return f"{subtype} · {model}"
        if subtype:
            return subtype
        if model:
            return model
        if session:
            return f"session {session[:8]}"
        return RAW_SENTINEL

    if event_type == "assistant_message":
        content = p.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = _str(block.get("text"))
                    if text:
                        first_line = text.split("\n")[0].strip()
                        if len(first_line) > 120:
                            return first_line[:117] + "…"
                        return first_line
        return RAW_SENTINEL

    if event_type == "tool_use":
        return (
            _str(p.get("tool_name"))
            or _str(p.get("name"))
            or _str(p.get("tool"))
            or RAW_SENTINEL
        )

    if event_type == "tool_result":
        content = p.get("content")
        if isinstance(content, str) and len(content) > 0:
            one_line = " ".join(content.split())
            if len(one_line) > 120:
                return one_line[:117] + "…"
            return one_line
        if isinstance(content, list) and len(content) > 0:
            return f"{len(content)} block(s)"
        return RAW_SENTINEL

    if event_type == "result":
        cost = p.get("cost_usd")
        model = _str(p.get("model"))
        cost_str = f"${cost:.4f}" if isinstance(cost, (int, float)) else None
        if cost_str and model:
            return f"{cost_str} · {model}"
        if cost_str:
            return cost_str
        if model:
            return model
        return RAW_SENTINEL

    if event_type == "error":
        err = p.get("error")
        if isinstance(err, dict):
            et = _str(err.get("type"))
            em = _str(err.get("message"))
            if et and em:
                return f"{et}: {em[:100]}"
            if em:
                return em[:120]
            if et:
                return et
        flat = _str(p.get("message"))
        if flat:
            return flat[:120]
        return RAW_SENTINEL

    if event_type == "fallback_escalation":
        frm = _str(p.get("from_slug")) or _str(p.get("from"))
        to = _str(p.get("to_slug")) or _str(p.get("to"))
        if frm and to:
            return f"{frm} → {to}"
        return RAW_SENTINEL

    return RAW_SENTINEL


# ── Canonical payloads for the 7 PR-04 Dec 7 event_types ────────────
#
# Payloads mirror real stream-json shapes from
# tests/fixtures/fake_claude.py.  event_types the fixture does not
# emit (error with structured .type, raw_output, fallback_escalation)
# use plausible shapes consistent with the adapter code
# (niwa-app/backend/backend_adapters/claude_code.py::_classify_event).

CANONICAL_EVENTS = [
    # (event_type, payload_dict_or_None, message_column, expected_sub_in_title)
    (
        "system_init",
        {
            "type": "system",
            "subtype": "init",
            "session_id": "fake-session-001",
            "model": "claude-sonnet-4-6",
            "tools": ["Read", "Write", "Bash"],
        },
        "System event",
        "init",
    ),
    (
        "assistant_message",
        {
            "content": [
                {"type": "text", "text": "Working on: build the feature\nsecond line"},
            ],
        },
        "Working on: build the feature",
        "Working on",
    ),
    (
        "tool_use",
        {
            "tool_name": "Bash",
            "input": {"command": "echo done"},
        },
        "Tool call: Bash",
        "Bash",
    ),
    (
        "tool_result",
        {"content": "done\nwith\nthree lines"},
        "done",
        "done",
    ),
    (
        "result",
        {
            "type": "result",
            "subtype": "success",
            "session_id": "fake-session-001",
            "cost_usd": 0.042,
            "duration_ms": 5200,
            "num_turns": 2,
            "is_error": False,
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 1500,
                "output_tokens": 800,
            },
        },
        "Execution completed (cost=0.042)",
        "claude-sonnet-4-6",
    ),
    (
        "error",
        {
            "type": "error",
            "error": {
                "type": "rate_limit",
                "message": "Too many requests",
            },
        },
        "Too many requests",
        "rate_limit",
    ),
    (
        "raw_output",
        None,
        "garbage-non-json line",
        None,  # raw_output title is None on purpose
    ),
]


# ── Server fixture (same pattern as test_runs_endpoints.py) ─────────

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _get_json(base, path):
    req = Request(f"{base}{path}", method="GET")
    with urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read())


@pytest.fixture(scope="module")
def server_with_7_events():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    port = _free_port()
    os.environ["NIWA_DB_PATH"] = db_path
    os.environ["NIWA_APP_PORT"] = str(port)
    os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"

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

    project_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    profile_id = str(uuid.uuid4())
    rd_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    conn.execute(
        "INSERT INTO projects (id, slug, name, area, description, "
        "active, created_at, updated_at) "
        "VALUES (?, 'p', 'P', 'proyecto', '', 1, ?, ?)",
        (project_id, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, "
        "created_at, updated_at) "
        "VALUES (?, 'T', 'proyecto', 'en_progreso', 'media', ?, ?)",
        (task_id, now, now),
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
        "INSERT INTO routing_decisions "
        "(id, task_id, decision_index, selected_profile_id, "
        " reason_summary, created_at) "
        "VALUES (?, ?, 0, ?, 'test', ?)",
        (rd_id, task_id, profile_id, now),
    )
    conn.execute(
        "INSERT INTO backend_runs "
        "(id, task_id, routing_decision_id, backend_profile_id, "
        " backend_kind, runtime_kind, status, "
        " created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'claude_code', 'cli', 'running', ?, ?)",
        (run_id, task_id, rd_id, profile_id, now, now),
    )
    # Insert events in the canonical order.  Use ``record_event`` so
    # the rowid secondary ordering matches what the real adapter
    # produces.
    import runs_service
    for event_type, payload, message, _ in CANONICAL_EVENTS:
        runs_service.record_event(
            run_id,
            event_type,
            conn,
            message=message,
            payload_json=json.dumps(payload) if payload is not None else None,
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

    yield {"base": base, "run_id": run_id}

    srv.shutdown()
    os.close(fd)
    os.unlink(db_path)


# ── Contract tests ──────────────────────────────────────────────────


class TestSevenEventTypesContract:
    """Each of the seven PR-04 Dec 7 event_types survives the HTTP
    round-trip with its payload intact, and extractTitle never
    returns an empty string."""

    def test_all_seven_types_returned_in_order(self, server_with_7_events):
        status, events = _get_json(
            server_with_7_events["base"],
            f"/api/runs/{server_with_7_events['run_id']}/events",
        )
        assert status == 200
        assert len(events) == len(CANONICAL_EVENTS)
        got_types = [e["event_type"] for e in events]
        expected_types = [c[0] for c in CANONICAL_EVENTS]
        assert got_types == expected_types

    def test_payload_shape_round_trips_intact(self, server_with_7_events):
        """HTTP response preserves payload_json verbatim so the
        frontend parses the same structure the adapter emitted."""
        _, events = _get_json(
            server_with_7_events["base"],
            f"/api/runs/{server_with_7_events['run_id']}/events",
        )
        assert len(events) == len(CANONICAL_EVENTS)
        for canonical, got in zip(CANONICAL_EVENTS, events):
            event_type, payload_expected, message_expected, _ = canonical
            assert got["event_type"] == event_type
            assert got["message"] == message_expected
            if payload_expected is None:
                assert got["payload_json"] is None
            else:
                # payload_json is a string.  Parse it and deep-equal
                # to the canonical dict.
                got_payload = json.loads(got["payload_json"])
                assert got_payload == payload_expected

    @pytest.mark.parametrize(
        "canonical",
        CANONICAL_EVENTS,
        ids=[c[0] for c in CANONICAL_EVENTS],
    )
    def test_extract_title_never_returns_empty(
        self, server_with_7_events, canonical,
    ):
        """Run the Python mirror of the TS extractTitle against each
        shape.  None is permitted ONLY for raw_output (which carries
        no payload)."""
        event_type, payload, _, expected_substr = canonical
        payload_json = (
            json.dumps(payload) if payload is not None else None
        )
        title = extract_title_py(event_type, payload_json)

        if event_type == "raw_output":
            assert title is None
            return

        assert title is not None, f"{event_type}: title is None"
        assert isinstance(title, str)
        assert title != "", f"{event_type}: empty title"
        # Sentinel leaks on recognised event_types would mean we
        # added a new type here without teaching extractTitle about
        # it — guard against that.
        assert title != RAW_SENTINEL, (
            f"{event_type}: extractTitle fell through to "
            f"{RAW_SENTINEL!r} despite payload being shaped."
        )
        if expected_substr:
            assert expected_substr in title, (
                f"{event_type}: expected {expected_substr!r} in "
                f"title, got {title!r}"
            )

    def test_malformed_payload_returns_unparsable_sentinel(self):
        """Guard: JSON-but-not-parseable payload never crashes and
        never returns empty string."""
        title = extract_title_py("tool_use", "not{valid}json}}}")
        assert title == UNPARSABLE_SENTINEL

    def test_unknown_event_type_returns_raw_sentinel(self):
        """If the adapter emits a new event_type the frontend does
        not recognise, title is (raw event), never empty."""
        title = extract_title_py(
            "future_event_type_we_dont_know",
            json.dumps({"arbitrary": "shape"}),
        )
        assert title == RAW_SENTINEL

    def test_null_payload_with_unknown_type_still_returns_sentinel(self):
        """Event with no payload and unknown type gets the sentinel
        (not None, not empty).  Only raw_output is allowed to return
        None."""
        title = extract_title_py("unknown_type", None)
        assert title == RAW_SENTINEL

    def test_tool_use_alternate_field_name(self):
        """Older PR-04 snapshots used ``name`` instead of
        ``tool_name``.  Both must be accepted, neither empty."""
        t1 = extract_title_py(
            "tool_use", json.dumps({"name": "Read", "input": {}}),
        )
        t2 = extract_title_py(
            "tool_use", json.dumps({"tool": "Edit", "input": {}}),
        )
        assert t1 == "Read"
        assert t2 == "Edit"

    def test_fallback_escalation_from_to(self):
        t = extract_title_py(
            "fallback_escalation",
            json.dumps({"from_slug": "claude_code", "to_slug": "codex"}),
        )
        assert t == "claude_code → codex"
