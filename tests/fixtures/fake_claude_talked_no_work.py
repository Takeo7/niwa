#!/usr/bin/env python3
"""Fake Claude CLI that talks without doing work — Bug 32 original.

Emits a conversational text answer (no tool_use, no file writes) and
finishes with ``stop_reason="end_turn"``. Used to verify the FIX-20260420
decision table still flags this case as ``needs_input`` when the
filesystem diff is empty (the "just talked" bucket).

Usage:
  echo "prompt" | python3 fake_claude_talked_no_work.py -p --output-format stream-json
"""

import json
import sys


def _emit(ev):
    print(json.dumps(ev), flush=True)


def main():
    sys.argv[1:]  # args ignored
    sys.stdin.read()  # drain prompt

    session_id = "bug32-sess-fake"
    answer = ("¿Qué stack prefieres para este proyecto — Node.js + Express "
              "o Python + FastAPI? Indícalo y procedo.")

    _emit({"type": "system", "subtype": "init",
           "session_id": session_id,
           "tools": ["Read", "Write", "Edit", "Bash"],
           "permissionMode": "bypassPermissions",
           "model": "claude-sonnet-4-6"})

    _emit({"type": "assistant", "session_id": session_id,
           "message": {"role": "assistant", "content": [
               {"type": "text", "text": answer},
           ]}})

    _emit({
        "type": "result", "subtype": "success",
        "session_id": session_id,
        "result": answer,
        "stop_reason": "end_turn",
        "is_error": False,
        "permission_denials": [],
        "cost_usd": 0.004,
        "duration_ms": 1200,
        "num_turns": 1,
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 300, "output_tokens": 80,
                  "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0},
    })

    sys.exit(0)


if __name__ == "__main__":
    main()
