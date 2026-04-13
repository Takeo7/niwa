#!/usr/bin/env python3
"""Fake Claude CLI that emits tool_use events with policy violations.

Used to test the runtime capability checking in the ClaudeCodeAdapter.

Supports two violation modes:
  --violation shell   → emits Bash tool_use with `rm -rf /tmp/danger`
  --violation write   → emits Write tool_use to /etc/passwd

After emitting the violating event, sleeps to give the adapter time to
detect the violation and kill the process.

Usage:
  echo "prompt" | python3 fake_claude_violation.py -p --output-format stream-json --violation shell
"""

import json
import sys
import time


def main():
    args = sys.argv[1:]
    sys.stdin.read()

    # Parse --violation flag
    violation = "shell"
    if "--violation" in args:
        idx = args.index("--violation")
        if idx + 1 < len(args):
            violation = args[idx + 1]

    session_id = "violation-sess-001"

    # Emit init event
    print(json.dumps({
        "type": "system", "subtype": "init",
        "session_id": session_id,
        "tools": ["Read", "Write", "Bash", "Edit"],
    }), flush=True)

    # Emit an assistant message first
    print(json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Let me work on this..."}],
        },
    }), flush=True)

    # Emit the violating tool_use
    if violation == "shell":
        print(json.dumps({
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "rm -rf /tmp/danger"},
        }), flush=True)
    elif violation == "write":
        print(json.dumps({
            "type": "tool_use",
            "name": "Write",
            "input": {
                "file_path": "/etc/passwd",
                "content": "should not be written",
            },
        }), flush=True)

    # Sleep long enough for the adapter to detect and kill us.
    # If the adapter is working correctly, it will SIGTERM/SIGKILL
    # this process before the sleep completes.
    time.sleep(30)

    # If we reach here, the adapter didn't kill us — test should fail
    print(json.dumps({
        "type": "result", "session_id": session_id,
        "cost_usd": 0.01,
    }), flush=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
