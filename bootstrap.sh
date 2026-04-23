#!/usr/bin/env bash
# Niwa v1 bootstrap — reproducible install of ~/.niwa layout, venv, DB
# migrations, service file. See docs/plans/PR-V1-14-bootstrap.md.
#
# Idempotent: reruns upsert venv / deps / migrations, preserve an existing
# ``config.toml``, and always rewrite the service file with a fresh template
# render. Does NOT load/start the service — that's PR-V1-15.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${SCRIPT_DIR}"
NIWA_HOME="${HOME}/.niwa"

_log() { printf '[niwa-bootstrap] %s\n' "$*"; }
_die() { printf '[niwa-bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

_require() {
    command -v "$1" >/dev/null 2>&1 || _die "missing required tool: $1"
}

# 1. Preconditions (fail fast). We list the required tools up-front so a
# failure message always mentions the whole set, regardless of which one
# ``command -v`` trips on first.
_log "checking preconditions: python3 (>=3.11), npm, git"
_require python3
_require npm
_require git
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || _die "python 3.11+ required, found $(python3 --version 2>&1)"

# 2. Layout.
mkdir -p "${NIWA_HOME}/logs" "${NIWA_HOME}/data"

# 3. Venv.
VENV_DIR="${NIWA_HOME}/venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
if [[ ! -x "${VENV_PYTHON}" ]]; then
    _log "creating venv at ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip

# 4. Backend editable install.
_log "installing backend (editable)"
"${VENV_DIR}/bin/pip" install --quiet -e "${SCRIPT_DIR}/backend[dev]"

# 5. Frontend deps (skippable for tests).
if [[ "${NIWA_BOOTSTRAP_SKIP_NPM:-0}" != "1" ]]; then
    _log "installing frontend deps"
    (cd "${SCRIPT_DIR}/frontend" && npm install --silent)
else
    _log "skipping npm install (NIWA_BOOTSTRAP_SKIP_NPM=1)"
fi

# 6. DB migrations.
DB_PATH="${NIWA_HOME}/data/niwa-v1.sqlite3"
_log "running alembic upgrade head on ${DB_PATH}"
(cd "${SCRIPT_DIR}/backend" && \
    "${VENV_DIR}/bin/alembic" -x "db_url=sqlite:///${DB_PATH}" upgrade head)

# 7. Config (preserve if exists).
CLAUDE_CLI_PATH="$(command -v claude || echo claude)"
CONFIG_PATH="${NIWA_HOME}/config.toml"
if [[ ! -f "${CONFIG_PATH}" ]]; then
    _log "writing default config.toml"
    sed \
        -e "s|{{CLAUDE_CLI_PATH}}|${CLAUDE_CLI_PATH}|g" \
        -e "s|{{HOME}}|${HOME}|g" \
        "${SCRIPT_DIR}/templates/config.toml.tmpl" \
        > "${CONFIG_PATH}"
else
    _log "config.toml exists, preserving"
fi

# 8. Service file (written, never loaded — see PR-V1-15).
case "$(uname -s)" in
    Darwin)
        SERVICE_DIR="${HOME}/Library/LaunchAgents"
        SERVICE_FILE="${SERVICE_DIR}/com.niwa.executor.plist"
        TEMPLATE="${SCRIPT_DIR}/templates/com.niwa.executor.plist.tmpl"
        ;;
    Linux)
        SERVICE_DIR="${HOME}/.config/systemd/user"
        SERVICE_FILE="${SERVICE_DIR}/niwa-executor.service"
        TEMPLATE="${SCRIPT_DIR}/templates/niwa-executor.service.tmpl"
        ;;
    *)
        _die "unsupported OS: $(uname -s)"
        ;;
esac

mkdir -p "${SERVICE_DIR}"
sed \
    -e "s|{{CLAUDE_CLI_PATH}}|${CLAUDE_CLI_PATH}|g" \
    -e "s|{{HOME}}|${HOME}|g" \
    -e "s|{{REPO_DIR}}|${REPO_DIR}|g" \
    -e "s|{{VENV_PYTHON}}|${VENV_PYTHON}|g" \
    "${TEMPLATE}" \
    > "${SERVICE_FILE}"
_log "service file written: ${SERVICE_FILE}"

# 9. Summary.
cat <<EOF

Niwa v1 bootstrap complete.

  config:  ${CONFIG_PATH}
  db:      ${DB_PATH}
  venv:    ${VENV_DIR}
  service: ${SERVICE_FILE}

Next (delivered in PR-V1-15):
  macOS:  launchctl load ${SERVICE_FILE}
  Linux:  systemctl --user enable --now niwa-executor

EOF
