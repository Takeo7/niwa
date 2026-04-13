#!/usr/bin/env python3
"""Tests for PR-00: ADR, scope document, state machines, and documentation fixes.

Run with: pytest tests/test_pr00_docs.py -v
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(PROJECT_ROOT, 'docs')
ADR_DIR = os.path.join(DOCS_DIR, 'adr')


class TestPR00Deliverables:
    """Verify that all PR-00 deliverable files exist."""

    def test_adr_0002_exists(self):
        path = os.path.join(ADR_DIR, '0002-v02-architecture.md')
        assert os.path.isfile(path), f"Missing: {path}"

    def test_v02_scope_exists(self):
        path = os.path.join(DOCS_DIR, 'v0.2-scope.md')
        assert os.path.isfile(path), f"Missing: {path}"

    def test_state_machines_exists(self):
        path = os.path.join(DOCS_DIR, 'state-machines.md')
        assert os.path.isfile(path), f"Missing: {path}"

    def test_adr_0001_still_exists(self):
        """ADR 0001 must not be overwritten or removed."""
        path = os.path.join(ADR_DIR, '0001-niwa-yume-separation.md')
        assert os.path.isfile(path), f"ADR 0001 was deleted or moved: {path}"


class TestADR0002Content:
    """Verify key content in the v0.2 architecture ADR."""

    def setup_method(self):
        path = os.path.join(ADR_DIR, '0002-v02-architecture.md')
        with open(path) as f:
            self.content = f.read()

    def test_related_adr_reference(self):
        """First line must reference ADR 0001."""
        first_line = self.content.split('\n')[0]
        assert '0001-niwa-yume-separation.md' in first_line

    def test_supersedes_line(self):
        """First line must declare supersedes/extends relationship."""
        first_line = self.content.split('\n')[0]
        assert 'Supersedes/extends: none' in first_line

    def test_sequential_numbering(self):
        """ADR is numbered 0002, not 0001."""
        assert '# ADR 0002' in self.content

    def test_decision_core_standalone(self):
        """D1: Core mode standalone."""
        assert 'Core mode' in self.content

    def test_decision_openclaw_not_hard_dependency(self):
        """D1: OpenClaw is not a hard global dependency."""
        assert 'not a hard global dependency' in self.content

    def test_decision_assigned_to_claude_deprecated(self):
        """D3: assigned_to_claude deprecated as routing semantics."""
        assert 'assigned_to_claude' in self.content
        assert 'deprecated' in self.content.lower()

    def test_decision_waiting_input_canonical(self):
        """D4: waiting_input is canonical state."""
        assert 'waiting_input' in self.content

    def test_decision_backend_run_at_execution(self):
        """D5: backend_run born at execution start."""
        assert 'backend_run' in self.content
        assert 'execution start' in self.content

    def test_decision_streamable_http(self):
        """D6: streamable-http is standard transport."""
        assert 'streamable-http' in self.content

    def test_decision_terminal_disabled(self):
        """D7: Terminal disabled by default."""
        assert 'Terminal disabled by default' in self.content or 'terminal' in self.content.lower()


class TestStateMachinesContent:
    """Verify key content in state-machines.md."""

    def setup_method(self):
        path = os.path.join(DOCS_DIR, 'state-machines.md')
        with open(path) as f:
            self.content = f.read()

    def test_task_states_defined(self):
        """All 8 task states must appear."""
        required_states = [
            'inbox', 'pendiente', 'en_progreso', 'waiting_input',
            'revision', 'bloqueada', 'hecha', 'archivada',
        ]
        for state in required_states:
            assert state in self.content, f"Missing task state: {state}"

    def test_run_states_defined(self):
        """All 10 backend_run states must appear."""
        required_states = [
            'queued', 'starting', 'running', 'waiting_approval',
            'waiting_input', 'succeeded', 'failed', 'cancelled',
            'timed_out', 'rejected',
        ]
        for state in required_states:
            assert state in self.content, f"Missing run state: {state}"

    def test_relation_types_defined(self):
        """Fallback, resume, retry relation types must appear."""
        for rel_type in ['fallback', 'resume', 'retry']:
            assert rel_type in self.content, f"Missing relation type: {rel_type}"

    def test_waiting_input_not_revision_rule(self):
        """Must document that waiting_input is used, not revision, for input requests."""
        assert 'Never use `revision`' in self.content or 'not `revision`' in self.content


class TestScopeContent:
    """Verify key content in v0.2-scope.md."""

    def setup_method(self):
        path = os.path.join(DOCS_DIR, 'v0.2-scope.md')
        with open(path) as f:
            self.content = f.read()

    def test_in_scope_section(self):
        assert '## In scope' in self.content

    def test_out_of_scope_section(self):
        assert '## Out of scope' in self.content

    def test_no_gemini_ollama(self):
        """Gemini/Ollama must be listed as out of scope."""
        assert 'Gemini' in self.content
        assert 'Ollama' in self.content

    def test_no_multiuser(self):
        """Multi-user must be listed as out of scope."""
        assert 'multi-tenant' in self.content.lower() or 'Multi-tenant' in self.content

    def test_pr_execution_order(self):
        """PR execution order table must exist."""
        assert 'PR-00' in self.content
        assert 'PR-12' in self.content


class TestDocumentationFixes:
    """Verify stale documentation has been corrected."""

    def test_install_openclaw_uses_streamable_http(self):
        """INSTALL.md Step 11 must use streamable-http for OpenClaw."""
        path = os.path.join(PROJECT_ROOT, 'INSTALL.md')
        with open(path) as f:
            content = f.read()
        assert 'streamable-http' in content
        # The OpenClaw registration line should NOT use SSE as the type
        lines = content.split('\n')
        for line in lines:
            if 'openclaw mcp set' in line.lower():
                assert 'streamable-http' in line, \
                    f"OpenClaw mcp set should use streamable-http, found: {line}"

    def test_install_smoke_test_note(self):
        """INSTALL.md must mention that mcp set does not validate connection."""
        path = os.path.join(PROJECT_ROOT, 'INSTALL.md')
        with open(path) as f:
            content = f.read()
        assert 'does not validate' in content.lower() or 'smoke test' in content.lower()

    def test_readme_openclaw_streamable_http_note(self):
        """README.md OpenClaw section must reference streamable-http."""
        path = os.path.join(PROJECT_ROOT, 'README.md')
        with open(path) as f:
            content = f.read()
        assert 'streamable-http' in content


class TestDecisionsLog:
    """Verify DECISIONS-LOG.md has the ADR numbering entry."""

    def test_adr_numbering_decision_logged(self):
        path = os.path.join(PROJECT_ROOT, 'docs', 'DECISIONS-LOG.md')
        with open(path) as f:
            content = f.read()
        assert 'PR-00' in content
        assert '0002' in content
        assert 'secuencial' in content.lower() or 'sequential' in content.lower() or 'secuenciales' in content.lower()
