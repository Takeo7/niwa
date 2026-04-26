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
_log "checking preconditions: python3.11+, npm, git"
_require npm
_require git

# Prefer ``python3.11`` explicitly — brew on Apple Silicon installs the
# 3.11 keg but does NOT expose it as ``python3``, only ``python3.11``.
# Falling back to ``python3`` keeps Linux default installs working.
if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    _die "python 3.11+ required: install python@3.11 (brew) or python3.11 (apt)"
fi
"${PYTHON_BIN}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || _die "python 3.11+ required, found $(${PYTHON_BIN} --version 2>&1)"

# 2. Layout.
mkdir -p "${NIWA_HOME}/logs" "${NIWA_HOME}/data"

# 3. Venv.
VENV_DIR="${NIWA_HOME}/venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
if [[ ! -x "${VENV_PYTHON}" ]]; then
    _log "creating venv at ${VENV_DIR}"
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
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

# 8b. Linger (Linux only). systemd user services don't survive reboot
# unless the user has linger enabled. macOS launchd handles this via
# RunAtLoad in the plist, so it's not needed there.
#
# Skippable for tests: bootstrap tests override HOME but not USER, so
# without the escape hatch ``loginctl enable-linger "$USER"`` would
# target the real host user (mutating system state on dev boxes with
# NOPASSWD sudo, or hanging on a TTY password prompt in CI).
if [[ "${NIWA_BOOTSTRAP_SKIP_LINGER:-0}" != "1" ]]; then
    case "$(uname -s)" in
        Linux)
            LINGER_USER="${USER:-$(id -un)}"
            if ! loginctl show-user "${LINGER_USER}" 2>/dev/null | \
                 grep -q '^Linger=yes'; then
                _log "enabling user linger (requires sudo password)"
                sudo loginctl enable-linger "${LINGER_USER}" \
                    && _log "linger enabled" \
                    || _log "WARN: enable-linger failed; service will not autostart on reboot. Run manually: sudo loginctl enable-linger ${LINGER_USER}"
            else
                _log "linger already enabled"
            fi
            ;;
    esac
else
    _log "skipping linger setup (NIWA_BOOTSTRAP_SKIP_LINGER=1)"
fi

# 9. Summary. Paths are shown relative to $HOME so the message stays the
# same across machines; the service file path varies per-OS and is less
# relevant to the user's next action anyway.
cat <<EOF

Niwa v1 bootstrap complete.

  config:  ~/.niwa/config.toml
  db:      ~/.niwa/data/niwa-v1.sqlite3
  venv:    ~/.niwa/venv

Next steps:

  source ~/.niwa/venv/bin/activate
  niwa-executor start          # daemon starts at login
  make dev                     # backend :8000 + frontend :5173

Open http://127.0.0.1:5173 once dev is running.
Read README.md -> "First project" for how to create your first task.

EOF
