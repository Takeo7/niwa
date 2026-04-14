"""Tests for mcp_contract — PR-09 Niwa v0.2.

Covers:
  - load_contract: success, file not found, missing keys
  - validate_contract: valid contract, unknown tools, duplicates
  - Real v02-assistant.json loads and validates

Run with: pytest tests/test_mcp_contract.py -v
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "niwa-app", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import mcp_contract


# ── load_contract ────────────────────────────────────────────────────

class TestLoadContract:

    def test_load_real_v02_assistant(self):
        c = mcp_contract.load_contract("v02-assistant")
        assert c["contract_version"] == "v02-assistant"
        assert "assistant_turn" in c["tools"]
        assert len(c["tools"]) == 11

    def test_load_real_initial_legacy(self):
        """v0.1 initial.json uses 'version' instead of 'contract_version'."""
        c = mcp_contract.load_contract("initial", strict=False)
        assert c["tools"]

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            mcp_contract.load_contract("nonexistent")

    def test_missing_required_key(self, tmp_path):
        (tmp_path / "bad.json").write_text('{"tools": ["a"]}')
        with pytest.raises(ValueError, match="contract_version"):
            mcp_contract.load_contract("bad", contracts_dir=tmp_path)

    def test_empty_tools(self, tmp_path):
        (tmp_path / "empty.json").write_text(
            '{"contract_version": "x", "tools": []}'
        )
        with pytest.raises(ValueError, match="non-empty"):
            mcp_contract.load_contract("empty", contracts_dir=tmp_path)


# ── validate_contract ────────────────────────────────────────────────

class TestValidateContract:

    def test_v02_assistant_valid(self):
        c = mcp_contract.load_contract("v02-assistant")
        result = mcp_contract.validate_contract(c)
        assert result["valid"], result["errors"]
        assert len(result["contract_tools"]) == 11

    def test_unknown_tool_flagged(self, tmp_path):
        # Create a minimal catalog
        (tmp_path / "core.json").write_text(
            json.dumps({"tools": ["task_list"]})
        )
        contract = {
            "contract_version": "test",
            "tools": ["task_list", "totally_unknown"],
        }
        result = mcp_contract.validate_contract(contract, catalog_dir=tmp_path)
        assert not result["valid"]
        assert any("totally_unknown" in e for e in result["errors"])

    def test_duplicate_tool_flagged(self):
        contract = {
            "contract_version": "test",
            "tools": ["assistant_turn", "assistant_turn"],
        }
        result = mcp_contract.validate_contract(contract)
        assert not result["valid"]
        assert any("Duplicate" in e for e in result["errors"])

    def test_v02_known_tools_not_flagged(self, tmp_path):
        """v0.2 tools (not in v0.1 catalog) should not be flagged."""
        (tmp_path / "core.json").write_text(
            json.dumps({"tools": ["task_list"]})
        )
        contract = {
            "contract_version": "test",
            "tools": ["task_list", "assistant_turn", "run_tail"],
        }
        result = mcp_contract.validate_contract(contract, catalog_dir=tmp_path)
        assert result["valid"], result["errors"]


# ── v02-assistant contract shape ─────────────────────────────────────

class TestV02AssistantContractShape:
    """Verify the exact tool list matches the SPEC."""

    EXPECTED_TOOLS = [
        "assistant_turn",
        "task_list",
        "task_get",
        "task_create",
        "task_cancel",
        "task_resume",
        "approval_list",
        "approval_respond",
        "run_tail",
        "run_explain",
        "project_context",
    ]

    def test_exact_tool_list(self):
        c = mcp_contract.load_contract("v02-assistant")
        assert sorted(c["tools"]) == sorted(self.EXPECTED_TOOLS)

    def test_transport_is_streamable_http(self):
        c = mcp_contract.load_contract("v02-assistant")
        assert c["transport"] == "streamable-http"

    def test_no_extra_tools(self):
        c = mcp_contract.load_contract("v02-assistant")
        assert len(c["tools"]) == len(self.EXPECTED_TOOLS)

    def test_no_missing_tools(self):
        c = mcp_contract.load_contract("v02-assistant")
        for tool in self.EXPECTED_TOOLS:
            assert tool in c["tools"], f"Missing tool: {tool}"
