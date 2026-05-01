#!/usr/bin/env python3
"""Deterministic fake GitHub CLI for Niwa smoke tests.

The script implements the tiny subset of ``gh`` used by Niwa's finalize and
pull-list paths. It persists state to ``FAKE_GH_STATE`` so smoke checks can
assert that PR creation and dangerous-mode merge happened without touching
GitHub.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_REPO_URL = "https://github.com/smoke/niwa"


def _state_path() -> Path:
    raw = os.environ.get("FAKE_GH_STATE")
    if not raw:
        raw = str(Path.cwd() / ".fake-gh-state.json")
    return Path(raw)


def _load() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"prs": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"prs": []}
    if not isinstance(data, dict) or not isinstance(data.get("prs"), list):
        return {"prs": []}
    return data


def _save(data: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _option(args: list[str], name: str, default: str = "") -> str:
    try:
        idx = args.index(name)
    except ValueError:
        return default
    if idx + 1 >= len(args):
        return default
    return args[idx + 1]


def _pr_create(args: list[str]) -> int:
    data = _load()
    prs = data["prs"]
    number = len(prs) + 1
    base_url = os.environ.get("FAKE_GH_REPO_URL", DEFAULT_REPO_URL).rstrip("/")
    url = f"{base_url}/pull/{number}"
    pr = {
        "number": number,
        "url": url,
        "title": _option(args, "--title", f"Smoke PR {number}"),
        "body": _option(args, "--body", ""),
        "headRefName": _option(args, "--head", ""),
        "state": "OPEN",
        "merged": False,
        "mergeable": "MERGEABLE",
        "statusCheckRollup": [],
    }
    prs.append(pr)
    _save(data)
    sys.stdout.write(url + "\n")
    return 0


def _find_pr(data: dict[str, Any], ref: str) -> dict[str, Any] | None:
    match = re.search(r"/pull/(\d+)", ref)
    wanted = int(match.group(1)) if match else None
    for pr in data["prs"]:
        if wanted is not None and pr.get("number") == wanted:
            return pr
        if pr.get("url") == ref:
            return pr
    return None


def _pr_merge(args: list[str]) -> int:
    if not args:
        sys.stderr.write("missing PR reference\n")
        return 1
    data = _load()
    pr = _find_pr(data, args[0])
    if pr is None:
        sys.stderr.write(f"pull request not found: {args[0]}\n")
        return 1
    pr["state"] = "MERGED"
    pr["merged"] = True
    _save(data)
    return 0


def _pr_list(args: list[str]) -> int:
    data = _load()
    state = _option(args, "--state", "open").upper()
    prs = data["prs"]
    if state != "ALL":
        prs = [p for p in prs if str(p.get("state", "")).upper() == state]
    sys.stdout.write(json.dumps(prs) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:2] == ["pr", "create"]:
        return _pr_create(args[2:])
    if args[:2] == ["pr", "merge"]:
        return _pr_merge(args[2:])
    if args[:2] == ["pr", "list"]:
        return _pr_list(args[2:])
    sys.stderr.write("fake gh supports: pr create, pr merge, pr list\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
