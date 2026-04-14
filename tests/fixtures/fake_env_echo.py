#!/usr/bin/env python3
"""Fake CLI binary that prints selected env vars as JSON to stdout.

Used to verify that the executor/adapter correctly injects
credentials into the subprocess environment.

Emits a single JSON-line result event containing the env vars,
then exits 0.
"""

import json
import os
import sys


def main():
    # Read and discard stdin (prompt)
    sys.stdin.read()

    env_report = {}
    for key in ("OPENAI_ACCESS_TOKEN", "CODEX_HOME",
                "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
                "NO_COLOR"):
        val = os.environ.get(key)
        if val is not None:
            env_report[key] = val

    events = [
        {"type": "status", "status": "started", "session_id": "env-test"},
        {"type": "result", "status": "completed", "session_id": "env-test",
         "env_report": env_report,
         "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                    "total_tokens": 2},
         "model": "test", "cost_usd": 0.0, "duration_ms": 1},
    ]
    for event in events:
        print(json.dumps(event), flush=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
