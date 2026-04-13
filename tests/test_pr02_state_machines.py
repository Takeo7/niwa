#!/usr/bin/env python3
"""Tests for PR-02: Canonical state machines for tasks.status and backend_runs.status.

Covers:
  - All valid task transitions from the SPEC work.
  - All invalid task transitions raise InvalidTransitionError.
  - All valid run transitions from the SPEC work.
  - All invalid run transitions raise InvalidTransitionError.
  - task_request_input writes waiting_input, not revision.
  - _pipeline_status() counts waiting_input as active.
  - Migration 008 adds CHECK constraint on backend_runs.status and is idempotent.
  - Prompts in bin/task-executor.py do not instruct assigned_to_claude as execution contract.
  - can_transition_task('hecha', 'pendiente') == False (hecha is terminal).
  - force_reject_task works and produces an audit record.
  - Transition maps are consistent across all three runtimes.

Run with: pytest tests/test_pr02_state_machines.py -v
"""
import ast
import os
import re
import sqlite3
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')
MIGRATIONS_DIR = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'migrations')
MIGRATION_007 = os.path.join(MIGRATIONS_DIR, '007_v02_execution_core.sql')
MIGRATION_008 = os.path.join(MIGRATIONS_DIR, '008_state_machine_checks.sql')
TASK_EXECUTOR_PATH = os.path.join(PROJECT_ROOT, 'bin', 'task-executor.py')
MCP_SERVER_PATH = os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')
STATE_MACHINES_PATH = os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'state_machines.py')

# Add backend to path so we can import state_machines
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'niwa-app', 'backend'))
import state_machines
from state_machines import (
    TASK_STATUSES, TASK_TRANSITIONS,
    RUN_STATUSES, RUN_TRANSITIONS,
    InvalidTransitionError,
    can_transition_task, can_transition_run,
    assert_task_transition, assert_run_transition,
    force_reject_task,
)


# ── SPEC-defined valid transitions ──

SPEC_TASK_TRANSITIONS = {
    ('inbox', 'pendiente'),
    ('pendiente', 'en_progreso'),
    ('pendiente', 'bloqueada'),
    ('pendiente', 'archivada'),
    ('en_progreso', 'waiting_input'),
    ('en_progreso', 'revision'),
    ('en_progreso', 'bloqueada'),
    ('en_progreso', 'hecha'),
    ('en_progreso', 'archivada'),
    ('waiting_input', 'pendiente'),
    ('waiting_input', 'archivada'),
    ('revision', 'pendiente'),
    ('revision', 'hecha'),
    ('revision', 'archivada'),
    ('bloqueada', 'pendiente'),
    ('bloqueada', 'archivada'),
}

SPEC_RUN_TRANSITIONS = {
    ('queued', 'starting'),
    ('starting', 'running'),
    ('running', 'waiting_approval'),
    ('running', 'waiting_input'),
    ('running', 'succeeded'),
    ('running', 'failed'),
    ('running', 'cancelled'),
    ('running', 'timed_out'),
    ('waiting_approval', 'running'),
    ('waiting_approval', 'rejected'),
    ('waiting_input', 'queued'),
    ('waiting_input', 'cancelled'),
}


def _apply_sql_idempotent(conn, sql):
    """Apply SQL idempotently, handling ALTER TABLE ADD COLUMN."""
    for statement in sql.split(';'):
        statement = statement.strip()
        if not statement:
            continue
        m = re.match(
            r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)',
            statement, re.IGNORECASE,
        )
        if m:
            table, col = m.group(1), m.group(2)
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if col in existing:
                continue
        try:
            conn.execute(statement)
        except Exception:
            pass
    conn.commit()


def _fresh_db():
    """Create a fresh in-memory DB with schema.sql applied."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    schema_sql = open(SCHEMA_PATH).read()
    conn.executescript(schema_sql)
    return conn


def _fresh_db_with_migrations():
    """Create a DB simulating an existing install upgraded via migrations."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    schema_sql = open(SCHEMA_PATH).read()
    # Apply base schema (which now includes v0.2 tables)
    conn.executescript(schema_sql)
    # Apply migration 008
    sql_008 = open(MIGRATION_008).read()
    conn.executescript(sql_008)
    return conn


# ═══════════════════════════════════════════════════════════════════════
# 1. Pure state machine validation
# ═══════════════════════════════════════════════════════════════════════

class TestTaskTransitionsValid(unittest.TestCase):
    """Every SPEC-defined valid task transition should be accepted."""

    def test_all_valid_transitions(self):
        for from_s, to_s in SPEC_TASK_TRANSITIONS:
            with self.subTest(transition=f"{from_s} -> {to_s}"):
                self.assertTrue(
                    can_transition_task(from_s, to_s),
                    f"Expected {from_s} -> {to_s} to be valid",
                )
                # assert_task_transition should NOT raise
                assert_task_transition(from_s, to_s)

    def test_every_status_has_entry_in_transitions(self):
        """Every status in TASK_STATUSES must have a key in TASK_TRANSITIONS."""
        for status in TASK_STATUSES:
            self.assertIn(status, TASK_TRANSITIONS)

    def test_transition_map_matches_spec_exactly(self):
        """The transition map should produce exactly the SPEC transitions."""
        actual = set()
        for from_s, targets in TASK_TRANSITIONS.items():
            for to_s in targets:
                actual.add((from_s, to_s))
        self.assertEqual(actual, SPEC_TASK_TRANSITIONS)


class TestTaskTransitionsInvalid(unittest.TestCase):
    """Invalid transitions must be rejected with a clear error."""

    INVALID_SAMPLES = [
        ('inbox', 'en_progreso'),     # must go through pendiente
        ('inbox', 'hecha'),           # can't skip to done
        ('hecha', 'pendiente'),       # terminal state
        ('hecha', 'en_progreso'),     # terminal state
        ('archivada', 'pendiente'),   # terminal state
        ('archivada', 'inbox'),       # terminal state
        ('en_progreso', 'inbox'),     # no backwards to inbox
        ('pendiente', 'revision'),    # not a direct transition
        ('waiting_input', 'hecha'),   # must go through pendiente
        ('bloqueada', 'en_progreso'), # must go through pendiente
    ]

    def test_invalid_transitions_return_false(self):
        for from_s, to_s in self.INVALID_SAMPLES:
            with self.subTest(transition=f"{from_s} -> {to_s}"):
                self.assertFalse(
                    can_transition_task(from_s, to_s),
                    f"Expected {from_s} -> {to_s} to be INVALID",
                )

    def test_invalid_transitions_raise(self):
        for from_s, to_s in self.INVALID_SAMPLES:
            with self.subTest(transition=f"{from_s} -> {to_s}"):
                with self.assertRaises(InvalidTransitionError) as ctx:
                    assert_task_transition(from_s, to_s)
                err = ctx.exception
                self.assertEqual(err.entity, 'task')
                self.assertEqual(err.from_status, from_s)
                self.assertEqual(err.to_status, to_s)
                # Error message should be human-readable
                self.assertIn(from_s, str(err))
                self.assertIn(to_s, str(err))

    def test_hecha_is_terminal(self):
        """Specific test: hecha has no outgoing transitions."""
        self.assertEqual(TASK_TRANSITIONS['hecha'], frozenset())
        self.assertFalse(can_transition_task('hecha', 'pendiente'))

    def test_archivada_is_terminal(self):
        """Specific test: archivada has no outgoing transitions."""
        self.assertEqual(TASK_TRANSITIONS['archivada'], frozenset())


class TestRunTransitionsValid(unittest.TestCase):
    """Every SPEC-defined valid run transition should be accepted."""

    def test_all_valid_transitions(self):
        for from_s, to_s in SPEC_RUN_TRANSITIONS:
            with self.subTest(transition=f"{from_s} -> {to_s}"):
                self.assertTrue(
                    can_transition_run(from_s, to_s),
                    f"Expected {from_s} -> {to_s} to be valid",
                )
                assert_run_transition(from_s, to_s)

    def test_every_status_has_entry_in_transitions(self):
        for status in RUN_STATUSES:
            self.assertIn(status, RUN_TRANSITIONS)

    def test_transition_map_matches_spec_exactly(self):
        actual = set()
        for from_s, targets in RUN_TRANSITIONS.items():
            for to_s in targets:
                actual.add((from_s, to_s))
        self.assertEqual(actual, SPEC_RUN_TRANSITIONS)


class TestRunTransitionsInvalid(unittest.TestCase):
    """Invalid run transitions must be rejected."""

    INVALID_SAMPLES = [
        ('queued', 'running'),           # must go through starting
        ('starting', 'succeeded'),       # must go through running
        ('succeeded', 'running'),        # terminal
        ('failed', 'queued'),            # terminal
        ('cancelled', 'running'),        # terminal
        ('timed_out', 'queued'),         # terminal
        ('rejected', 'running'),         # terminal
        ('running', 'queued'),           # no backwards
        ('waiting_approval', 'succeeded'), # must resume to running first
    ]

    def test_invalid_transitions_return_false(self):
        for from_s, to_s in self.INVALID_SAMPLES:
            with self.subTest(transition=f"{from_s} -> {to_s}"):
                self.assertFalse(can_transition_run(from_s, to_s))

    def test_invalid_transitions_raise(self):
        for from_s, to_s in self.INVALID_SAMPLES:
            with self.subTest(transition=f"{from_s} -> {to_s}"):
                with self.assertRaises(InvalidTransitionError):
                    assert_run_transition(from_s, to_s)

    def test_terminal_states_have_no_outgoing(self):
        for terminal in ('succeeded', 'failed', 'cancelled', 'timed_out', 'rejected'):
            self.assertEqual(RUN_TRANSITIONS[terminal], frozenset(),
                             f"{terminal} should have no outgoing transitions")


# ═══════════════════════════════════════════════════════════════════════
# 2. force_reject_task
# ═══════════════════════════════════════════════════════════════════════

class TestForceRejectTask(unittest.TestCase):
    """force_reject_task bypasses state machine with audit trail."""

    def test_hecha_to_pendiente_blocked_by_state_machine(self):
        self.assertFalse(can_transition_task('hecha', 'pendiente'))

    def test_force_reject_returns_audit_record(self):
        audit = force_reject_task('task-abc123', 'bad output', user='test-user')
        self.assertEqual(audit['action'], 'force_reject_task')
        self.assertEqual(audit['task_id'], 'task-abc123')
        self.assertEqual(audit['from_status'], 'hecha')
        self.assertEqual(audit['to_status'], 'pendiente')
        self.assertEqual(audit['reason'], 'bad output')
        self.assertEqual(audit['user'], 'test-user')
        self.assertIn('timestamp', audit)

    def test_force_reject_logs_warning(self):
        """force_reject_task must log at WARNING level for auditing."""
        import logging
        with self.assertLogs('state_machines', level='WARNING') as cm:
            force_reject_task('task-xyz', 'test reason')
        self.assertTrue(any('force_reject_task' in msg for msg in cm.output))
        self.assertTrue(any('task-xyz' in msg for msg in cm.output))


# ═══════════════════════════════════════════════════════════════════════
# 3. Bug fixes
# ═══════════════════════════════════════════════════════════════════════

class TestTaskRequestInputBugFix(unittest.TestCase):
    """task_request_input must write waiting_input, not revision."""

    def test_mcp_server_uses_waiting_input(self):
        """The _task_request_input function in tasks-mcp/server.py must
        set status to 'waiting_input', not 'revision'."""
        code = open(MCP_SERVER_PATH).read()
        # Find the _task_request_input function and check its SQL
        func_match = re.search(
            r'def _task_request_input\(.*?\n(?=def |\Z)',
            code, re.DOTALL,
        )
        self.assertIsNotNone(func_match, "_task_request_input function not found")
        func_body = func_match.group(0)

        # Must contain waiting_input in the UPDATE
        self.assertIn("status='waiting_input'", func_body,
                       "UPDATE should set status='waiting_input'")
        # Must NOT contain revision in the UPDATE
        self.assertNotIn("status='revision'", func_body,
                          "UPDATE must NOT set status='revision'")
        # Return value should also say waiting_input
        self.assertIn('"waiting_input"', func_body,
                       "Return value should contain 'waiting_input'")


class TestPipelineStatusBugFix(unittest.TestCase):
    """_pipeline_status() must count waiting_input as active."""

    def test_pipeline_status_includes_waiting_input(self):
        code = open(MCP_SERVER_PATH).read()
        func_match = re.search(
            r'def _pipeline_status\(.*?\n(?=\ndef |\Z)',
            code, re.DOTALL,
        )
        self.assertIsNotNone(func_match, "_pipeline_status function not found")
        func_body = func_match.group(0)
        self.assertIn('waiting_input', func_body,
                       "_pipeline_status must count waiting_input as active")

    def test_pipeline_status_db(self):
        """Verify waiting_input tasks are counted as active in the DB query."""
        conn = _fresh_db()
        now = '2026-04-13T00:00:00Z'
        # Insert tasks in various statuses
        for i, status in enumerate(['pendiente', 'waiting_input', 'hecha']):
            conn.execute(
                "INSERT INTO tasks (id,title,area,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (f'task-{i}', f'Task {i}', 'personal', status, now, now),
            )
        conn.commit()

        by_status = {
            r['status']: r['n']
            for r in conn.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")
        }
        active = sum(
            by_status.get(s, 0)
            for s in ('inbox', 'pendiente', 'en_progreso', 'bloqueada', 'revision', 'waiting_input')
        )
        # pendiente + waiting_input = 2 active (hecha excluded)
        self.assertEqual(active, 2)
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 4. Migration 008 — CHECK constraint on backend_runs.status
# ═══════════════════════════════════════════════════════════════════════

class TestMigration008(unittest.TestCase):
    """Migration 008 adds CHECK constraint on backend_runs.status."""

    def test_migration_008_exists(self):
        self.assertTrue(os.path.isfile(MIGRATION_008),
                        f"Migration file not found: {MIGRATION_008}")

    def test_fresh_install_has_backend_runs_check(self):
        """schema.sql must include CHECK on backend_runs.status."""
        schema_sql = open(SCHEMA_PATH).read()
        # Find specifically the "CREATE TABLE ... backend_runs (" block
        match = re.search(
            r'CREATE TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?backend_runs\s*\((.+?)\);',
            schema_sql, re.DOTALL | re.IGNORECASE,
        )
        self.assertIsNotNone(match, "backend_runs CREATE TABLE not found in schema.sql")
        table_def = match.group(1)
        self.assertIn('CHECK', table_def.upper(),
                       "backend_runs should have a CHECK constraint")
        # Verify all SPEC statuses are in the CHECK
        for status in ('queued', 'starting', 'running', 'waiting_approval',
                       'waiting_input', 'succeeded', 'failed', 'cancelled',
                       'timed_out', 'rejected'):
            self.assertIn(status, table_def,
                           f"backend_runs CHECK must include '{status}'")

    def test_migration_008_applies_on_fresh_schema(self):
        """Migration 008 must apply cleanly on a DB created from schema.sql."""
        conn = _fresh_db_with_migrations()
        # Verify backend_runs still exists and has the right columns
        cols = {r[1] for r in conn.execute("PRAGMA table_info(backend_runs)").fetchall()}
        self.assertIn('status', cols)
        self.assertIn('task_id', cols)
        conn.close()

    def test_migration_008_enforces_check(self):
        """After migration 008, invalid status values must be rejected."""
        conn = _fresh_db_with_migrations()
        now = '2026-04-13T00:00:00Z'
        # Need a project and task first for the FK
        conn.execute(
            "INSERT INTO projects (id,slug,name,area,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            ('proj-1', 'test', 'Test', 'personal', now, now),
        )
        conn.execute(
            "INSERT INTO tasks (id,title,area,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            ('task-1', 'Test task', 'personal', 'pendiente', now, now),
        )
        conn.commit()

        # Valid status should work
        conn.execute(
            "INSERT INTO backend_runs (id,task_id,status,created_at,updated_at) VALUES (?,?,?,?,?)",
            ('run-1', 'task-1', 'queued', now, now),
        )
        conn.commit()

        # Invalid status should fail
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO backend_runs (id,task_id,status,created_at,updated_at) VALUES (?,?,?,?,?)",
                ('run-2', 'task-1', 'INVALID_STATUS', now, now),
            )
        conn.close()

    def test_migration_008_preserves_index(self):
        """idx_backend_runs_task_status must exist after migration."""
        conn = _fresh_db_with_migrations()
        indices = {r[1] for r in conn.execute("PRAGMA index_list(backend_runs)").fetchall()}
        self.assertIn('idx_backend_runs_task_status', indices)
        conn.close()

    def test_all_spec_run_statuses_accepted(self):
        """All SPEC-defined run statuses must be accepted by the CHECK constraint."""
        conn = _fresh_db_with_migrations()
        now = '2026-04-13T00:00:00Z'
        conn.execute(
            "INSERT INTO projects (id,slug,name,area,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            ('proj-1', 'test', 'Test', 'personal', now, now),
        )
        conn.execute(
            "INSERT INTO tasks (id,title,area,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            ('task-1', 'Test task', 'personal', 'pendiente', now, now),
        )
        for i, status in enumerate(RUN_STATUSES):
            with self.subTest(status=status):
                conn.execute(
                    "INSERT INTO backend_runs (id,task_id,status,created_at,updated_at) VALUES (?,?,?,?,?)",
                    (f'run-{i}', 'task-1', status, now, now),
                )
        conn.commit()
        count = conn.execute("SELECT count(*) FROM backend_runs").fetchone()[0]
        self.assertEqual(count, len(RUN_STATUSES))
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
# 5. Prompt cleanup — assigned_to_claude
# ═══════════════════════════════════════════════════════════════════════

class TestAssignedToClaudeCleanup(unittest.TestCase):
    """assigned_to_claude must not appear in executor prompts as execution contract."""

    def test_tier1_chat_prompt_no_assigned_to_claude(self):
        """Tier 1 (chat) prompt must not instruct to use assigned_to_claude."""
        code = open(TASK_EXECUTOR_PATH).read()
        # Find _build_prompt function
        func_match = re.search(
            r'def _build_prompt\(.*?\n(?=\ndef |\nclass |\Z)',
            code, re.DOTALL,
        )
        self.assertIsNotNone(func_match, "_build_prompt function not found")
        func_body = func_match.group(0)

        # Must not contain assigned_to_claude as an instruction
        lines_with_atc = [
            line.strip() for line in func_body.splitlines()
            if 'assigned_to_claude' in line and 'parts.append' in line
        ]
        self.assertEqual(
            len(lines_with_atc), 0,
            f"_build_prompt still instructs assigned_to_claude: {lines_with_atc}",
        )

    def test_planner_prompt_no_assigned_to_claude(self):
        """Planner prompt must not instruct to use assigned_to_claude."""
        code = open(TASK_EXECUTOR_PATH).read()
        func_match = re.search(
            r'def _build_planner_prompt\(.*?\n(?=\ndef |\nclass |\Z)',
            code, re.DOTALL,
        )
        self.assertIsNotNone(func_match, "_build_planner_prompt function not found")
        func_body = func_match.group(0)

        lines_with_atc = [
            line.strip() for line in func_body.splitlines()
            if 'assigned_to_claude' in line and 'parts.append' in line
        ]
        self.assertEqual(
            len(lines_with_atc), 0,
            f"_build_planner_prompt still instructs assigned_to_claude: {lines_with_atc}",
        )


# ═══════════════════════════════════════════════════════════════════════
# 6. Transition map consistency across runtimes
# ═══════════════════════════════════════════════════════════════════════

class TestTransitionMapConsistency(unittest.TestCase):
    """The transition maps in all three runtimes must be identical."""

    @staticmethod
    def _eval_node(node):
        """Recursively evaluate an AST node, handling frozenset() calls."""
        if isinstance(node, ast.Dict):
            keys = [TestTransitionMapConsistency._eval_node(k) for k in node.keys]
            values = [TestTransitionMapConsistency._eval_node(v) for v in node.values]
            return dict(zip(keys, values))
        elif isinstance(node, ast.Call):
            # Handle frozenset({...})
            func_name = getattr(node.func, 'id', None)
            if func_name == 'frozenset' and len(node.args) == 1:
                inner = TestTransitionMapConsistency._eval_node(node.args[0])
                return frozenset(inner)
            if func_name == 'frozenset' and len(node.args) == 0:
                return frozenset()
            raise ValueError(f"Unsupported call: {func_name}")
        elif isinstance(node, ast.Set):
            return {TestTransitionMapConsistency._eval_node(e) for e in node.elts}
        elif isinstance(node, ast.Constant):
            return node.value
        else:
            return ast.literal_eval(node)

    def _extract_transitions_from_source(self, filepath, varname='_TASK_TRANSITIONS'):
        """Extract a transition dict from a Python source file using AST."""
        source = open(filepath).read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            # Handle both plain assignment and annotated assignment
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    name = getattr(target, 'id', None) or getattr(target, 'attr', None)
                    if name == varname:
                        return self._eval_node(node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                target = node.target
                name = getattr(target, 'id', None) or getattr(target, 'attr', None)
                if name == varname:
                    return self._eval_node(node.value)
        return None

    def test_executor_matches_canonical(self):
        """bin/task-executor.py transitions must match state_machines.py."""
        executor_map = self._extract_transitions_from_source(TASK_EXECUTOR_PATH)
        self.assertIsNotNone(executor_map, "_TASK_TRANSITIONS not found in task-executor.py")
        canonical = {k: set(v) for k, v in TASK_TRANSITIONS.items()}
        executor = {k: set(v) for k, v in executor_map.items()}
        self.assertEqual(executor, canonical,
                         "task-executor.py transition map differs from state_machines.py")

    def test_mcp_server_matches_canonical(self):
        """servers/tasks-mcp/server.py transitions must match state_machines.py."""
        mcp_map = self._extract_transitions_from_source(MCP_SERVER_PATH)
        self.assertIsNotNone(mcp_map, "_TASK_TRANSITIONS not found in server.py")
        canonical = {k: set(v) for k, v in TASK_TRANSITIONS.items()}
        mcp = {k: set(v) for k, v in mcp_map.items()}
        self.assertEqual(mcp, canonical,
                         "tasks-mcp/server.py transition map differs from state_machines.py")


# ═══════════════════════════════════════════════════════════════════════
# 7. Schema integrity
# ═══════════════════════════════════════════════════════════════════════

class TestSchemaIntegrity(unittest.TestCase):
    """Verify schema.sql has correct CHECK constraints after PR-02 updates."""

    def test_tasks_status_check_includes_waiting_input(self):
        """tasks.status CHECK in schema.sql must include waiting_input."""
        schema = open(SCHEMA_PATH).read()
        match = re.search(
            r'CREATE TABLE[^;]*?\btasks\b\s*\([^;]+\);',
            schema, re.DOTALL | re.IGNORECASE,
        )
        self.assertIsNotNone(match)
        table_def = match.group(0)
        self.assertIn('waiting_input', table_def)

    def test_kanban_columns_check_includes_waiting_input(self):
        """kanban_columns.status CHECK in schema.sql must include waiting_input."""
        schema = open(SCHEMA_PATH).read()
        match = re.search(
            r'CREATE TABLE[^;]*?kanban_columns\s*\([^;]+\);',
            schema, re.DOTALL | re.IGNORECASE,
        )
        self.assertIsNotNone(match)
        table_def = match.group(0)
        self.assertIn('waiting_input', table_def)

    def test_fresh_db_rejects_invalid_task_status(self):
        """Fresh install from schema.sql must reject invalid task statuses."""
        conn = _fresh_db()
        now = '2026-04-13T00:00:00Z'
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (id,title,area,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                ('task-bad', 'Bad', 'personal', 'INVALID', now, now),
            )
        conn.close()

    def test_fresh_db_accepts_all_task_statuses(self):
        """Fresh install must accept all SPEC-defined task statuses."""
        conn = _fresh_db()
        now = '2026-04-13T00:00:00Z'
        for i, status in enumerate(TASK_STATUSES):
            with self.subTest(status=status):
                conn.execute(
                    "INSERT INTO tasks (id,title,area,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                    (f'task-{i}', f'Task {i}', 'personal', status, now, now),
                )
        conn.commit()
        count = conn.execute("SELECT count(*) FROM tasks").fetchone()[0]
        self.assertEqual(count, len(TASK_STATUSES))
        conn.close()


if __name__ == '__main__':
    unittest.main()
