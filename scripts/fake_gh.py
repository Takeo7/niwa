#!/usr/bin/env python3
"""Fake gh CLI for smoke tests.

Supports the subset of gh commands that finalize.py calls:

  gh pr create  --title T --body B --base main
  gh pr list    --json number,url,title,state,headRefName
  gh pr merge   URL --squash --delete-branch

State is persisted in the JSON file pointed to by ``FAKE_GH_STATE``
(default: ``/tmp/fake_gh_state.json``).  Each PR is assigned a fake
GitHub URL ``https://github.com/smoke/niwa/pull/<n>``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


_STATE_FILE = Path(os.environ.get("FAKE_GH_STATE", "/tmp/fake_gh_state.json"))


def _load() -> list[dict]:
    if _STATE_FILE.is_file():
        try:
            return json.loads(_STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save(prs: list[dict]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(prs, indent=2))


def _cmd_pr_create(argv: list[str]) -> int:
    """gh pr create --title T --body B [--base B] [--head H]"""
    title = ""
    body = ""
    head = ""
    i = 0
    while i < len(argv):
        if argv[i] == "--title" and i + 1 < len(argv):
            title = argv[i + 1]; i += 2
        elif argv[i] == "--body" and i + 1 < len(argv):
            body = argv[i + 1]; i += 2
        elif argv[i] in ("--base", "--head") and i + 1 < len(argv):
            if argv[i] == "--head":
                head = argv[i + 1]
            i += 2
        else:
            i += 1

    prs = _load()
    n = len(prs) + 1
    url = f"https://github.com/smoke/niwa/pull/{n}"
    prs.append({
        "number": n,
        "url": url,
        "title": title,
        "body": body,
        "headRefName": head,
        "state": "OPEN",
        "merged": False,
    })
    _save(prs)
    print(url)
    return 0


def _cmd_pr_list(argv: list[str]) -> int:
    """gh pr list --json ..."""
    prs = _load()
    # Filter only open PRs for list
    open_prs = [p for p in prs if p.get("state") == "OPEN"]
    # Build response with only requested fields
    fields_arg = ""
    for i, a in enumerate(argv):
        if a == "--json" and i + 1 < len(argv):
            fields_arg = argv[i + 1]
            break
    fields = [f.strip() for f in fields_arg.split(",")] if fields_arg else []
    result = []
    for pr in open_prs:
        if fields:
            result.append({f: pr.get(f, "") for f in fields})
        else:
            result.append(pr)
    print(json.dumps(result))
    return 0


def _cmd_pr_merge(argv: list[str]) -> int:
    """gh pr merge URL --squash --delete-branch"""
    url = argv[0] if argv else ""
    prs = _load()
    for pr in prs:
        if pr["url"] == url or str(pr["number"]) == url:
            pr["state"] = "MERGED"
            pr["merged"] = True
            _save(prs)
            print(f"✓ Merged pull request {pr['number']}")
            return 0
    # Try by number
    for pr in prs:
        if str(pr["number"]) in url:
            pr["state"] = "MERGED"
            pr["merged"] = True
            _save(prs)
            print(f"✓ Merged pull request {pr['number']}")
            return 0
    print(f"Error: PR not found: {url}", file=sys.stderr)
    return 1


def _cmd_auth_status(_argv: list[str]) -> int:
    print("✓ Logged in to github.com as smoke-user (fake)")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("fake gh: no subcommand", file=sys.stderr)
        return 1

    # dispatch: gh pr <sub> ...
    if args[0] == "pr" and len(args) > 1:
        sub = args[1]
        rest = args[2:]
        if sub == "create":
            return _cmd_pr_create(rest)
        if sub == "list":
            return _cmd_pr_list(rest)
        if sub == "merge":
            return _cmd_pr_merge(rest)
        print(f"fake gh pr: unknown subcommand '{sub}'", file=sys.stderr)
        return 1

    if args[0] == "auth" and len(args) > 1 and args[1] == "status":
        return _cmd_auth_status(args[2:])

    print(f"fake gh: unsupported command: {' '.join(args)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
