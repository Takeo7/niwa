"""MCP contract loader and validator — PR-09 Niwa v0.2.

Loads contract JSON files from config/mcp-contract/ and validates
them against the MCP catalog (config/mcp-catalog/).

Public API
----------
``load_contract(name)``
    Load a contract by name (e.g. ``"v02-assistant"``).

``validate_contract(contract, catalog_dir)``
    Check that every tool in the contract exists in the catalog.

``CONTRACTS_DIR``, ``CATALOG_DIR``
    Default paths (relative to repo root).
"""

import json
import os
from pathlib import Path
from typing import Any

# Default paths — overridable via env or function args.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACTS_DIR = Path(os.environ.get(
    "NIWA_CONTRACTS_DIR",
    str(_REPO_ROOT / "config" / "mcp-contract"),
))
CATALOG_DIR = Path(os.environ.get(
    "NIWA_CATALOG_DIR",
    str(_REPO_ROOT / "config" / "mcp-catalog"),
))


def load_contract(
    name: str,
    contracts_dir: Path | None = None,
    *,
    strict: bool = True,
) -> dict:
    """Load a contract JSON by name.

    Parameters
    ----------
    name : str
        Contract name without extension (e.g. ``"v02-assistant"``).
    contracts_dir : Path | None
        Override for the contracts directory.
    strict : bool
        If True (default), require ``contract_version`` and ``tools``
        keys.  Set to False for legacy contracts (v0.1 initial.json).

    Returns
    -------
    dict with keys: contract_version, tools, transport, notes.

    Raises
    ------
    FileNotFoundError
        If the contract file does not exist.
    ValueError
        If the JSON is malformed or missing required keys (strict mode).
    """
    d = contracts_dir or CONTRACTS_DIR
    path = d / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Contract not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if strict:
        for key in ("contract_version", "tools"):
            if key not in data:
                raise ValueError(
                    f"Contract {name!r} missing required key: {key!r}"
                )
        if not isinstance(data["tools"], list) or not data["tools"]:
            raise ValueError(
                f"Contract {name!r}: 'tools' must be a non-empty list"
            )
    return data


def _load_catalog_tools(catalog_dir: Path | None = None) -> set[str]:
    """Collect all tool names from the MCP catalog JSON files.

    Reads ``combined.json`` if present (authoritative), otherwise
    unions tools from all individual domain JSONs.
    """
    d = catalog_dir or CATALOG_DIR
    combined = d / "combined.json"
    if combined.is_file():
        with open(combined, "r", encoding="utf-8") as f:
            data = json.load(f)
        tools: set[str] = set()
        for domain in data.get("domains", {}).values():
            tools.update(domain.get("tools", []))
        return tools

    # Fallback: read individual domain files
    tools = set()
    for p in sorted(d.glob("*.json")):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        tools.update(data.get("tools", []))
    return tools


def validate_contract(
    contract: dict,
    catalog_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate a contract against the catalog.

    Returns
    -------
    dict with keys:
        valid (bool), errors (list[str]), warnings (list[str]),
        contract_tools (list[str]), catalog_tools (list[str]).
    """
    catalog_tools = _load_catalog_tools(catalog_dir)
    contract_tools = set(contract.get("tools", []))

    errors: list[str] = []
    warnings: list[str] = []

    # assistant_turn is a v0.2 tool not in the v0.1 catalog — that's OK.
    # Tools in the contract that are NOT in the catalog AND are not
    # known v0.2 additions are flagged.
    V02_TOOLS = {
        "assistant_turn", "task_cancel", "task_resume",
        "approval_list", "approval_respond",
        "run_tail", "run_explain",
    }
    for tool in sorted(contract_tools):
        if tool not in catalog_tools and tool not in V02_TOOLS:
            errors.append(
                f"Tool {tool!r} in contract but not in catalog or v0.2 known set"
            )

    # Check for duplicates in contract
    tool_list = contract.get("tools", [])
    if len(tool_list) != len(set(tool_list)):
        seen: set[str] = set()
        for t in tool_list:
            if t in seen:
                errors.append(f"Duplicate tool in contract: {t!r}")
            seen.add(t)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "contract_tools": sorted(contract_tools),
        "catalog_tools": sorted(catalog_tools),
    }
