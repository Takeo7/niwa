"""Tests for PR-10a — read-only query helpers in runs_service.

Covers the four helpers that back the Web UI endpoints:
  - list_runs_for_task()
  - get_run_detail()
  - list_events_for_run()
  - get_routing_decision_for_task()

These helpers join with backend_profiles so the UI does not need
a second round-trip, and they bypass Bug 11 (which lives in
assistant_service._tool_run_explain) by reading the real
``reason_summary`` column.

Run: pytest tests/test_runs_service_read_queries.py -v
"""

import json
import os
import sqlite3
import sys
import tempfile
import uuid

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

import runs_service


# ── Fixtures ────────────────────────────────────────────────────────

@pytest.fixture()
def conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(open(SCHEMA_PATH).read())
    yield db
    db.close()
    os.close(fd)
    os.unlink(path)


@pytest.fixture()
def seeded(conn):
    """Seed one project, one task, two backend_profiles."""
    now = runs_service._now_iso()
    project_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    claude_id = str(uuid.uuid4())
    codex_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO projects (id, slug, name, area, description, "
        "active, created_at, updated_at) "
        "VALUES (?, 'proj', 'Proj', 'proyecto', '', 1, ?, ?)",
        (project_id, now, now),
    )
    conn.execute(
        "INSERT INTO tasks (id, title, area, status, priority, "
        "created_at, updated_at) "
        "VALUES (?, 'T', 'proyecto', 'pendiente', 'media', ?, ?)",
        (task_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, "
        "backend_kind, runtime_kind, enabled, priority, "
        "created_at, updated_at) "
        "VALUES (?, 'claude_code', 'Claude Code', 'claude_code', "
        "'cli', 1, 10, ?, ?)",
        (claude_id, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles (id, slug, display_name, "
        "backend_kind, runtime_kind, enabled, priority, "
        "created_at, updated_at) "
        "VALUES (?, 'codex', 'Codex', 'codex', 'cli', 1, 5, ?, ?)",
        (codex_id, now, now),
    )
    conn.commit()
    return {
        "project_id": project_id,
        "task_id": task_id,
        "claude_id": claude_id,
        "codex_id": codex_id,
    }


def _insert_routing_decision(conn, task_id, profile_id=None, **extras):
    now = runs_service._now_iso()
    rd_id = str(uuid.uuid4())
    decision_index = extras.pop("decision_index", 0)
    fallback_chain = extras.pop("fallback_chain", None)
    matched_rules = extras.pop("matched_rules", None)
    reason_summary = extras.pop("reason_summary", "test")
    contract_version = extras.pop("contract_version", None)
    conn.execute(
        "INSERT INTO routing_decisions "
        "(id, task_id, decision_index, selected_profile_id, "
        " reason_summary, matched_rules_json, fallback_chain_json, "
        " contract_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            rd_id, task_id, decision_index, profile_id,
            reason_summary,
            json.dumps(matched_rules) if matched_rules else None,
            json.dumps(fallback_chain) if fallback_chain else None,
            contract_version,
            now,
        ),
    )
    conn.commit()
    return rd_id


# ── list_runs_for_task ──────────────────────────────────────────────


class TestListRunsForTask:

    def test_returns_empty_list_when_no_runs(self, conn, seeded):
        rows = runs_service.list_runs_for_task(seeded["task_id"], conn)
        assert rows == []

    def test_orders_oldest_first(self, conn, seeded):
        rd_id = _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
        )
        first = runs_service.create_run(
            seeded["task_id"], rd_id, seeded["claude_id"], conn,
            backend_kind="claude_code", runtime_kind="cli",
        )
        # Force a distinct created_at timestamp
        import time as _t
        _t.sleep(1.1)
        second = runs_service.create_run(
            seeded["task_id"], rd_id, seeded["codex_id"], conn,
            previous_run_id=first["id"],
            relation_type="fallback",
            backend_kind="codex", runtime_kind="cli",
        )
        rows = runs_service.list_runs_for_task(seeded["task_id"], conn)
        assert [r["id"] for r in rows] == [first["id"], second["id"]]

    def test_joins_backend_profile_slug_and_display_name(self, conn, seeded):
        rd_id = _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
        )
        runs_service.create_run(
            seeded["task_id"], rd_id, seeded["claude_id"], conn,
            backend_kind="claude_code", runtime_kind="cli",
        )
        [run] = runs_service.list_runs_for_task(seeded["task_id"], conn)
        assert run["backend_profile_slug"] == "claude_code"
        assert run["backend_profile_display_name"] == "Claude Code"

    def test_preserves_relation_type(self, conn, seeded):
        rd_id = _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
        )
        first = runs_service.create_run(
            seeded["task_id"], rd_id, seeded["claude_id"], conn,
        )
        runs_service.create_run(
            seeded["task_id"], rd_id, seeded["codex_id"], conn,
            previous_run_id=first["id"],
            relation_type="fallback",
        )
        rows = runs_service.list_runs_for_task(seeded["task_id"], conn)
        assert rows[0]["relation_type"] is None
        assert rows[1]["relation_type"] == "fallback"
        assert rows[1]["previous_run_id"] == first["id"]


# ── get_run_detail ──────────────────────────────────────────────────


class TestGetRunDetail:

    def test_returns_none_when_missing(self, conn, seeded):
        assert runs_service.get_run_detail("nope", conn) is None

    def test_returns_joined_row(self, conn, seeded):
        rd_id = _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
        )
        created = runs_service.create_run(
            seeded["task_id"], rd_id, seeded["claude_id"], conn,
            backend_kind="claude_code", runtime_kind="cli",
            model_resolved="claude-sonnet-4-5",
        )
        detail = runs_service.get_run_detail(created["id"], conn)
        assert detail["id"] == created["id"]
        assert detail["backend_profile_slug"] == "claude_code"
        assert detail["backend_profile_display_name"] == "Claude Code"
        assert detail["status"] == "queued"
        assert detail["model_resolved"] == "claude-sonnet-4-5"


# ── list_events_for_run ─────────────────────────────────────────────


class TestListEventsForRun:

    def test_returns_empty_when_no_events(self, conn, seeded):
        rd_id = _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
        )
        run = runs_service.create_run(
            seeded["task_id"], rd_id, seeded["claude_id"], conn,
        )
        assert runs_service.list_events_for_run(run["id"], conn) == []

    def test_orders_oldest_first(self, conn, seeded):
        rd_id = _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
        )
        run = runs_service.create_run(
            seeded["task_id"], rd_id, seeded["claude_id"], conn,
        )
        runs_service.record_event(
            run["id"], "system_init", conn, message="init",
        )
        runs_service.record_event(
            run["id"], "assistant_message", conn, message="hi",
        )
        runs_service.record_event(
            run["id"], "result", conn, message="done",
        )
        events = runs_service.list_events_for_run(run["id"], conn)
        assert [e["event_type"] for e in events] == [
            "system_init", "assistant_message", "result",
        ]

    def test_limit_caps_output(self, conn, seeded):
        rd_id = _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
        )
        run = runs_service.create_run(
            seeded["task_id"], rd_id, seeded["claude_id"], conn,
        )
        for i in range(5):
            runs_service.record_event(
                run["id"], "tool_use", conn,
                message=f"step {i}",
                payload_json=json.dumps({"i": i}),
            )
        events = runs_service.list_events_for_run(
            run["id"], conn, limit=3,
        )
        assert len(events) == 3
        assert events[0]["message"] == "step 0"


# ── get_routing_decision_for_task ───────────────────────────────────


class TestGetRoutingDecisionForTask:

    def test_returns_none_when_no_decision(self, conn, seeded):
        assert runs_service.get_routing_decision_for_task(
            seeded["task_id"], conn,
        ) is None

    def test_returns_most_recent_decision(self, conn, seeded):
        _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
            decision_index=0, reason_summary="first",
        )
        import time as _t; _t.sleep(1.1)
        rd2 = _insert_routing_decision(
            conn, seeded["task_id"], seeded["codex_id"],
            decision_index=1, reason_summary="second",
        )
        got = runs_service.get_routing_decision_for_task(
            seeded["task_id"], conn,
        )
        assert got["id"] == rd2
        assert got["reason_summary"] == "second"

    def test_resolves_fallback_chain(self, conn, seeded):
        _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
            fallback_chain=[seeded["claude_id"], seeded["codex_id"]],
            matched_rules=[{"rule": "user_pin", "slug": "claude_code"}],
            contract_version="v02-assistant",
        )
        got = runs_service.get_routing_decision_for_task(
            seeded["task_id"], conn,
        )
        assert got["selected_backend_slug"] == "claude_code"
        assert got["selected_backend_display_name"] == "Claude Code"
        assert got["contract_version"] == "v02-assistant"
        assert [p["slug"] for p in got["fallback_chain"]] == [
            "claude_code", "codex",
        ]
        assert got["matched_rules"] == [
            {"rule": "user_pin", "slug": "claude_code"},
        ]

    def test_handles_deleted_profile_in_fallback_chain(self, conn, seeded):
        bogus_id = str(uuid.uuid4())
        _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
            fallback_chain=[seeded["claude_id"], bogus_id],
        )
        got = runs_service.get_routing_decision_for_task(
            seeded["task_id"], conn,
        )
        assert got["fallback_chain"][0]["slug"] == "claude_code"
        assert got["fallback_chain"][1]["id"] == bogus_id
        assert got["fallback_chain"][1]["slug"] is None

    def test_surfaces_pending_approval(self, conn, seeded):
        _insert_routing_decision(
            conn, seeded["task_id"], None,  # no backend selected
            reason_summary="capability denied",
        )
        now = runs_service._now_iso()
        approval_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO approvals "
            "(id, task_id, approval_type, reason, risk_level, "
            " status, requested_at) "
            "VALUES (?, ?, 'capability_denied', 'x', 'medium', "
            "        'pending', ?)",
            (approval_id, seeded["task_id"], now),
        )
        conn.commit()
        got = runs_service.get_routing_decision_for_task(
            seeded["task_id"], conn,
        )
        assert got["approval_required"] is True
        assert got["approval"]["id"] == approval_id
        assert got["approval"]["status"] == "pending"

    def test_reason_summary_read_directly_bypasses_bug_11(
        self, conn, seeded,
    ):
        """Bug 11: _tool_run_explain reads ``reason_summary_json`` which
        doesn't exist.  This helper reads the real column, so reason
        arrives populated.
        """
        _insert_routing_decision(
            conn, seeded["task_id"], seeded["claude_id"],
            reason_summary="Rule 'complex_to_claude' matched",
        )
        got = runs_service.get_routing_decision_for_task(
            seeded["task_id"], conn,
        )
        assert got["reason_summary"] == "Rule 'complex_to_claude' matched"
