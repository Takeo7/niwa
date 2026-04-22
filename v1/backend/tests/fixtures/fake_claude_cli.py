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
* ``FAKE_CLAUDE_SESSION_ID`` — PR-V1-22 resume support. When set, the
  fake emits a ``system`` / ``init`` event as the first stdout line
  carrying this value as ``session_id`` so adapter tests can assert
  that ``ClaudeCodeAdapter.session_id`` captures it. Has no effect in
  triage short-circuit mode.
* ``FAKE_CLAUDE_TRIAGE_JSON`` — PR-V1-12b keyword-dispatch. When the
  prompt (read from stdin) contains the literal ``"triage agent for
  Niwa"`` the fake switches to triage mode: it emits a single
  ``assistant`` event wrapping this JSON in a ```json fence``` and
  exits 0, bypassing ``FAKE_CLAUDE_SCRIPT``/``FAKE_CLAUDE_EXIT``. If
  the env var is unset in triage mode, a neutral ``execute`` decision
  with empty subtasks is emitted so legacy tests keep working. The
  JSON is consumed **once** — subsequent triage invocations within
  the same pytest process fall back to the neutral execute payload.
  This bounds recursion when a ``split`` decision produces subtasks
  that would otherwise be re-triaged with the same verdict forever.

The fake is a plain Python script with a ``#!/usr/bin/env python3`` shebang.
Tests mark it executable at import time and pass its absolute path to the
adapter via ``NIWA_CLAUDE_CLI``.
"""

from __future__ import annotations

import json
import os
import sys
import time


_TRIAGE_KEYWORD = "triage agent for Niwa"
_DEFAULT_TRIAGE_JSON = json.dumps(
    {"decision": "execute", "subtasks": [], "rationale": "default"}
)


def _read_stdin_prompt() -> str:
    """Drain stdin without blocking forever when the adapter closed early."""

    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return ""
    return data or ""


def _emit_triage_response(raw_json: str) -> None:
    """Write one ``assistant`` event whose text wraps ``raw_json`` in a fence."""

    text = f"```json\n{raw_json}\n```"
    event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }
    sys.stdout.write(json.dumps(event) + "\n")
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

    # PR-V1-12b: triage keyword-dispatch. The adapter writes the prompt to
    # stdin — if it carries the literal keyword, short-circuit to a
    # deterministic triage payload and exit 0, regardless of what the
    # regular script path would do.
    prompt = _read_stdin_prompt()
    if _TRIAGE_KEYWORD in prompt:
        payload = os.environ.get("FAKE_CLAUDE_TRIAGE_JSON")
        marker = os.environ.get("FAKE_CLAUDE_TRIAGE_MARKER")
        if payload and marker:
            # Consume the scripted decision once: first call honours the
            # payload and drops the marker; every subsequent call in the
            # same test falls back to the neutral ``execute`` default.
            # Bounds the split recursion a repeated ``split`` verdict
            # would otherwise cause.
            if os.path.exists(marker):
                _emit_triage_response(_DEFAULT_TRIAGE_JSON)
            else:
                open(marker, "w").close()
                _emit_triage_response(payload)
        else:
            _emit_triage_response(payload or _DEFAULT_TRIAGE_JSON)
        return 0

    session_id = os.environ.get("FAKE_CLAUDE_SESSION_ID")
    if session_id:
        init_event = {
            "type": "system",
            "subtype": "init",
            "session_id": session_id,
        }
        sys.stdout.write(json.dumps(init_event) + "\n")
        sys.stdout.flush()

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
