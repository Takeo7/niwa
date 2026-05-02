#!/usr/bin/env python3
"""Print an evidence-based acceptance summary without running gates."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_SMOKE_REPORT = Path(".smoke/report.json")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _print_smoke(report: dict[str, Any] | None, path: Path) -> bool:
    print("Automated smoke evidence")
    if report is None:
        print(f"- make smoke: no report found at {path}; run make smoke first")
        return False

    result = str(report.get("result", "UNKNOWN"))
    print(f"- make smoke: {result}")
    print(f"- report: {path}")
    if report.get("start_time"):
        print(f"- date: {report['start_time']}")
    checks = report.get("checks", [])
    failed = False
    if isinstance(checks, list):
        for check in checks:
            if not isinstance(check, dict):
                continue
            name = check.get("name", "unknown")
            passed = bool(check.get("passed"))
            failed = failed or not passed
            status = "PASS" if passed else "FAIL"
            print(f"  - {status}: {name}")
    return result == "PASS" and not failed


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if args else DEFAULT_SMOKE_REPORT
    print("Niwa acceptance summary")
    print("=======================")
    smoke_ok = _print_smoke(_load_json(path), path)
    print()
    print("Automated gates that must be recorded separately")
    print("- cd backend && pytest -q")
    print("- cd frontend && npm test -- --run")
    print("- make release-gate")
    print()
    print("Optional live gates")
    print("- make smoke-live: live tools check only; requires NIWA_SMOKE_LIVE=1")
    print()
    print("Manual infrastructure checks")
    print("- DNS, TLS, Caddy install/reload, tunnels, real Claude, and real GitHub")
    print("  are operator-owned and are not proven by CI or this summary.")
    return 0 if smoke_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
