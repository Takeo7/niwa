#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="$ROOT_DIR/infra"
DB_PATH="$ROOT_DIR/data/desk.sqlite3"
TASK_ID=""
SKIP_DEPLOY=0
SKIP_COMMIT=0
FORCE_DEPLOY=0
COMMIT_MESSAGE=""
POST_DEPLOY_URL="${DESK_POST_DEPLOY_URL:-http://127.0.0.1:8080/health}"
CHANGES_PRESENT=0
COMMIT_DONE=0
REPO_TOP="$(git -C "$ROOT_DIR" rev-parse --show-toplevel)"
PROJECT_PATH="$(realpath --relative-to="$REPO_TOP" "$ROOT_DIR")"
COMPOSE_FILE="$INFRA_DIR/docker-compose.yml"
COMPOSE_SERVICE="desk"

usage() {
  cat <<'EOF'
Uso:
  desk_change_flow.sh --task-id <uuid> [--commit-message "..."] [--skip-deploy] [--skip-commit] [--force-deploy]

Flujo:
  1. validación local (py_compile + health local si Desk está arriba)
  2. commit si hay cambios y no se usa --skip-commit
  3. recreate de Desk si hay cambios en el proyecto o se fuerza
  4. verificación post-deploy
  5. sello de cierre en la tarea de Desk + status=hecha

Reglas:
  - Las tareas del proyecto Desk no deben marcarse como hechas manualmente.
  - Este script añade el marcador requerido en notes tras validar el cierre.
EOF
}

log() { printf '[desk-flow] %s\n' "$*"; }
fail() { printf '[desk-flow][error] %s\n' "$*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Falta comando requerido: $1"
}

changed_paths() {
  git -C "$REPO_TOP" status --porcelain -- "$PROJECT_PATH"
}

has_repo_changes() {
  [[ -n "$(changed_paths)" ]]
}

should_deploy() {
  if [[ "$FORCE_DEPLOY" -eq 1 ]]; then
    return 0
  fi
  if [[ "$COMMIT_DONE" -eq 1 || "$CHANGES_PRESENT" -eq 1 ]]; then
    return 0
  fi
  return 1
}

validate_task_exists() {
  python3 - "$DB_PATH" "$TASK_ID" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
row = conn.execute("SELECT id, title, project_id, status FROM tasks WHERE id=?", (sys.argv[2],)).fetchone()
if not row:
    raise SystemExit("Tarea no encontrada")
if row[2] != 'proj-desk':
    raise SystemExit("La tarea no pertenece al proyecto Desk")
print(row[1])
PY
}

run_guard_check() {
  log 'Ejecutando guard de archivos protegidos'
  python3 "$ROOT_DIR/scripts/guard_protected_files.py" --revert --project-path "$PROJECT_PATH" \
    || fail 'Guard detectó modificaciones prohibidas en archivos protegidos (revertidas)'
}

run_local_validation() {
  if has_repo_changes; then
    CHANGES_PRESENT=1
  fi
  run_guard_check
  log 'Ejecutando validación pre-deploy (Python + JS + HTML)'
  python3 "$ROOT_DIR/scripts/validate_desk.py" --pre-deploy || fail 'Validación pre-deploy falló'
}

run_commit() {
  if [[ "$SKIP_COMMIT" -eq 1 ]]; then
    log 'Saltando commit por flag'
    return
  fi
  if ! has_repo_changes; then
    log 'Sin cambios para commit dentro de Desk'
    return
  fi
  if [[ -z "$COMMIT_MESSAGE" ]]; then
    COMMIT_MESSAGE="desk: close task $TASK_ID with verified deploy flow"
  fi
  git -C "$REPO_TOP" add --all -- "$PROJECT_PATH"
  git -C "$REPO_TOP" commit -m "$COMMIT_MESSAGE" -- "$PROJECT_PATH"
  COMMIT_DONE=1
  log 'Commit realizado solo con cambios de Desk'
}

container_is_running() {
  local container_id=""
  container_id="$(docker compose -f "$COMPOSE_FILE" ps -q "$COMPOSE_SERVICE" 2>/dev/null || true)"
  [[ -n "$container_id" ]] || return 1
  local status=""
  status="$(docker inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || true)"
  [[ "$status" == 'running' ]]
}

wait_for_container() {
  local attempts=30
  local sleep_seconds=2
  local i
  for ((i=1; i<=attempts; i++)); do
    if container_is_running; then
      log "Contenedor $COMPOSE_SERVICE arriba (intento $i/$attempts)"
      return 0
    fi
    sleep "$sleep_seconds"
  done
  return 1
}

deploy_if_needed() {
  if [[ "$SKIP_DEPLOY" -eq 1 ]]; then
    log 'Saltando deploy por flag'
    return
  fi
  if ! should_deploy; then
    log 'No detecto cambios pendientes tras commit; no hago recreate'
    return
  fi
  require_cmd docker
  if [[ ! -f "$COMPOSE_FILE" ]]; then
    fail 'No existe infra/docker-compose.yml'
  fi
  log 'Recreando Desk con docker compose up -d --force-recreate'
  docker compose -f "$COMPOSE_FILE" up -d --force-recreate "$COMPOSE_SERVICE"
  wait_for_container || fail 'Desk no quedó corriendo tras el recreate'
}

verify_post_deploy() {
  require_cmd docker
  [[ -f "$COMPOSE_FILE" ]] || fail 'No existe infra/docker-compose.yml'
  wait_for_container || fail 'Desk no está corriendo para verificar el post-deploy'

  log 'Ejecutando validación post-deploy (endpoints)'
  python3 "$ROOT_DIR/scripts/validate_desk.py" --post-deploy --base-url "$POST_DEPLOY_URL" || fail 'Validación post-deploy falló'
}

close_task() {
  python3 "$ROOT_DIR/scripts/desk_close_task.py" "$DB_PATH" "$TASK_ID" >/dev/null
  log 'Tarea marcada como hecha con cierre verificado'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task-id) TASK_ID="${2:-}"; shift 2 ;;
    --commit-message) COMMIT_MESSAGE="${2:-}"; shift 2 ;;
    --skip-deploy) SKIP_DEPLOY=1; shift ;;
    --skip-commit) SKIP_COMMIT=1; shift ;;
    --force-deploy) FORCE_DEPLOY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Argumento no reconocido: $1" ;;
  esac
done

[[ -n "$TASK_ID" ]] || { usage; fail 'Falta --task-id'; }
require_cmd git
require_cmd python3
require_cmd curl

log "Tarea Desk: $(validate_task_exists)"
run_local_validation
run_commit
deploy_if_needed
verify_post_deploy
close_task
log 'Flujo completado'
