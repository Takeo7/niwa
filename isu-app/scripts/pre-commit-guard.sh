#!/usr/bin/env bash
# Pre-commit hook: block commits that modify Desk protected files
# unless ALLOW_PROTECTED_COMMIT=1 is set (for manual interventions).
#
# Install: cp scripts/pre-commit-guard.sh ../../.git/hooks/pre-commit && chmod +x ../../.git/hooks/pre-commit

set -euo pipefail

if [[ "${ALLOW_PROTECTED_COMMIT:-0}" == "1" ]]; then
    exit 0
fi

PROTECTED_FILES=(
    "Desk/backend/app.py"
    "Desk/infra/docker-compose.yml"
    "Desk/infra/Dockerfile"
    "Desk/.env"
    "Desk/db/schema.sql"
    "config/openclaw.json"
    "config/auth-profiles.json"
    "scripts/send_audio_raw.sh"
    "scripts/send_audio.sh"
    "security/security-audit.py"
    "security/prompt_injection_scan.py"
    "scripts/task-worker.sh"
    "scripts/task-executor.sh"
)

STAGED=$(git diff --cached --name-only 2>/dev/null || true)
BLOCKED=()

for file in "${PROTECTED_FILES[@]}"; do
    if echo "$STAGED" | grep -qF "$file"; then
        BLOCKED+=("$file")
    fi
done

if [[ ${#BLOCKED[@]} -gt 0 ]]; then
    echo "[pre-commit] BLOQUEADO: los siguientes archivos protegidos están en staging:"
    for f in "${BLOCKED[@]}"; do
        echo "  - $f"
    done
    echo ""
    echo "Si el cambio es intencional, ejecuta:"
    echo "  ALLOW_PROTECTED_COMMIT=1 git commit ..."
    exit 1
fi

# Check for dangerous patterns in staged diffs
DIFF=$(git diff --cached -U0 2>/dev/null || true)

if echo "$DIFF" | grep -qP '^\+.*(DESK_PASSWORD|DESK_SESSION_SECRET|CLAUDE_BRIDGE_TOKEN)\s*=\s*["\x27]?["\x27]?\s*$'; then
    echo "[pre-commit] BLOQUEADO: se detectó blanqueo de defaults críticos (password/secret/token = empty)"
    echo "Este tipo de cambio destruye la operación de Desk."
    exit 1
fi

if echo "$DIFF" | grep -qP '^\+.*(DESK_PASSWORD|DESK_SESSION_SECRET|CLAUDE_BRIDGE_TOKEN)\s*=\s*None\s*$'; then
    echo "[pre-commit] BLOQUEADO: se detectó asignación None a defaults críticos"
    exit 1
fi

if echo "$DIFF" | grep -qP '^\+.*os\.environ\[\s*["\x27](DESK_PASSWORD|DESK_SESSION_SECRET|CLAUDE_BRIDGE_TOKEN)["\x27]\]'; then
    echo "[pre-commit] BLOQUEADO: se detectó os.environ[] sin fallback para variable crítica"
    echo "Debe usarse os.environ.get() con un default no vacío."
    exit 1
fi

if echo "$DIFF" | grep -qP '^\+.*sys\.exit\(.*(missing|required|not set|must be set|undefined)'; then
    echo "[pre-commit] BLOQUEADO: se detectó sys.exit() por env var faltante"
    echo "Desk usa defaults seguros para desarrollo; sys.exit por env var no es aceptable."
    exit 1
fi

if echo "$DIFF" | grep -qP '^\+.*raise\s+(SystemExit|RuntimeError|ValueError)\(.*(missing|required|not set|must be set)'; then
    echo "[pre-commit] BLOQUEADO: se detectó raise exception por env var faltante"
    echo "Desk usa defaults seguros para desarrollo; hard exits por env var no es aceptable."
    exit 1
fi

exit 0
