#!/usr/bin/env python3
"""Fake Claude CLI that simulates expired credentials.

Exits 0 with an empty stdout and empty stderr — the exact shape the
Claude CLI 2.1.97 exhibits when ``~/.claude/.credentials.json`` is
expired or malformed. Used by tests/test_readiness_probe.py to
exercise the ``credential_error`` branch of probe_claude_cli.
"""
import sys


def main():
    sys.stdin.read()
    sys.exit(0)


if __name__ == "__main__":
    main()
