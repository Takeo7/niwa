#!/usr/bin/env python3
"""Fake Claude CLI that simulates a healthy probe response.

Emits a minimal functional stream (``system_init`` + ``result``)
and exits 0. Used by tests/test_readiness_probe.py to exercise the
``ok`` branch of health_service.probe_claude_cli.
"""
import json
import sys


def main():
    # Drain stdin — the probe may send an empty prompt.
    sys.stdin.read()
    events = [
        {"type": "system", "subtype": "init",
         "session_id": "probe-session", "tools": []},
        {"type": "result", "subtype": "success",
         "session_id": "probe-session",
         "result": "ok", "is_error": False,
         "permission_denials": [], "stop_reason": "end_turn"},
    ]
    for event in events:
        print(json.dumps(event), flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
