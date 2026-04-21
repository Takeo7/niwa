# PR-V1-14 — Bootstrap.sh reproducible

**Semana:** 4
**Esfuerzo:** M
**Depende de:** PR-V1-13 mergeado (safe mode finalize).

## Qué

Script shell `v1/bootstrap.sh` que deja la máquina del usuario
lista para correr Niwa v1 de un tirón:

1. Crea `~/.niwa/` con subdirectorios (`venv`, `logs`, `data`).
2. Crea venv Python en `~/.niwa/venv` y activa.
3. Instala backend editable: `pip install -e <repo>/v1/backend[dev]`.
4. Instala frontend: `cd <repo>/v1/frontend && npm install`.
5. Corre `alembic upgrade head` sobre la DB configurada.
6. Genera `~/.niwa/config.toml` con defaults si NO existe
   (preserva config existente).
7. Auto-detecta `NIWA_CLAUDE_CLI` via `which claude` y lo inyecta
   en el `config.toml`.
8. Escribe el launcher del executor en el location estándar:
   - **macOS**: `~/Library/LaunchAgents/com.niwa.executor.plist`.
   - **Linux**: `~/.config/systemd/user/niwa-executor.service`.
   - **No carga ni arranca el servicio** — eso es PR-V1-15.
9. Imprime resumen al final con próximos pasos.

Idempotente: reejecutable sin romper estado. Upserts venv / deps /
migraciones; preserva `config.toml` si existe; reescribe service
file (template fresco está OK).

## Por qué

SPEC §6: "Bootstrap: `v1/bootstrap.sh` — instala deps, crea
`~/.niwa/`, migra DB, instala systemd unit. Sin wizard
interactivo". SPEC §9 Semana 4 pedía bootstrap reproducible. Hoy
el humano tiene que instalar todo a mano por README — este PR
consolida.

## Scope — archivos que toca

```
v1/
├── bootstrap.sh                            # nuevo, ~200 LOC bash
├── templates/                              # nuevo, service templates
│   ├── com.niwa.executor.plist.tmpl        # macOS launchd
│   ├── niwa-executor.service.tmpl          # Linux systemd user
│   └── config.toml.tmpl                    # config defaults
└── backend/
    └── tests/
        └── test_bootstrap.py               # nuevo, ~120 LOC pytest
```

**HARD-CAP 400 LOC netas código+tests** (sin HANDBOOK). Proyección
~350. Si excedes, PARAS.

## Fuera de scope (explícito)

- **No carga ni arranca el servicio**. PR-V1-15 hace `launchctl load`
  / `systemctl --user enable` + helper CLI `niwa-executor`.
- **No hay uninstall / `--remove`**. Follow-up.
- **No hay modo interactivo**. Todo es unattended. Si falta algo
  (Python 3.11+, node, npm, git, gh) el script aborta con mensaje
  legible y exit ≠ 0.
- **No instala `gh`, `claude`, `node`, `python`**. Precondición del
  usuario.
- **No migra de v0.2 a v1**. Fuera de scope.
- **No reescribe `config.toml`** si ya existe (solo lo crea).
- **No toca frontend build** (`npm run build`); solo `npm install`.
- **No toca backend.**
- **No valida el contenido** del `config.toml` existente (trust
  user).

## Dependencias nuevas

- Shell: `bash`, `python3` (≥3.11), `npm`, `git`, `alembic` (via
  venv tras instalar).
- Runtime: **ninguna** Python/npm nueva en el repo.
- `gh` NO es hard requirement del bootstrap (PR-13 lo maneja como
  opcional); si está, se detecta y se loggea.

## Contrato

### Preconditions check (fail fast)

`bootstrap.sh` al arrancar valida:
- `python3 --version` ≥ 3.11 → si falla, `exit 1`.
- `npm --version` cualquiera → si falla, `exit 1`.
- `git --version` cualquiera → si falla, `exit 1`.

Si alguna falla, imprime mensaje con lo que falta y exit 1.

### Layout creado

```
~/.niwa/
├── config.toml          # default si falta; preservado si existe
├── venv/                # Python virtualenv
├── logs/                # vacío; PR-15 escribe aquí
└── data/
    └── niwa-v1.sqlite3  # creada por alembic upgrade head
```

### Config template (`v1/templates/config.toml.tmpl`)

```toml
# Niwa v1 — config edited manually (SPEC §2 / §6).
# Regenerated only if this file is missing when bootstrap.sh runs.

[claude]
# Auto-detected at bootstrap time via `which claude`; override freely.
cli = "{{CLAUDE_CLI_PATH}}"
# Global timeout for adapter + triage (seconds).
timeout = 1800

[db]
# Absolute path — bootstrap resolves $HOME at write time.
path = "{{HOME}}/.niwa/data/niwa-v1.sqlite3"

[executor]
# Polling interval for claim_next_task.
poll_interval_seconds = 5
```

`{{VARS}}` se sustituyen con `sed` o `envsubst` en bash. Si
`which claude` devuelve vacío, `CLAUDE_CLI_PATH` queda como
`"claude"` (fallback a PATH en runtime).

### Service templates

**macOS** — `v1/templates/com.niwa.executor.plist.tmpl`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.niwa.executor</string>
    <key>ProgramArguments</key>
    <array>
        <string>{{VENV_PYTHON}}</string>
        <string>-m</string>
        <string>app.executor</string>
    </array>
    <key>WorkingDirectory</key><string>{{REPO_DIR}}/v1/backend</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NIWA_CLAUDE_CLI</key><string>{{CLAUDE_CLI_PATH}}</string>
        <key>NIWA_CONFIG_PATH</key><string>{{HOME}}/.niwa/config.toml</string>
    </dict>
    <key>StandardOutPath</key><string>{{HOME}}/.niwa/logs/executor.log</string>
    <key>StandardErrorPath</key><string>{{HOME}}/.niwa/logs/executor.log</string>
    <key>KeepAlive</key><true/>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
```

**Linux** — `v1/templates/niwa-executor.service.tmpl`:

```ini
[Unit]
Description=Niwa v1 executor daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment="NIWA_CLAUDE_CLI={{CLAUDE_CLI_PATH}}"
Environment="NIWA_CONFIG_PATH={{HOME}}/.niwa/config.toml"
WorkingDirectory={{REPO_DIR}}/v1/backend
ExecStart={{VENV_PYTHON}} -m app.executor
Restart=on-failure
RestartSec=5
StandardOutput=append:{{HOME}}/.niwa/logs/executor.log
StandardError=append:{{HOME}}/.niwa/logs/executor.log

[Install]
WantedBy=default.target
```

### Flow de `bootstrap.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
NIWA_HOME="${HOME}/.niwa"

_log() { printf '[niwa-bootstrap] %s\n' "$*"; }
_require() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1"; exit 1; }; }

# 1. Preconditions
_require python3
_require npm
_require git
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" \
    || { echo "Python ≥3.11 required"; exit 1; }

# 2. Layout
mkdir -p "${NIWA_HOME}"/{logs,data}

# 3. Venv
if [[ ! -f "${NIWA_HOME}/venv/bin/python" ]]; then
    _log "creating venv"
    python3 -m venv "${NIWA_HOME}/venv"
fi
"${NIWA_HOME}/venv/bin/pip" install --quiet --upgrade pip

# 4. Backend editable
_log "installing backend"
"${NIWA_HOME}/venv/bin/pip" install --quiet -e "${SCRIPT_DIR}/backend[dev]"

# 5. Frontend
if [[ "${NIWA_BOOTSTRAP_SKIP_NPM:-0}" != "1" ]]; then
    _log "installing frontend"
    (cd "${SCRIPT_DIR}/frontend" && npm install --silent)
fi

# 6. Migrations
_log "running migrations"
DB_PATH="${NIWA_HOME}/data/niwa-v1.sqlite3"
(cd "${SCRIPT_DIR}/backend" && \
    "${NIWA_HOME}/venv/bin/alembic" \
        -x db_url="sqlite:///${DB_PATH}" upgrade head)

# 7. Config
CLAUDE_CLI_PATH="$(command -v claude || echo claude)"
if [[ ! -f "${NIWA_HOME}/config.toml" ]]; then
    _log "writing config.toml (defaults)"
    sed \
        -e "s|{{CLAUDE_CLI_PATH}}|${CLAUDE_CLI_PATH}|g" \
        -e "s|{{HOME}}|${HOME}|g" \
        "${SCRIPT_DIR}/templates/config.toml.tmpl" \
        > "${NIWA_HOME}/config.toml"
else
    _log "config.toml exists, preserving"
fi

# 8. Service file
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
        echo "Unsupported OS: $(uname -s)"; exit 1
        ;;
esac

mkdir -p "${SERVICE_DIR}"
VENV_PYTHON="${NIWA_HOME}/venv/bin/python"
sed \
    -e "s|{{CLAUDE_CLI_PATH}}|${CLAUDE_CLI_PATH}|g" \
    -e "s|{{HOME}}|${HOME}|g" \
    -e "s|{{REPO_DIR}}|${REPO_DIR}|g" \
    -e "s|{{VENV_PYTHON}}|${VENV_PYTHON}|g" \
    "${TEMPLATE}" \
    > "${SERVICE_FILE}"
_log "service file written: ${SERVICE_FILE}"

# 9. Summary
cat <<EOF

Niwa v1 bootstrap complete.

  config: ${NIWA_HOME}/config.toml
  db:     ${DB_PATH}
  venv:   ${NIWA_HOME}/venv
  service: ${SERVICE_FILE}

Next (delivered in PR-V1-15):
  macOS:  launchctl load ${SERVICE_FILE}
  Linux:  systemctl --user enable --now niwa-executor

EOF
```

## Tests

### Nuevos backend — `tests/test_bootstrap.py` (4 casos)

Todos corren `bash v1/bootstrap.sh` en subprocess con `HOME=tmp_path`
y `NIWA_BOOTSTRAP_SKIP_NPM=1` para no gastar el tiempo del CI en
`npm install`. Usan la rama `monkeypatch.setenv` + subprocess.

1. `test_fresh_install_creates_layout_and_config` — HOME vacío.
   Tras bootstrap:
   - `~/.niwa/config.toml` existe, contiene `cli = "..."` (path a
     claude o literal `"claude"`).
   - `~/.niwa/venv/bin/python` existe.
   - `~/.niwa/data/niwa-v1.sqlite3` existe tras migración.
   - Service file creado (location depende de `uname`).
   - `~/.niwa/logs` existe como directorio vacío.
2. `test_rerun_is_idempotent` — correr bootstrap dos veces; asserts:
   - `config.toml` no se sobrescribe (modifica su content entre
     runs y verifica que sigue tras la 2ª).
   - Exit code 0 en ambas.
   - DB intacta (no borrado/recreado entre runs).
3. `test_missing_python_fails_fast` — simula `python3` ausente
   via `PATH=""` + bootstrap subprocess. Exit ≠ 0, stderr
   menciona Python.
4. `test_config_substitution_replaces_placeholders` — tras fresh
   install, `config.toml` no contiene literal `{{CLAUDE_CLI_PATH}}`
   ni `{{HOME}}`.

### Baseline tras PR-V1-14

- Backend: **93 passed** (89 actuales + 4 bootstrap).
- Frontend: 6 sin cambios (no toca frontend).

## Criterio de hecho

- [ ] `bash v1/bootstrap.sh` en HOME limpio crea toda la layout y
  sale 0.
- [ ] Reejecutado, sigue saliendo 0 y preserva `config.toml`.
- [ ] `config.toml` post-bootstrap contiene path real a `claude`
  si `which claude` devuelve algo, o `"claude"` como fallback.
- [ ] Service file creado en location estándar por OS; NO cargado
  ni arrancado (eso es PR-V1-15).
- [ ] `pytest -q tests/test_bootstrap.py` → 4 passed.
- [ ] `pytest -q` completo → ≥93 passed, 0 regresiones.
- [ ] HANDBOOK sección "Bootstrap (PR-V1-14)" con flow, layout,
  env vars para test, preconditions.
- [ ] Codex ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests (sin HANDBOOK) ≤ **400**. Proyección
  ~350.

## Riesgos conocidos

- **`pip install -e` puede tardar** (≥30 s primera vez). OK para
  bootstrap; tests con `NIWA_BOOTSTRAP_SKIP_NPM=1` para no
  aumentar CI.
- **Symlinks relativos**: `SCRIPT_DIR` usa `cd && pwd` que resuelve
  symlinks. Si el repo está en una ruta con symlinks, los paths
  escritos en plist/service/config serán los resueltos. Aceptable.
- **macOS sandboxing de `~/Library/LaunchAgents`**: modernos macOS
  requieren permisos. Documentar que el usuario puede necesitar
  aceptar el dialog la primera vez.
- **Concurrent bootstrap runs**: no hay lock; si dos procesos
  corren a la vez, se pisan. MVP asume secuencial.
- **Trust en CLAUDE CLI path**: `which claude` puede apuntar a un
  binary obsoleto. Usuario puede editar `config.toml` a mano.
- **Tests con subprocess + HOME override** pueden tardar 10-20 s
  si no skipean npm. `NIWA_BOOTSTRAP_SKIP_NPM=1` lo reduce.
- **`pip install --quiet`**: puede ocultar errores legítimos.
  Bootstrap usa `set -e` así que exit ≠ 0 propaga. Debug mode
  (futuro `--verbose`).

## Notas para Claude Code

- Commits sugeridos (4-5):
  1. `feat(bootstrap): shell skeleton with preconditions and layout`
  2. `feat(bootstrap): venv + backend + frontend + migrations`
  3. `feat(bootstrap): service templates and config generation`
  4. `test(bootstrap): subprocess tests with home override`
  5. `docs(v1): handbook bootstrap section`
- **Shell style**: `set -euo pipefail` top-of-file, funciones con
  `_snake_case`, variables en `UPPER_SNAKE`, log prefijado
  `[niwa-bootstrap]`.
- **Templates separados**: los 3 templates en `v1/templates/` para
  poder leerlos por `cat` (no inline heredocs gigantes en
  `bootstrap.sh`).
- **`sed` para sustitución**: más portable que `envsubst` (no
  siempre presente).
- **Service file**: NO cargar con `launchctl`/`systemctl` — eso es
  PR-V1-15. Solo escribir el fichero.
- **Detección de OS**: `uname -s` — `Darwin` | `Linux`. Otros →
  exit 1.
- **Si algo del brief es ambiguo, PARA y reporta.**
