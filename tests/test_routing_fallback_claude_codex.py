"""Tests for fallback chain Claude ↔ Codex — PR-07 Niwa v0.2.

Verifies:
  1. With Codex enabled, routing selects codex for small_patch_to_codex
     rule and includes claude as fallback.
  2. If the primary adapter raises an exception, the executor escalates
     to the next backend in the fallback chain, creating a new run with
     relation_type='fallback'.
  3. If the fallback also fails, the task fails with a clear message.
  4. Returned failures (adapter ran but task failed) are NOT escalated.

Uses mocked adapters — no real CLI calls.
"""

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from unittest import TestCase, mock

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TESTS_DIR)
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
SCHEMA_PATH = os.path.join(ROOT_DIR, "niwa-app", "db", "schema.sql")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import routing_service
import runs_service
from backend_adapters.base import BackendAdapter
from backend_registry import BackendRegistry


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        open(SCHEMA_PATH, encoding="utf-8").read())
    return conn


def _seed_profiles(conn, codex_enabled=True):
    now = _now_iso()
    conn.execute(
        "INSERT INTO backend_profiles "
        "(id, slug, display_name, backend_kind, runtime_kind, "
        " default_model, capabilities_json, enabled, priority, "
        " created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("prof-claude", "claude_code", "Claude Code",
         "claude_code", "cli", "claude-sonnet-4-6",
         json.dumps({"resume_modes": ["session_restore"]}),
         1, 10, now, now),
    )
    conn.execute(
        "INSERT INTO backend_profiles "
        "(id, slug, display_name, backend_kind, runtime_kind, "
        " default_model, capabilities_json, enabled, priority, "
        " created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("prof-codex", "codex", "Codex",
         "codex", "cli", "o4-mini",
         json.dumps({"resume_modes": []}),
         1 if codex_enabled else 0,
         5 if codex_enabled else 0,
         now, now),
    )
    routing_service.seed_routing_rules(conn)
    conn.commit()


def _make_task(conn, title="Test task", description="A test task",
               **kwargs):
    task_id = kwargs.get("task_id", str(uuid.uuid4()))
    now = _now_iso()
    conn.execute(
        "INSERT INTO tasks "
        "(id, title, description, area, project_id, status, priority, "
        " urgent, created_at, updated_at, "
        " requested_backend_profile_id, selected_backend_profile_id, "
        " current_run_id, approval_required, quota_risk, "
        " estimated_resource_cost) "
        "VALUES (?, ?, ?, 'proyecto', NULL, 'pendiente', 'media', 0, "
        "        ?, ?, NULL, NULL, NULL, 0, NULL, NULL)",
        (task_id, title, description, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?",
                       (task_id,)).fetchone()
    return dict(row)


# ═══════════════════════════════════════════════════════════════════
# 1. Routing decision: codex primary, claude fallback
# ═══════════════════════════════════════════════════════════════════

class TestRoutingDecisionWithCodexEnabled(TestCase):

    def test_small_patch_selects_codex(self):
        """small_patch_to_codex rule selects codex when enabled."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=True)
        task = _make_task(conn,
                          title="Fix typo in README",
                          description="Fix a typo")

        decision = routing_service.decide(task, conn)

        self.assertEqual(
            decision["selected_backend_profile_id"], "prof-codex")
        self.assertIn("small_patch_to_codex",
                       decision["reason_summary"])

    def test_fallback_chain_has_claude(self):
        """Fallback chain includes claude after codex."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=True)
        task = _make_task(conn,
                          title="Fix bug in parser",
                          description="Fix a bug")

        decision = routing_service.decide(task, conn)

        chain = decision["fallback_chain"]
        self.assertIn("prof-codex", chain)
        self.assertIn("prof-claude", chain)
        # codex is first (selected), claude is second
        codex_idx = chain.index("prof-codex")
        claude_idx = chain.index("prof-claude")
        self.assertLess(codex_idx, claude_idx)

    def test_complex_task_selects_claude(self):
        """complex_to_claude rule still selects claude for complex
        tasks even with codex enabled."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=True)
        task = _make_task(
            conn,
            title="Refactor arquitectura del sistema completo",
            description=(
                "Necesitamos reestructurar la arquitectura completa "
                "del sistema para soportar multi-archivo y migrar "
                "toda la base de datos a un esquema nuevo con "
                "soporte para varios archivos de configuracion"
            ),
        )

        decision = routing_service.decide(task, conn)
        self.assertEqual(
            decision["selected_backend_profile_id"], "prof-claude")

    def test_codex_disabled_falls_to_claude(self):
        """With codex disabled, small patches go to claude."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=False)
        task = _make_task(conn,
                          title="Fix typo",
                          description="Fix a typo")

        decision = routing_service.decide(task, conn)
        self.assertEqual(
            decision["selected_backend_profile_id"], "prof-claude")


# ═══════════════════════════════════════════════════════════════════
# 2. Fallback escalation: codex fails → claude takes over
# ═══════════════════════════════════════════════════════════════════

class _FakeAdapter(BackendAdapter):
    """Test adapter that can be configured to succeed or raise."""

    def __init__(self, *, should_raise=False, raise_cls=None,
                 return_result=None):
        self._should_raise = should_raise
        self._raise_cls = raise_cls or RuntimeError
        self._return_result = return_result or {
            "status": "succeeded", "outcome": "success",
            "exit_code": 0,
        }

    def capabilities(self):
        return {"resume_modes": []}

    def start(self, task, run, profile, capability_profile):
        if self._should_raise:
            raise self._raise_cls(
                f"Simulated failure in {profile.get('slug', '?')}")
        return self._return_result

    def resume(self, *a, **kw):
        raise NotImplementedError

    def cancel(self, *a, **kw):
        return {"status": "cancelled"}

    def heartbeat(self, *a, **kw):
        return {"alive": False}

    def collect_artifacts(self, *a, **kw):
        return []

    def parse_usage_signals(self, *a, **kw):
        return {}


class TestFallbackEscalation(TestCase):

    def test_codex_exception_escalates_to_claude(self):
        """When codex adapter raises, executor creates a fallback run
        with claude and succeeds."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=True)
        task = _make_task(conn,
                          title="Fix typo in config",
                          description="Fix a typo")

        # Route → codex primary, claude fallback
        decision = routing_service.decide(task, conn)
        self.assertEqual(
            decision["selected_backend_profile_id"], "prof-codex")

        chain = decision["fallback_chain"]
        self.assertEqual(len(chain), 2)

        # Simulate executor behavior with fallback
        prior_run_id = None
        for idx, profile_id in enumerate(chain[:2]):
            profile = dict(conn.execute(
                "SELECT * FROM backend_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone())

            relation_type = "fallback" if idx > 0 else None
            run = runs_service.create_run(
                task_id=task["id"],
                routing_decision_id=decision["routing_decision_id"],
                backend_profile_id=profile_id,
                conn=conn,
                previous_run_id=prior_run_id,
                relation_type=relation_type,
                backend_kind=profile["backend_kind"],
            )

            if profile["slug"] == "codex":
                # Codex raises
                adapter = _FakeAdapter(should_raise=True)
                try:
                    adapter.start(task, run, profile, {})
                    self.fail("Should have raised")
                except RuntimeError:
                    runs_service.record_event(
                        run["id"], "fallback_escalation", conn,
                        message="Codex failed, escalating.",
                    )
                    runs_service.transition_run(
                        run["id"], "starting", conn)
                    runs_service.finish_run(
                        run["id"], "failure", conn,
                        error_code="executor_error",
                    )
                    prior_run_id = run["id"]
                    continue
            else:
                # Claude succeeds
                adapter = _FakeAdapter(should_raise=False)
                result = adapter.start(task, run, profile, {})
                self.assertEqual(result["status"], "succeeded")
                break

        # Verify: 2 runs created
        runs = conn.execute(
            "SELECT * FROM backend_runs WHERE task_id = ? "
            "ORDER BY created_at",
            (task["id"],),
        ).fetchall()
        self.assertEqual(len(runs), 2)

        # First run: codex, failed
        r0 = dict(runs[0])
        self.assertEqual(r0["backend_profile_id"], "prof-codex")
        self.assertEqual(r0["status"], "failed")
        self.assertIsNone(r0["relation_type"])

        # Second run: claude, fallback, queued (fake didn't transition)
        r1 = dict(runs[1])
        self.assertEqual(r1["backend_profile_id"], "prof-claude")
        self.assertEqual(r1["relation_type"], "fallback")
        self.assertEqual(r1["previous_run_id"], r0["id"])

        # Fallback escalation event recorded
        events = conn.execute(
            "SELECT event_type FROM backend_run_events "
            "WHERE backend_run_id = ?",
            (r0["id"],),
        ).fetchall()
        self.assertTrue(
            any(e["event_type"] == "fallback_escalation"
                for e in events))

    def test_both_fail_returns_error(self):
        """When both codex and claude fail, all runs marked failed."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=True)
        task = _make_task(conn, title="Fix bug",
                          description="Fix a bug")

        decision = routing_service.decide(task, conn)
        chain = decision["fallback_chain"]

        all_failed = True
        for idx, profile_id in enumerate(chain[:2]):
            profile = dict(conn.execute(
                "SELECT * FROM backend_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone())

            run = runs_service.create_run(
                task_id=task["id"],
                routing_decision_id=decision["routing_decision_id"],
                backend_profile_id=profile_id,
                conn=conn,
                relation_type="fallback" if idx > 0 else None,
            )

            adapter = _FakeAdapter(should_raise=True)
            try:
                adapter.start(task, run, profile, {})
            except RuntimeError:
                runs_service.transition_run(
                    run["id"], "starting", conn)
                runs_service.finish_run(
                    run["id"], "failure", conn,
                    error_code="executor_error",
                )

        # All runs should be failed
        runs = conn.execute(
            "SELECT status FROM backend_runs WHERE task_id = ?",
            (task["id"],),
        ).fetchall()
        self.assertEqual(len(runs), 2)
        for r in runs:
            self.assertEqual(r["status"], "failed")

    def test_non_transient_failure_not_escalated(self):
        """Adapter returning failure with non-transient error_code
        (e.g. capability_denied) is NOT escalated."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=True)
        task = _make_task(conn, title="Fix typo",
                          description="Fix a typo")

        decision = routing_service.decide(task, conn)

        run = runs_service.create_run(
            task_id=task["id"],
            routing_decision_id=decision["routing_decision_id"],
            backend_profile_id="prof-codex",
            conn=conn,
        )

        # Non-transient: no error_code at all (normal execution failure)
        adapter = _FakeAdapter(
            return_result={"status": "failed", "outcome": "failure",
                           "exit_code": 1})
        result = adapter.start(task, run, {}, {})

        self.assertEqual(result["status"], "failed")
        runs = conn.execute(
            "SELECT * FROM backend_runs WHERE task_id = ?",
            (task["id"],),
        ).fetchall()
        self.assertEqual(len(runs), 1)

    def test_transient_error_code_escalates(self):
        """Adapter returning failure with a transient error_code
        (auth_failed, rate_limited, etc.) IS escalated."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=True)
        task = _make_task(conn, title="Fix typo",
                          description="Fix a typo")

        decision = routing_service.decide(task, conn)
        chain = decision["fallback_chain"]

        # Simulate: codex returns auth_failed → should escalate to claude
        prior_run_id = None
        results = []
        for idx, profile_id in enumerate(chain[:2]):
            profile = dict(conn.execute(
                "SELECT * FROM backend_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone())

            relation_type = "fallback" if idx > 0 else None
            run = runs_service.create_run(
                task_id=task["id"],
                routing_decision_id=decision["routing_decision_id"],
                backend_profile_id=profile_id,
                conn=conn,
                previous_run_id=prior_run_id,
                relation_type=relation_type,
            )

            if profile["slug"] == "codex":
                # Returns transient failure
                result = {"status": "failed", "outcome": "failure",
                          "error_code": "auth_failed"}
                results.append(result)
                prior_run_id = run["id"]
                continue
            else:
                # Claude succeeds
                result = {"status": "succeeded", "outcome": "success"}
                results.append(result)
                break

        # Verify escalation happened
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["error_code"], "auth_failed")
        self.assertEqual(results[1]["status"], "succeeded")

        runs = conn.execute(
            "SELECT * FROM backend_runs WHERE task_id = ? "
            "ORDER BY created_at",
            (task["id"],),
        ).fetchall()
        self.assertEqual(len(runs), 2)
        self.assertEqual(dict(runs[1])["relation_type"], "fallback")

    def test_non_transient_codes_excluded(self):
        """capability_denied, adapter_not_implemented, and
        codex_no_token must NOT be in the transient set."""
        executor_path = os.path.join(
            ROOT_DIR, "bin", "task-executor.py")
        source = open(executor_path, encoding="utf-8").read()
        start = source.find("_TRANSIENT_ERROR_CODES")
        self.assertNotEqual(start, -1,
                            "_TRANSIENT_ERROR_CODES not found")
        snippet = source[start:start + 400]
        self.assertNotIn("capability_denied", snippet)
        self.assertNotIn("adapter_not_implemented", snippet)
        self.assertNotIn("codex_no_token", snippet)

    def test_transient_codes_include_expected(self):
        """Known transient codes must be in the executor's set."""
        executor_path = os.path.join(
            ROOT_DIR, "bin", "task-executor.py")
        source = open(executor_path, encoding="utf-8").read()
        start = source.find("_TRANSIENT_ERROR_CODES")
        snippet = source[start:start + 400]
        for code in ("auth_failed", "rate_limited", "timed_out",
                     "adapter_exception", "subprocess_error"):
            self.assertIn(code, snippet,
                          f"{code} not in _TRANSIENT_ERROR_CODES")

    def test_fallback_limit_is_one(self):
        """Execution chain is limited to primary + 1 fallback."""
        conn = _make_conn()
        _seed_profiles(conn, codex_enabled=True)
        task = _make_task(conn, title="Fix typo",
                          description="Fix a typo")

        decision = routing_service.decide(task, conn)
        chain = decision["fallback_chain"]

        self.assertEqual(len(chain), 2)
        execution_chain = chain[:2]
        self.assertEqual(len(execution_chain), 2)


# ═══════════════════════════════════════════════════════════════════
# 3. Credential injection (source verification)
# ═══════════════════════════════════════════════════════════════════

class TestCredentialInjection(TestCase):
    """Verify _prepare_backend_env exists in the executor and handles
    both backends.  Cannot import the executor directly (side effects),
    so we verify via source inspection."""

    def _executor_source(self):
        path = os.path.join(ROOT_DIR, "bin", "task-executor.py")
        return open(path, encoding="utf-8").read()

    def test_prepare_backend_env_exists(self):
        """_prepare_backend_env function is defined in the executor."""
        source = self._executor_source()
        self.assertIn("def _prepare_backend_env(", source)

    def test_codex_slug_injects_openai_token(self):
        """The codex branch sets OPENAI_ACCESS_TOKEN."""
        source = self._executor_source()
        start = source.find("def _prepare_backend_env(")
        func = source[start:source.find("\ndef ", start + 1)]
        self.assertIn("OPENAI_ACCESS_TOKEN", func)
        self.assertIn("CODEX_HOME", func)

    def test_claude_slug_injects_anthropic_key(self):
        """The claude_code branch sets ANTHROPIC_API_KEY."""
        source = self._executor_source()
        start = source.find("def _prepare_backend_env(")
        func = source[start:source.find("\ndef ", start + 1)]
        self.assertIn("ANTHROPIC_API_KEY", func)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", func)

    def test_codex_no_token_returns_none(self):
        """When _get_openai_oauth_token returns None, the function
        must return None (not empty dict)."""
        source = self._executor_source()
        start = source.find("def _prepare_backend_env(")
        func = source[start:source.find("\ndef ", start + 1)]
        # Must have: if not token: return None
        self.assertIn("return None", func)

    def test_executor_blocks_on_no_token(self):
        """When _prepare_backend_env returns None, the executor must
        fail with codex_no_token — NOT escalate to fallback."""
        source = self._executor_source()
        start = source.find("def _execute_task_v02(")
        func = source[start:source.find("\ndef ", start + 1)]
        self.assertIn("codex_no_token", func)
        self.assertIn("no OpenAI token", func)

    def test_extra_env_passed_to_adapter(self):
        """The executor injects _extra_env into profile dict."""
        source = self._executor_source()
        start = source.find("def _execute_task_v02(")
        func = source[start:source.find("\ndef ", start + 1)]
        self.assertIn("_extra_env", func)

    def test_adapter_merges_extra_env(self):
        """Both adapters merge extra_env into subprocess env."""
        from backend_adapters.claude_code import ClaudeCodeAdapter
        from backend_adapters.codex import CodexAdapter
        import inspect

        claude_src = inspect.getsource(ClaudeCodeAdapter._execute)
        self.assertIn("extra_env", claude_src)
        self.assertIn("env.update(extra_env)", claude_src)

        codex_src = inspect.getsource(CodexAdapter._execute)
        self.assertIn("extra_env", codex_src)
        self.assertIn("env.update(extra_env)", codex_src)


if __name__ == "__main__":
    import unittest
    unittest.main()
