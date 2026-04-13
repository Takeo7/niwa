#!/usr/bin/env python3
"""Fake Claude CLI that blocks for a configurable duration without output.

Used to test that the heartbeat thread fires independently of stdout.

Usage:
  echo "prompt" | python3 fake_claude_slow.py -p --output-format stream-json ...

Reads FAKE_CLAUDE_DELAY_SECONDS from env (default 3).
Emits one init line, then sleeps, then emits result.
"""

import json
import os
import sys
import time


def main():
    sys.stdin.read()
    delay = float(os.environ.get("FAKE_CLAUDE_DELAY_SECONDS", "3"))

    # Emit init immediately
    print(json.dumps({
        "type": "system", "subtype": "init",
        "session_id": "slow-sess-001",
    }), flush=True)

    # Block without any output
    time.sleep(delay)

    # Emit result
    print(json.dumps({
        "type": "result", "session_id": "slow-sess-001",
        "cost_usd": 0.01, "duration_ms": int(delay * 1000),
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }), flush=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
