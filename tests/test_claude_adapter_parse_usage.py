"""Tests for PR-04 — ClaudeCodeAdapter.parse_usage_signals().

Pure unit tests (no subprocess, no DB).  Validates extraction of
usage signals from stream-json output lines.
"""

import json
import os
import sys

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend_adapters.claude_code import ClaudeCodeAdapter, USAGE_SIGNAL_FIELDS


@pytest.fixture
def adapter():
    return ClaudeCodeAdapter()


# ── Helpers ──────────────────────────────────────────────────────

def _stream(*messages):
    """Build a stream-json string from a list of dicts."""
    return "\n".join(json.dumps(m) for m in messages)


# ═══════════════════════════════════════════════════════════════════
# 1. Schema completeness
# ═══════════════════════════════════════════════════════════════════

class TestUsageSignalsSchema:

    def test_returns_all_signal_fields(self, adapter):
        """parse_usage_signals always returns all USAGE_SIGNAL_FIELDS keys."""
        result = adapter.parse_usage_signals("")
        for field in USAGE_SIGNAL_FIELDS:
            assert field in result, f"Missing field: {field}"

    def test_empty_input_returns_all_none(self, adapter):
        result = adapter.parse_usage_signals("")
        for field in USAGE_SIGNAL_FIELDS:
            assert result[field] is None

    def test_garbage_input_returns_all_none(self, adapter):
        result = adapter.parse_usage_signals("not json\nalso not json\n")
        for field in USAGE_SIGNAL_FIELDS:
            assert result[field] is None


# ═══════════════════════════════════════════════════════════════════
# 2. Result message parsing
# ═══════════════════════════════════════════════════════════════════

class TestResultMessageParsing:

    def test_extracts_cost_usd(self, adapter):
        raw = _stream({"type": "result", "cost_usd": 0.042})
        result = adapter.parse_usage_signals(raw)
        assert result["cost_usd"] == 0.042

    def test_extracts_duration_ms(self, adapter):
        raw = _stream({"type": "result", "duration_ms": 5200})
        result = adapter.parse_usage_signals(raw)
        assert result["duration_ms"] == 5200

    def test_extracts_model(self, adapter):
        raw = _stream({"type": "result", "model": "claude-sonnet-4-6"})
        result = adapter.parse_usage_signals(raw)
        assert result["model"] == "claude-sonnet-4-6"

    def test_extracts_input_tokens(self, adapter):
        raw = _stream({
            "type": "result",
            "usage": {"input_tokens": 1500},
        })
        result = adapter.parse_usage_signals(raw)
        assert result["input_tokens"] == 1500

    def test_extracts_output_tokens(self, adapter):
        raw = _stream({
            "type": "result",
            "usage": {"output_tokens": 800},
        })
        result = adapter.parse_usage_signals(raw)
        assert result["output_tokens"] == 800

    def test_extracts_cache_read_tokens(self, adapter):
        raw = _stream({
            "type": "result",
            "usage": {"cache_read_input_tokens": 300},
        })
        result = adapter.parse_usage_signals(raw)
        assert result["cache_read_tokens"] == 300

    def test_extracts_cache_creation_tokens(self, adapter):
        raw = _stream({
            "type": "result",
            "usage": {"cache_creation_input_tokens": 100},
        })
        result = adapter.parse_usage_signals(raw)
        assert result["cache_creation_tokens"] == 100

    def test_extracts_all_fields_from_complete_result(self, adapter):
        raw = _stream({
            "type": "result",
            "cost_usd": 0.05,
            "duration_ms": 12000,
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 2000,
                "output_tokens": 1000,
                "cache_read_input_tokens": 500,
                "cache_creation_input_tokens": 200,
            },
        })
        result = adapter.parse_usage_signals(raw)
        assert result["cost_usd"] == 0.05
        assert result["duration_ms"] == 12000
        assert result["model"] == "claude-sonnet-4-6"
        assert result["input_tokens"] == 2000
        assert result["output_tokens"] == 1000
        assert result["cache_read_tokens"] == 500
        assert result["cache_creation_tokens"] == 200

    def test_missing_usage_block_leaves_tokens_none(self, adapter):
        raw = _stream({"type": "result", "cost_usd": 0.01})
        result = adapter.parse_usage_signals(raw)
        assert result["cost_usd"] == 0.01
        assert result["input_tokens"] is None
        assert result["output_tokens"] is None


# ═══════════════════════════════════════════════════════════════════
# 3. Turn counting
# ═══════════════════════════════════════════════════════════════════

class TestTurnCounting:

    def test_counts_assistant_messages_as_turns(self, adapter):
        raw = _stream(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}},
            {"type": "tool_use", "name": "Read"},
            {"type": "tool_result", "content": "file contents"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Done"}]}},
            {"type": "result", "cost_usd": 0.01},
        )
        result = adapter.parse_usage_signals(raw)
        assert result["turns"] == 2

    def test_zero_turns_returns_none(self, adapter):
        raw = _stream({"type": "result", "cost_usd": 0.01})
        result = adapter.parse_usage_signals(raw)
        assert result["turns"] is None

    def test_single_turn(self, adapter):
        raw = _stream(
            {"type": "assistant", "message": {"content": []}},
        )
        result = adapter.parse_usage_signals(raw)
        assert result["turns"] == 1


# ═══════════════════════════════════════════════════════════════════
# 4. Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_mixed_json_and_garbage(self, adapter):
        """Non-JSON lines are silently skipped."""
        raw = (
            'not json line\n'
            + json.dumps({"type": "result", "cost_usd": 0.03}) + '\n'
            + 'another garbage\n'
        )
        result = adapter.parse_usage_signals(raw)
        assert result["cost_usd"] == 0.03

    def test_multiple_result_messages_last_wins(self, adapter):
        """If multiple result messages appear, last one's fields win."""
        raw = _stream(
            {"type": "result", "cost_usd": 0.01, "model": "old-model"},
            {"type": "result", "cost_usd": 0.05, "model": "new-model"},
        )
        result = adapter.parse_usage_signals(raw)
        assert result["cost_usd"] == 0.05
        assert result["model"] == "new-model"

    def test_unknown_message_types_ignored_for_signals(self, adapter):
        raw = _stream(
            {"type": "unknown_type", "data": "something"},
            {"type": "result", "cost_usd": 0.02},
        )
        result = adapter.parse_usage_signals(raw)
        assert result["cost_usd"] == 0.02

    def test_empty_usage_dict(self, adapter):
        raw = _stream({"type": "result", "usage": {}})
        result = adapter.parse_usage_signals(raw)
        assert result["input_tokens"] is None
        assert result["output_tokens"] is None

    def test_whitespace_only_input(self, adapter):
        result = adapter.parse_usage_signals("   \n\n  \n")
        for field in USAGE_SIGNAL_FIELDS:
            assert result[field] is None
