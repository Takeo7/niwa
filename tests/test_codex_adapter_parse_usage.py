"""Unit tests for CodexAdapter.parse_usage_signals().

Verifies extraction of token counts, cost, model, duration, and
turns from Codex JSON-line output format.
"""

import json
import os
import sys

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from backend_adapters.codex import CodexAdapter


@pytest.fixture
def adapter():
    return CodexAdapter()


# ── Happy path ────────────────────────────────────────────────────

class TestParseUsageHappyPath:

    def test_full_result(self, adapter):
        """All fields populated from a complete result event."""
        output = "\n".join([
            json.dumps({"type": "status", "status": "started",
                        "session_id": "s1"}),
            json.dumps({"type": "message", "role": "assistant",
                        "content": "Working..."}),
            json.dumps({"type": "message", "role": "assistant",
                        "content": "Done."}),
            json.dumps({"type": "result", "status": "completed",
                        "cost_usd": 0.015, "duration_ms": 3000,
                        "model": "o4-mini",
                        "usage": {"prompt_tokens": 200,
                                  "completion_tokens": 300,
                                  "total_tokens": 500}}),
        ])
        signals = adapter.parse_usage_signals(output)
        assert signals["input_tokens"] == 200
        assert signals["output_tokens"] == 300
        assert signals["total_tokens"] == 500
        assert signals["model"] == "o4-mini"
        assert signals["cost_usd"] == 0.015
        assert signals["duration_ms"] == 3000
        assert signals["turns"] == 2

    def test_single_turn(self, adapter):
        output = "\n".join([
            json.dumps({"type": "message", "role": "assistant",
                        "content": "Ok"}),
            json.dumps({"type": "result", "model": "o4-mini",
                        "usage": {"prompt_tokens": 100,
                                  "completion_tokens": 50,
                                  "total_tokens": 150}}),
        ])
        signals = adapter.parse_usage_signals(output)
        assert signals["turns"] == 1
        assert signals["input_tokens"] == 100
        assert signals["output_tokens"] == 50


# ── Edge cases ────────────────────────────────────────────────────

class TestParseUsageEdgeCases:

    def test_empty_input(self, adapter):
        signals = adapter.parse_usage_signals("")
        assert signals["input_tokens"] is None
        assert signals["output_tokens"] is None
        assert signals["turns"] is None

    def test_no_result_event(self, adapter):
        output = json.dumps({"type": "message", "role": "assistant",
                             "content": "Hello"})
        signals = adapter.parse_usage_signals(output)
        assert signals["cost_usd"] is None
        assert signals["model"] is None
        assert signals["turns"] == 1

    def test_non_json_lines_skipped(self, adapter):
        output = "not json\n" + json.dumps({
            "type": "result", "model": "o4-mini",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                      "total_tokens": 15},
        })
        signals = adapter.parse_usage_signals(output)
        assert signals["input_tokens"] == 10
        assert signals["model"] == "o4-mini"

    def test_result_without_usage(self, adapter):
        output = json.dumps({"type": "result", "model": "o4-mini",
                             "cost_usd": 0.01})
        signals = adapter.parse_usage_signals(output)
        assert signals["model"] == "o4-mini"
        assert signals["cost_usd"] == 0.01
        assert signals["input_tokens"] is None

    def test_result_with_empty_usage(self, adapter):
        output = json.dumps({"type": "result", "usage": {}})
        signals = adapter.parse_usage_signals(output)
        assert signals["input_tokens"] is None
        assert signals["output_tokens"] is None

    def test_non_assistant_messages_not_counted(self, adapter):
        """Only messages with role=assistant count as turns."""
        output = "\n".join([
            json.dumps({"type": "message", "role": "system",
                        "content": "System msg"}),
            json.dumps({"type": "message", "role": "assistant",
                        "content": "Reply"}),
            json.dumps({"type": "result", "usage": {}}),
        ])
        signals = adapter.parse_usage_signals(output)
        assert signals["turns"] == 1

    def test_whitespace_only_input(self, adapter):
        signals = adapter.parse_usage_signals("   \n  \n  ")
        assert signals["turns"] is None

    def test_multiple_result_events_last_wins(self, adapter):
        """If multiple result events, last one overwrites."""
        output = "\n".join([
            json.dumps({"type": "result", "model": "first",
                        "usage": {"prompt_tokens": 1,
                                  "completion_tokens": 1,
                                  "total_tokens": 2}}),
            json.dumps({"type": "result", "model": "second",
                        "usage": {"prompt_tokens": 99,
                                  "completion_tokens": 99,
                                  "total_tokens": 198}}),
        ])
        signals = adapter.parse_usage_signals(output)
        assert signals["model"] == "second"
        assert signals["input_tokens"] == 99

    def test_all_signal_fields_present(self, adapter):
        """Every USAGE_SIGNAL_FIELDS key is present in result."""
        signals = adapter.parse_usage_signals("")
        from backend_adapters.codex import USAGE_SIGNAL_FIELDS
        for field in USAGE_SIGNAL_FIELDS:
            assert field in signals

    def test_partial_usage_object(self, adapter):
        output = json.dumps({
            "type": "result",
            "usage": {"prompt_tokens": 42},
        })
        signals = adapter.parse_usage_signals(output)
        assert signals["input_tokens"] == 42
        assert signals["output_tokens"] is None
        assert signals["total_tokens"] is None
