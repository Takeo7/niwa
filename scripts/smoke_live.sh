#!/usr/bin/env bash
# Optional live tools check. Deterministic CI/smoke must not require this.
set -euo pipefail

if [[ "${NIWA_SMOKE_LIVE:-0}" != "1" ]]; then
  echo "SKIP smoke-live live tools check: set NIWA_SMOKE_LIVE=1 to check real claude/gh tools"
  exit 0
fi

echo "smoke-live live tools check: checking local claude CLI and gh auth only"

missing=0
if ! command -v claude >/dev/null 2>&1; then
  echo "MISSING claude CLI"
  missing=1
else
  claude --version >/dev/null
  echo "OK claude CLI"
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "MISSING gh CLI"
  missing=1
elif ! gh auth status >/dev/null 2>&1; then
  echo "MISSING gh authenticated session"
  missing=1
else
  echo "OK gh authenticated session"
fi

if [[ "${missing}" != "0" ]]; then
  echo "FAIL smoke-live live tools check: live tools are unavailable"
  exit 1
fi

echo "PASS smoke-live live tools check"
