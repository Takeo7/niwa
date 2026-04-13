#!/usr/bin/env python3
"""Fake Claude CLI binary for integration tests.

Reads a prompt from stdin, emits stream-json events to stdout,
and exits with code 0 (success) or 1 (if --fail flag is passed).

Also writes a file into the current working directory so that
collect_artifacts() has something to scan.

Usage:
  echo "prompt" | python3 fake_claude.py -p --output-format stream-json --model claude-sonnet-4-6
  echo "prompt" | python3 fake_claude.py -p --output-format stream-json --resume sess-123
  echo "prompt" | python3 fake_claude.py --fail   # exits with code 1
"""

import json
import sys
import os


def main():
    args = sys.argv[1:]

    # Read prompt from stdin
    prompt = sys.stdin.read()

    should_fail = "--fail" in args

    # Extract session_id from --resume if present
    session_id = "fake-session-001"
    if "--resume" in args:
        idx = args.index("--resume")
        if idx + 1 < len(args):
            session_id = args[idx + 1]

    # Emit stream-json events to stdout
    events = [
        {"type": "system", "subtype": "init", "session_id": session_id,
         "tools": ["Read", "Write", "Bash"]},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": f"Working on: {prompt[:50]}"}],
        }},
        {"type": "tool_use", "name": "Bash", "input": {"command": "echo done"}},
        {"type": "tool_result", "content": "done"},
        {"type": "assistant", "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Task completed successfully."}],
        }},
    ]

    if should_fail:
        events.append({"type": "error", "error": {"message": "Simulated failure"}})
    else:
        events.append({
            "type": "result",
            "subtype": "success",
            "session_id": session_id,
            "cost_usd": 0.042,
            "duration_ms": 5200,
            "duration_api_ms": 3800,
            "num_turns": 2,
            "is_error": False,
            "model": "claude-sonnet-4-6",
            "usage": {
                "input_tokens": 1500,
                "output_tokens": 800,
                "cache_read_input_tokens": 300,
                "cache_creation_input_tokens": 100,
            },
        })

    for event in events:
        print(json.dumps(event), flush=True)

    # Write an artifact file in cwd (if artifact_root is cwd)
    artifact_path = os.path.join(os.getcwd(), "output.md")
    try:
        with open(artifact_path, "w") as f:
            f.write(f"# Result\n\nProcessed: {prompt[:100]}\n")
    except OSError:
        pass  # cwd might not be writable in some test setups

    sys.exit(1 if should_fail else 0)


if __name__ == "__main__":
    main()
