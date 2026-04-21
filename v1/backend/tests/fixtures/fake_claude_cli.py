#!/usr/bin/env python3
"""Fake Claude Code CLI — emits canned stream-json for tests.

Reads an events script (JSONL) and writes one line per event to stdout
with ``flush=True`` so the adapter sees them in order. Sleeps an optional
delay between lines to let tests exercise the non-blocking read path.

Environment variables:

* ``FAKE_CLAUDE_SCRIPT`` — path to a JSONL file; each non-empty line is a
  literal stdout line. Missing / empty → no output, just exit.
* ``FAKE_CLAUDE_EXIT`` — integer exit code (default ``0``).
* ``FAKE_CLAUDE_DELAY_MS`` — per-line delay in milliseconds (default ``0``).
* ``FAKE_CLAUDE_TOUCH`` — ``:``-separated paths to create before exit.
  Simulates the adapter touching the tree so future verifier evidence
  (E3 in 11b) has something to inspect. ``{pid}`` is replaced with this
  process's pid so multi-run tests land on distinct files.
* ``FAKE_CLAUDE_TRIAGE_JSON`` — JSON body to wrap in an ``assistant`` event
  when the incoming prompt on stdin contains ``"triage agent for Niwa"``.
  Lets a single fake-CLI binary serve both triage and execution stages
  without extra infra. When unset, triage prompts fall through to the
  normal ``FAKE_CLAUDE_SCRIPT`` path.

The fake is a plain Python script with a ``#!/usr/bin/env python3`` shebang.
Tests mark it executable at import time and pass its absolute path to the
adapter via ``NIWA_CLAUDE_CLI``.
"""

from __future__ import annotations

import json as _json
import os
import sys
import time


_TRIAGE_MARKER = "triage agent for Niwa"


def _emit_triage_response(body: str) -> None:
    """Wrap ``body`` in a minimal ``assistant`` stream-json event."""

    event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": body}]},
    }
    sys.stdout.write(_json.dumps(event) + "\n")
    sys.stdout.write(_json.dumps({"type": "result", "exit_code": 0}) + "\n")
    sys.stdout.flush()


def main() -> int:
    script_path = os.environ.get("FAKE_CLAUDE_SCRIPT")
    try:
        exit_code = int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))
    except ValueError:
        exit_code = 0
    try:
        delay_ms = int(os.environ.get("FAKE_CLAUDE_DELAY_MS", "0"))
    except ValueError:
        delay_ms = 0

    # Drain stdin so the adapter's ``write + close`` never blocks on a
    # full OS pipe buffer. The captured prompt is used to route triage
    # calls when ``FAKE_CLAUDE_TRIAGE_JSON`` is set.
    stdin_text = ""
    if not sys.stdin.isatty():
        try:
            stdin_text = sys.stdin.read()
        except (OSError, ValueError):
            stdin_text = ""

    triage_body = os.environ.get("FAKE_CLAUDE_TRIAGE_JSON")
    if triage_body and _TRIAGE_MARKER in stdin_text:
        # Wrap in a ```json fence so the triage parser's pass 1 matches.
        wrapped = "```json\n" + triage_body.strip() + "\n```"
        _emit_triage_response(wrapped)
        return 0

    if script_path and os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.rstrip("\n")
                if not stripped:
                    continue
                sys.stdout.write(stripped + "\n")
                sys.stdout.flush()
                if delay_ms:
                    time.sleep(delay_ms / 1000.0)

    touch = os.environ.get("FAKE_CLAUDE_TOUCH")
    if touch:
        for raw in touch.split(":"):
            path = raw.replace("{pid}", str(os.getpid())).strip()
            if not path:
                continue
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("artifact\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
