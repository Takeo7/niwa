#!/usr/bin/env bash
# Validate Niwa from a fresh HOME without external Claude/GitHub/Caddy/DNS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_HOME="$(mktemp -d "${TMPDIR:-/tmp}/niwa-release-home.XXXXXX")"

cleanup() {
  rm -rf "${TMP_HOME}"
}
trap cleanup EXIT

chmod 700 "${TMP_HOME}"
export HOME="${TMP_HOME}"
export NIWA_HOME="${TMP_HOME}/.niwa"
export NIWA_BOOTSTRAP_SKIP_LINGER=1

log() {
  printf '[release-gate] %s\n' "$*"
}

run() {
  log "$*"
  "$@"
}

cd "${ROOT}"

run ./bootstrap.sh

export PATH="${NIWA_HOME}/venv/bin:${PATH}"

run make test
run make smoke
run niwa-executor doctor --strict

BACKUP="${TMP_HOME}/niwa-backup.tar.gz"
RESTORE_DB="${TMP_HOME}/restored.sqlite3"
run niwa-executor backup --output "${BACKUP}"
run niwa-executor restore "${BACKUP}" --db-path "${RESTORE_DB}" --yes
test -s "${RESTORE_DB}"

log "PASS"
