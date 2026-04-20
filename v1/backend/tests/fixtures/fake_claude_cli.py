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

The fake is a plain Python script with a ``#!/usr/bin/env python3`` shebang.
Tests mark it executable at import time and pass its absolute path to the
adapter via ``NIWA_CLAUDE_CLI``.
"""

from __future__ import annotations

import os
import sys
import time


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

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
