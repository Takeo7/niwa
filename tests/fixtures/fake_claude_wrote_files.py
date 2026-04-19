#!/usr/bin/env python3
"""Fake Claude CLI for FIX-20260420 Bug 35 integration tests.

Reproduces the exact shape observed on 2026-04-19: Claude writes three
files via ``Write`` tool calls wrapped inside ``assistant.message.content[]``
blocks (the real nested format, NOT the top-level synthetic form used by
``fake_claude.py``). No top-level ``{"type":"tool_use"}`` messages are
emitted.

Writes ``index.html``, ``style.css``, ``app.js`` in cwd so the filesystem
diff has three added entries.

Usage:
  echo "prompt" | python3 fake_claude_wrote_files.py -p --output-format stream-json

Flags honoured:
  --fail         exit 1 after emitting events (optional error path).
"""

import json
import os
import sys


def _emit(ev):
    print(json.dumps(ev), flush=True)


def main():
    args = sys.argv[1:]
    sys.stdin.read()  # drain prompt
    should_fail = "--fail" in args

    session_id = "bug35-sess-fake"
    _emit({"type": "system", "subtype": "init",
           "session_id": session_id,
           "tools": ["Read", "Write", "Edit", "Bash"],
           "permissionMode": "bypassPermissions",
           "model": "claude-sonnet-4-6"})

    # Introductory text-only assistant message.
    _emit({"type": "assistant", "session_id": session_id,
           "message": {"role": "assistant",
                       "content": [{"type": "text",
                                    "text": "I'll create the page."}]}})

    files = [
        ("index.html",
         "<!doctype html><html><body><button id=b>Pulsa</button>"
         "<script src=app.js></script></body></html>"),
        ("style.css",
         "body{font-family:sans-serif}.moved{transform:translateX(60px)}"),
        ("app.js",
         "document.getElementById('b').addEventListener('click',"
         "function(){this.classList.toggle('moved')})"),
    ]

    for i, (name, content) in enumerate(files, start=1):
        tool_id = f"toolu_{i:02d}"
        # Nested tool_use inside assistant content — the shape the
        # pre-FIX parser missed.
        _emit({"type": "assistant", "session_id": session_id,
               "message": {"role": "assistant", "content": [
                   {"type": "tool_use", "id": tool_id, "name": "Write",
                    "input": {"file_path": name, "content": content}},
               ]}})
        # tool_result is emitted as a `user` message in real Claude CLI.
        _emit({"type": "user", "session_id": session_id,
               "message": {"role": "user", "content": [
                   {"type": "tool_result", "tool_use_id": tool_id,
                    "content": [{"type": "text",
                                 "text": f"File created successfully at {name}"}],
                    "is_error": False},
               ]}})
        # Materialise the file so filesystem diff sees it.
        try:
            with open(os.path.join(os.getcwd(), name), "w",
                      encoding="utf-8") as fh:
                fh.write(content)
        except OSError:
            pass

    _emit({"type": "assistant", "session_id": session_id,
           "message": {"role": "assistant",
                       "content": [{"type": "text",
                                    "text": "Listo. Pulsa el botón "
                                            "para ver el cambio."}]}})

    _emit({
        "type": "result", "subtype": "success",
        "session_id": session_id,
        "result": "Listo. Pulsa el botón para ver el cambio.",
        "stop_reason": "end_turn",
        "is_error": False,
        "permission_denials": [],
        "cost_usd": 0.031,
        "duration_ms": 8420,
        "num_turns": 5,
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 6850, "output_tokens": 360,
                  "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0},
    })

    sys.exit(1 if should_fail else 0)


if __name__ == "__main__":
    main()
