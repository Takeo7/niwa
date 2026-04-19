#!/usr/bin/env python3
"""Fake planner CLI for integration tests.

Reads a prompt from stdin and emits a <SUBTASKS>...</SUBTASKS> block
with three fixed children on stdout. Exit 0 always (the planner
tier's failure paths are covered by task-executor unit tests).

Usage:
  echo "plan this" | python3 fake_planner.py
"""

import json
import sys


def main():
    _ = sys.stdin.read()  # consume prompt; not inspected
    subtasks = [
        {"title": "Write hello.py", "priority": "media"},
        {"title": "Write test_hello.py", "priority": "media"},
        {"title": "Run pytest on the hello module", "priority": "media"},
    ]
    print("<SUBTASKS>")
    print(json.dumps(subtasks))
    print("</SUBTASKS>")
    sys.exit(0)


if __name__ == "__main__":
    main()
