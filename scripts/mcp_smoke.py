#!/usr/bin/env python3
"""Small HTTP JSON-RPC smoke check for Niwa MCP."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


URL = os.environ.get("NIWA_MCP_URL", "http://127.0.0.1:8000/api/mcp")
TOKEN = os.environ.get("NIWA_MCP_TOKEN")


def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    try:
        init = call("initialize")
        ping = call("ping")
    except urllib.error.HTTPError as exc:
        print(f"FAIL: Niwa MCP endpoint returned HTTP {exc.code} at {URL}")
        return 1
    except urllib.error.URLError as exc:
        print(f"SKIP: Niwa MCP endpoint unavailable at {URL}: {exc}")
        return 0

    if "error" in init or "error" in ping:
        print(json.dumps({"initialize": init, "ping": ping}, indent=2))
        return 1

    print("initialize: ok")
    print("ping: ok")

    if not TOKEN:
        print("tools/list: skipped (set NIWA_MCP_TOKEN to check authenticated tools)")
        return 0

    tools = call("tools/list")
    if "error" in tools:
        print(json.dumps(tools, indent=2))
        return 1
    names = sorted(tool["name"] for tool in tools["result"]["tools"])
    print("tools/list: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
