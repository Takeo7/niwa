#!/usr/bin/env python3
"""Fake Codex CLI binary for integration tests.

Reads a prompt from stdin, emits JSON-line events to stdout,
and exits with code 0 (success) or 1 (if --fail flag is passed).

Also writes a file into the current working directory so that
collect_artifacts() has something to scan.

Usage:
  echo "prompt" | python3 fake_codex.py exec --json
  echo "prompt" | python3 fake_codex.py exec --json --fail   # exits with code 1
"""

import json
import os
import sys


def main():
    args = sys.argv[1:]

    # Read prompt from stdin
    prompt = sys.stdin.read()

    should_fail = "--fail" in args

    session_id = "codex-sess-001"

    # Emit JSON-line events to stdout (Codex-style format)
    events = [
        {"type": "status", "status": "started",
         "session_id": session_id},
        {"type": "message", "role": "assistant",
         "content": f"Working on: {prompt[:50]}"},
        {"type": "command", "name": "shell",
         "command": "echo done"},
        {"type": "command_output", "output": "done",
         "exit_code": 0},
        {"type": "message", "role": "assistant",
         "content": "Task completed successfully."},
    ]

    if should_fail:
        events.append({"type": "error",
                       "message": "Simulated Codex failure"})
    else:
        events.append({
            "type": "result",
            "status": "completed",
            "session_id": session_id,
            "cost_usd": 0.015,
            "duration_ms": 3000,
            "model": "o4-mini",
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 300,
                "total_tokens": 500,
            },
        })

    for event in events:
        print(json.dumps(event), flush=True)

    # Write an artifact file in cwd
    artifact_path = os.path.join(os.getcwd(), "patch.diff")
    try:
        with open(artifact_path, "w") as f:
            f.write(f"--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new\n")
    except OSError:
        pass

    sys.exit(1 if should_fail else 0)


if __name__ == "__main__":
    main()
