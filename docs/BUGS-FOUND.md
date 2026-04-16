# Bugs preexistentes encontrados fuera del scope de cada PR

Cada entrada: fecha, PR donde se encontró, descripción, ubicación, severidad.

Formato sugerido:

```
## YYYY-MM-DD — encontrado durante PR-XX

**Descripción:** qué está mal.
**Ubicación:** archivo:línea o componente.
**Severidad:** crítico | alto | medio | bajo.
**PR futuro donde se arreglará:** PR-XX o "pendiente de asignar".
```

---

## 2026-04-12 — encontrado durante PR-01

### Bug 1: Migración 004 viola invariante — borra tablas que schema.sql define

**Descripción:** `schema.sql` define las tablas `day_focus`, `day_focus_tasks`, `task_labels`, `task_metrics` y `kanban_columns`, pero la migración `004_cleanup.sql` las elimina con `DROP TABLE IF EXISTS`. `schema.sql` no refleja el estado real post-migraciones para estas tablas. Viola la invariante adoptada: "schema.sql representa el estado post-migración de un fresh install."
**Ubicación:** `niwa-app/db/schema.sql` (tablas day_focus, day_focus_tasks, task_labels, task_metrics, kanban_columns) y `niwa-app/db/migrations/004_cleanup.sql`.
**Severidad:** media.
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de schema.sql).

### Bug 2: Migración 003 viola invariante — deployments no está en schema.sql

**Descripción:** La migración `003_deployments.sql` crea la tabla `deployments`, pero `schema.sql` no la incluye. Un fresh install que solo aplique `schema.sql` no tendrá esta tabla. Viola la invariante: las migraciones que añaden tablas deben reflejarse en schema.sql.
**Ubicación:** `niwa-app/db/migrations/003_deployments.sql` define `deployments`; `niwa-app/db/schema.sql` no la incluye.
**Severidad:** media.
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de schema.sql).

### Bug 3: Migración 005 viola invariante — idx_settings_key no está en schema.sql

**Descripción:** La migración `005_services_and_settings_unify.sql` crea el índice `idx_settings_key`, pero `schema.sql` no lo incluye. Viola la invariante: las migraciones que añaden índices deben reflejarse en schema.sql.
**Ubicación:** `niwa-app/db/migrations/005_services_and_settings_unify.sql` define `idx_settings_key`; `niwa-app/db/schema.sql` no lo incluye.
**Severidad:** media.
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de schema.sql).

## 2026-04-13 — encontrado durante PR-02

### Bug 4: Datos preexistentes con `status='revision'` que semánticamente deberían ser `waiting_input`

**Descripción:** Antes de PR-02, `task_request_input` (MCP tool) escribía `status='revision'` cuando el agente necesitaba input humano. El status correcto es `waiting_input` (corregido en PR-02). Cualquier base de datos de producción creada antes de PR-02 puede tener tareas con `status='revision'` que semánticamente representan solicitudes de input, no revisiones de deliverables.
**Ubicación:** Tabla `tasks`, filas donde `status='revision'` y la timeline contiene un evento `type='alerted'` con `author='claude'`.
**Severidad:** baja (no hay instancias de producción con datos afectados al momento de PR-02).
**PR futuro donde se arreglará:** pendiente de asignar — cleanup operacional manual, no migración automática.

## 2026-04-13 — encontrado durante PR-04

### Bug 5: test_e2e.py::test_executor falla porque asume BD runtime disponible

**Descripción:** `tests/test_e2e.py::test_executor` intenta abrir la base de datos de la aplicación (`/instance/niwa-app/data/niwa.sqlite3`) directamente. Ese path no existe en entornos de CI/test. El test fue diseñado para correr contra una instancia viva, no en un entorno aislado. Confirmado preexistente en commit `8130acf` (pre-PR-04).
**Ubicación:** `tests/test_e2e.py:19` — `sqlite3.connect(DB, timeout=10)` donde `DB` apunta a la ruta de producción.
**Severidad:** baja (no afecta funcionalidad, solo la suite de tests en CI).
**PR futuro donde se arreglará:** pendiente de asignar (PR-12 reescribe tests).

## 2026-04-13 — encontrado durante PR-06

### Bug 6: _extract_commands en capability_service no maneja pipes correctamente

**Descripción:** `_extract_commands()` usa `re.split(r'\s*(?:[;&|]{1,2})\s*', command_str)` que trata `|` (pipe) igual que `||` (or). Un comando como `cat file | grep pattern` extraería correctamente `cat` y `grep`, pero `echo "a|b"` dentro de comillas podría generar un split incorrecto. La regex no distingue operadores dentro de strings entrecomillados.
**Ubicación:** `niwa-app/backend/capability_service.py:91`
**Severidad:** baja.
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de capability_service).

### Bug 7: NETWORK_COMMANDS incluye nslookup/dig/ping como comandos de red

**Descripción:** `NETWORK_COMMANDS` incluye `ping`, `nslookup` y `dig` que son herramientas de diagnóstico, no de transferencia de datos. En un contexto de desarrollo, bloquearlos con `network_mode="off"` es demasiado restrictivo — un desarrollador podría querer verificar DNS sin transferir datos.
**Ubicación:** `niwa-app/backend/capability_service.py:47-50`
**Severidad:** baja (política, no bug funcional).
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de capability_service).

### Bug 8: Bloque post-wait de session_id en claude_code.py

**Descripción:** En `ClaudeCodeAdapter._execute()`, el session_id se extrae del stream JSON y se persiste via `runs_service.update_session_handle()`. Si el stream no emite un evento con session_id (error temprano, timeout antes del primer mensaje), `session_handle` queda como `NULL` en la BD. No hay manejo explícito de este caso — un resume posterior fallaría con `--resume None`.
**Ubicación:** `niwa-app/backend/backend_adapters/claude_code.py` (bloque de streaming)
**Severidad:** baja (edge case, requiere fallo muy temprano del proceso Claude).
**Mitigación parcial (PR-08):** `assistant_service._tool_task_resume()` detecta `session_handle IS NULL` en el run previo y devuelve `error="session_handle_missing"` al LLM en lugar de marcar la tarea como pendiente. El LLM informa al usuario en vez de encolar un resume condenado a fallar.
**Bug subyacente sigue abierto:** el adapter debería manejar el caso de forma explícita (e.g., marcar el run como no-resumable, o grabar un session_handle sentinel).
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de claude_code.py).

### Bug 9: Validación de risk_level en approval_service

**Descripción:** `request_approval()` acepta cualquier string en `risk_level` sin validar contra los valores esperados (`low`, `medium`, `high`, `critical`). Un caller podría pasar un valor arbitrario que se persiste en la BD sin error.
**Ubicación:** `niwa-app/backend/approval_service.py:31-56`
**Severidad:** baja (no causa errores funcionales, pero permite datos inconsistentes).
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de approval_service).

## 2026-04-14 — encontrado durante PR-07

### Bug 10: _execute_task_v02 no inyectaba credenciales en el subprocess (pre-existente desde PR-06)

**Descripción:** `_execute_task_v02()` no configuraba `ANTHROPIC_API_KEY`/`CLAUDE_CODE_OAUTH_TOKEN` (para Claude) ni `OPENAI_ACCESS_TOKEN`/`CODEX_HOME` (para Codex) en el entorno del subprocess. El camino legacy (`_run_llm_command`) sí lo hacía. Los adapters hacían `os.environ.copy()` y heredaban lo que tuviera el proceso executor, lo cual funciona para Claude (cuyas credenciales suelen estar en el entorno del shell) pero no para Codex (cuyo token viene de la BD vía OAuth).
**Ubicación:** `bin/task-executor.py:_execute_task_v02()` — faltaba `_prepare_backend_env()`.
**Severidad:** alta para Codex (bloqueante), baja para Claude (funciona por herencia de env).
**PR donde se arregla:** PR-07 — se añade `_prepare_backend_env()` que inyecta credenciales en el profile como `_extra_env`, y los adapters lo mergen en el subprocess env.

## 2026-04-14 — encontrado durante PR-09

### Bug 11: _tool_run_explain lee reason_summary_json pero la columna es reason_summary

**Descripción:** `_tool_run_explain()` en `assistant_service.py` hace `d.get("reason_summary_json")` para leer la razón de la routing decision, pero la columna real en `routing_decisions` se llama `reason_summary` (sin sufijo `_json`). Como `d` es un `dict` construido desde un `sqlite3.Row`, la clave `reason_summary_json` no existe — `d.get()` retorna `None` siempre. El campo `matched_rules_json` en la línea siguiente SÍ es correcto (la columna se llama `matched_rules_json`). Resultado: `_tool_run_explain` siempre devuelve `reason_summary: null` en su output, incluso cuando la routing decision tiene un reason_summary poblado.
**Ubicación:** `niwa-app/backend/assistant_service.py:468` (`d.get("reason_summary_json")` debería ser `d.get("reason_summary")`). Columna real: `niwa-app/db/schema.sql:287` y `niwa-app/db/migrations/007_v02_execution_core.sql:60`.
**Severidad:** media (la tool run_explain pierde información de auditoría en su output; no causa crash pero devuelve datos incompletos).
**PR futuro donde se arreglará:** pendiente de asignar (fix trivial: cambiar `"reason_summary_json"` a `"reason_summary"` en assistant_service.py).

## 2026-04-14 — encontrado durante PR-10a

### Bug 12: test_pr01_schema no incluye contract_version en las columnas esperadas de routing_decisions

**Descripción:** `tests/test_pr01_schema.py::TestTableStructure::test_routing_decisions_columns` compara el conjunto de columnas esperadas contra las reales. PR-09 añadió la columna `contract_version` a `routing_decisions` (migration 011), pero el test no se actualizó. Resultado: el test falla con `extra={'contract_version'}`. Pre-existente a PR-10a — reproducible en la rama limpia en cuanto se aplica la migration 011.
**Ubicación:** `tests/test_pr01_schema.py:493-499` (el set `expected` no incluye `'contract_version'`).
**Severidad:** baja (falso positivo en tests, no afecta funcionalidad).
**Estado:** **ARREGLADO en PR-12.** Se añade `'contract_version'` al set `expected` con comentario explicativo en `tests/test_pr01_schema.py::TestTableStructure::test_routing_decisions_columns`.

### Bug 13: test_assistant_turn_endpoint falla en full-suite por module-state pollution

**Descripción:** `tests/test_assistant_turn_endpoint.py` confía en `os.environ["NIWA_APP_AUTH_REQUIRED"] = "0"` antes de `import app`, pero `NIWA_APP_AUTH_REQUIRED` en `app.py` se evalúa a nivel de módulo al importar. Si otro test (`test_assistant_tool_endpoints.py` u otros) ya importó `app` con auth=1 previamente, `sys.modules["app"]` está cacheado y el env var se ignora. Los 7 tests del archivo pasan cuando se ejecutan aislados pero fallan cuando `pytest tests/` recorre toda la suite. Reproducible en la rama sin cambios de PR-10a.
**Ubicación:** `tests/test_assistant_turn_endpoint.py:62-95` (fixture `server`).
**Severidad:** baja (falso negativo en CI full-suite; los tests son correctos en sí).
**Estado:** **ARREGLADO en PR-12.** La fixture `server` fija `app.NIWA_APP_AUTH_REQUIRED = False` directamente tras el import, replicando el patrón de `tests/test_runs_endpoints.py:79`. Verificado ejecutando `pytest tests/test_assistant_tool_endpoints.py tests/test_assistant_turn_endpoint.py` en ese orden (el orden que dispara la polución) — 26 passed.

### Bug 14: Bundle del frontend supera 1.47MB sin code splitting

**Descripción:** `npm run build` emite un único chunk JS de ~1.47MB (427KB gzipped) en `dist/assets/index-*.js`. Vite emite el warning estándar `(!) Some chunks are larger than 500 kB after minification`. `vite.config.ts` no configura `build.rollupOptions.output.manualChunks` ni usa `React.lazy`/dynamic `import()` para code-splitting por ruta. Todas las rutas (dashboard, tasks, kanban, projects, runs, system, metrics, notes, history, chat) se cargan en el primer bundle.
**Ubicación:** `niwa-app/frontend/vite.config.ts` (sin `manualChunks`), más cualquier consumidor de rutas en `niwa-app/frontend/src/app/Router.tsx` que podría hacer lazy-load.
**Severidad:** baja (tiempo de carga inicial subóptimo; no afecta funcionalidad).
**PR futuro donde se arreglará:** pendiente de asignar (PR de performance de frontend).
**Impacto:** Primera carga más lenta de lo necesario, especialmente en conexiones móviles o VPS con bandwidth limitado. Route-based splitting con `React.lazy` por feature o `manualChunks` agrupando Mantine/dnd-kit/recharts por separado son caminos razonables.

## 2026-04-14 — encontrado durante PR-10c

### Bug 15: ESLint del frontend sin config ejecutable

**Descripción:** `eslint` está instalado como devDependency en `niwa-app/frontend/package.json` (v9.39.4) pero no existe `eslint.config.js` (ni `.eslintrc.*`) en el repo. `npm run lint` falla con:
```
ESLint couldn't find an eslint.config.(js|mjs|cjs) file.
```
El proyecto no tiene linting de frontend en ejecución. Esto probablemente explica inconsistencias sutiles acumuladas en imports y tipos que un lint activo habría detectado temprano.
**Ubicación:** `niwa-app/frontend/` (ausencia de archivo de config).
**Severidad:** baja (no afecta funcionalidad; sí afecta calidad sostenida del código frontend).
**PR futuro donde se arreglará:** candidato al PR de infra de tests de frontend (que añadirá vitest según PR-10a Dec 2). Lint + test infra deberían ir juntos, probablemente antes de PR-12.

## 2026-04-15 — encontrado durante PR-22

### Bug 16: Chat conversacional sólo soporta Anthropic API key — no admite suscripciones CLI ni otros proveedores

**Descripción:** `niwa-app/backend/assistant_service.py` (endpoint `assistant_turn`, el chat web v0.2) está hardcodeado contra `https://api.anthropic.com/v1/messages` con header `x-api-key`. Si el usuario sólo tiene la **suscripción Claude Pro/Max** (configurada vía `claude setup-token`) el chat no funciona — `claude -p` CLI y la API HTTPS son sistemas de auth/billing distintos y el setup_token no vale como API key. Tampoco se soporta OpenAI (suscripción ChatGPT o API key), Gemini, Ollama, ni ningún otro provider de los listados en la UI "Proveedores LLM" (`Sistema → Agentes`). La UI ofrece esas opciones pero el backend del chat las ignora — sólo consulta `svc.llm.anthropic.api_key`. Niwa ya tiene el concepto de "runtime CLI" para ejecución de tareas (backends `claude_code` / `codex` con `runtime_kind=cli` que consumen suscripciones vía CLI autenticado), pero el camino del chat no lo usa.

Impacto práctico: un usuario con suscripción Claude y `claude setup-token` puesto crea tareas, tiene `claude_code` backend verde, configura "llm_anthropic" en la UI con setup_token → cree que está todo listo, abre el Chat, recibe `llm_not_configured` sin contexto de por qué.
**Ubicación:**
- Backend chat: `niwa-app/backend/assistant_service.py::_call_anthropic` (línea ~781) y `_get_llm_config` (línea ~710-760).
- Lookup hardcodeado: sólo `svc.llm.anthropic.api_key` / `int.llm_api_key` / env `ANTHROPIC_API_KEY`.
- Frontend: `niwa-app/frontend/src/features/chat/` asume un solo provider.
- UI "Proveedores LLM" (`SERVICES_REGISTRY` en `niwa-app/backend/app.py`) exhibe OpenAI/Gemini/Ollama como configurables sin señalar que el chat no los usa.
**Severidad:** media (feature gap. Bloquea a usuarios con suscripción-only y a los que prefieren OpenAI/Gemini. No rompe funcionalidad actual, pero contradice la expectativa del usuario construida por la propia UI de proveedores).
**PR futuro donde se arreglará:** pendiente de asignar. Propuesta: PR-NN "LLM runtime unificado para chat conversacional" — añade un router por `svc.llm.<provider>.runtime_kind` (`api` | `cli` | `oauth`) y adapters:
- CLI (`claude -p`, `codex -p`): usa la suscripción vía CLI autenticado. Trade-off: sin function calling estructurado → las tools MCP no son accesibles desde chat. Más lento (arranque de proceso por turno).
- API HTTPS OpenAI: misma estrategia que Anthropic actual, pay-per-use.
- OAuth ChatGPT/Codex: el token del CLI Codex ya se persiste vía el flujo OAuth existente (`niwa-app/backend/oauth.py`) — podría reutilizarse.

Scope estimado: ~200-400 LOC (router + adapters + tests).

### Bug 17: Estado "CONFIGURADO" mentiroso del servicio llm_anthropic cuando sólo hay Setup Token

**Descripción:** `_get_service_status('llm_anthropic')` devolvía `{"status": "configured", "message": "Setup Token configurado ✓"}` cuando el usuario sólo tenía Setup Token (sin API key). La UI renderizaba un badge verde "Configurado". Pero el camino del chat (`assistant_turn`) **no** usa Setup Token — requiere API key — así que el usuario abría el Chat y recibía `llm_not_configured` sin pista de por qué el panel decía verde. "Fail silently" típico: un estado agregado que miente sobre qué superficies están efectivamente cubiertas.
**Ubicación:** `niwa-app/backend/app.py::_get_service_status` caso `service_id == "llm_anthropic"` (líneas ~1949-1960 pre-fix).
**Severidad:** baja (confunde pero no corrompe datos ni rompe nada que ya funcionaba).
**Estado:** **ARREGLADO en PR-22.** El status ahora devuelve `warning` cuando sólo hay Setup Token, con mensaje explícito: "Setup Token OK para tareas (CLI). Falta API key para el chat conversacional." `configured` sólo si la API key está presente. Test matrix en `tests/test_service_status_llm_anthropic.py` cubre las 4 celdas (api_key × setup_token). Relacionado con el gap de Bug 16 — ese gap persiste y justifica el `warning`; cuando Bug 16 se resuelva (runtime CLI para chat), el Setup Token solo podría volver a ser "configured" honestamente.

## 2026-04-15 — encontrado durante PR-23

### Bug 18: Executor systemd crash-loop silencioso desde fresh install — log file creado con ownership root

**Descripción:** Tras un `./niwa install --quick --mode assistant --yes` con `sudo`, el servicio `niwa-<instance>-executor.service` entra en crash-loop inmediato con:

```
PermissionError: [Errno 13] Permission denied: '/home/niwa/.niwa/logs/executor.log'
```

**Cadena causal:**

1. `setup.py::_install_systemd_unit` crea `/opt/<instance>/logs/` vacío vía `shutil.copytree`, hace `chown -R niwa:niwa /opt/<instance>` y `systemctl enable --now`.
2. El unit incluye `StandardOutput=append:/opt/<instance>/logs/executor.log` y `StandardError=append:...`.
3. systemd abre ese fichero para append con su euid (root) ANTES de dropear privilegios a `User=niwa`. Si el fichero no existe, lo crea como `root:root 0644` dentro de un directorio `niwa:niwa`.
4. El executor Python (ya corriendo como niwa) intenta abrir el mismo fichero vía `RotatingFileHandler(LOG_PATH)` en `bin/task-executor.py:185` y falla con `PermissionError`.
5. `Restart=always`, `RestartSec=10` → restart loop eterno.

Verificado en producción (VPS real) tras el install del 2026-04-15: el executor llevaba 830+ restarts acumulados desde el install original. Nadie se enteró porque:

- `systemctl is-active` reporta "activating" brevemente entre reinicios.
- El install de `setup.py` imprime "✓ Enabled and started niwa-niwa-executor.service" ANTES del primer restart failure — no hay verificación post-install de que el servicio esté efectivamente estable.
- La UI de Niwa no muestra el estado del executor en ningún panel visible.

**Impacto:** El executor, componente crítico que ejecuta tareas vía `claude -p`, está **totalmente caído desde la instalación** en cualquier fresh install con `sudo` (que es el camino principal). Ningún task se procesa hasta que el usuario chowne manualmente el fichero. Fail-silent clase A.

**Ubicación:** `setup.py::_install_systemd_unit` (rama `run_as_root`, líneas ~1824-1900 pre-fix). El unit template contiene `StandardOutput=append:{log_path}` pero no se pre-crea el fichero con ownership correcto antes de `systemctl enable`.

**Severidad:** **alta** (bloqueante; el executor no funciona en ningún fresh install).

**Estado:** **ARREGLADO en PR-23.** `setup.py` ahora hace `(shared_dir / "logs" / "executor.log").touch(exist_ok=True)` antes del `chown -R niwa:niwa shared_dir`, de modo que el fichero existe con ownership correcto (niwa:niwa) cuando systemd lo abre para append — systemd reutiliza el fd en vez de crearlo como root. Test en `tests/test_installer_executor_log.py` incluye regresión estática (el touch debe aparecer antes del chown en source order) + simulación de la cadena de permisos. Verificado en VPS real: `chown niwa:niwa /opt/<instance>/logs/{executor,hosting}.log` unblockea el crash-loop ya instalado; para instalaciones futuras el fix preventivo de setup.py resuelve el bug desde el origen.

**Follow-ups documentados para PRs posteriores:**

- **Sub-bug 18a (severidad media):** `niwa-<instance>-hosting.service` tiene el mismo patrón (`StandardOutput=append:/opt/<instance>/logs/hosting.log` + `User=niwa`) pero no crashea porque `bin/hosting-server.py` no hace Python-level `open()` del fichero — usa `print()` y hereda el fd de systemd. Bug latente: cualquier futuro intento de logging Python-level en hosting reproducirá Bug 18.

  **Estado:** **ARREGLADO (defense-in-depth) en PR-26.** `install_hosting_server` ahora hace `hosting_log.touch(exist_ok=True)` + `chown niwa:niwa hosting_log` antes del `systemctl enable --now`, replicando el patrón que PR-23 aplicó al executor. Cualquier logger Python-level que se añada en el futuro a `hosting-server.py` encontrará el fichero ya creado con ownership correcto y no reproducirá Bug 18. Test en `tests/test_installer_hosting_path.py::TestHostingLogPreCreated` cubre el touch, el chown y el orden relativo. Además, PR-25 ya cubre la detección: si el crash-loop volviera a ocurrir (por cualquier causa), el health check de los 15s post-enable abortaría el install loudly.
- **Sub-bug 18b (severidad media):** `setup.py` reporta "✓ Enabled and started" tras `systemctl enable --now` sin verificar que el servicio esté _stable_ (i.e. no en restart loop). Propuesta: esperar 15s y confirmar que `systemctl is-active == active` y el contador de restarts no está creciendo. Si no, abortar el install con mensaje claro. Esto matches el principio "fail loud" del proyecto.

  **Estado:** **ARREGLADO en PR-25.** `setup.py` incorpora tres helpers puros stdlib (`_wait_for_service_stable`, `_verify_service_or_abort`, `_reset_failed_unit`). Tras cada `systemctl enable --now` satisfactorio (executor y hosting, tanto system-scope root como user-scope non-root), el installer espera 15s y comprueba que `systemctl is-active == "active"` y `NRestarts == 0`. Si no cumple, `sys.exit(1)` con dump del journal (últimas 20 líneas), referencias a Bug 18/19 y el comando `chown niwa:niwa /opt/<instance>/logs/{executor,hosting}.log` para desbloquear manualmente una instalación ya rota. Antes de cada `enable --now` se llama `systemctl reset-failed` (best-effort) para que un reinstall sobre una unidad previamente crasheada no intoxique el contador `NRestarts` y dispare un falso positivo. Tests en `tests/test_installer_service_health.py` (18 casos) cubren todos los caminos con `sleep` y `runner` inyectados para coste cero en CI. Efecto de borde útil: el check aplica también al hosting, cerrando de paso el patrón latente de Bug 18a (el hosting hoy no crashea porque no hace Python-level `open()` de su log, pero cualquier regresión futura quedaría detectada inmediatamente por el mismo helper).

## 2026-04-15 — encontrado durante PR-24

### Bug 19: El executor pasa el path del prompt como argumento posicional — toda tarea devuelve "I need permission to read that file"

**Descripción:** `bin/task-executor.py::_run_llm` invocaba `claude -p` así:

```python
prompt_file = tempfile.NamedTemporaryFile(
    mode="w", suffix=".md", prefix="niwa-prompt-", delete=False,
)
prompt_file.write(prompt)
prompt_file.close()
cmd = shlex.split(command) + [prompt_file.name]
```

El intento era evitar `ENAMETOOLONG` al pasar prompts largos por argv. Pero `claude -p <path>` **no** interpreta ese positional como referencia a un fichero — lo trata como **texto del prompt**. El modelo entonces ve "por favor procesa esta ruta", invoca su tool `Read` con el path, la permission check falla (o no está pre-aprobada) y toda la respuesta del LLM es:

```
I need permission to read that file.
```

**Impacto:** **crítico**. Desde la versión que introdujo esta aproximación de tempfile, **todas las tareas ejecutadas por el executor Niwa devolvieron basura**. El executor marca las tareas como `hecha` (exit code 0 del proceso) pero el output es inútil. El pipeline entero (UI → DB → executor → claude) está roto en el último metro.

Verificado empíricamente en VPS:

| Invocación                              | Output                                  |
|-----------------------------------------|-----------------------------------------|
| `claude -p /tmp/niwa-prompt-test.md`    | "I need permission to read that file."  |
| `cat /tmp/niwa-prompt-test.md \| claude -p` | "SMOKE-OK 2026-04-15" (correcto)        |

**Ubicación:** `bin/task-executor.py::_run_llm` (líneas ~658-666 pre-fix: `tempfile.NamedTemporaryFile` + `cmd = shlex.split(command) + [prompt_file.name]`).
**Severidad:** **crítica** (bloqueante; ninguna tarea se ejecuta correctamente).
**Estado:** **ARREGLADO en PR-24.** El prompt se pasa vía stdin con `stdin=subprocess.PIPE` en el `Popen`, se escribe el prompt al fd de stdin y se cierra para enviar EOF. stdout/stderr siguen usando PTY (claude-code escribe progreso a `/dev/tty`, un pipe plano lo perdería). Se elimina la creación/cleanup del tempfile. Tests en `tests/test_task_executor_stdin.py` (5 casos): verifican que argv no contiene paths de tmp, `stdin=subprocess.PIPE`, prompt escrito al stdin del child, `close()` llamado para señalar EOF. Control negativo verificado durante desarrollo.

### Bug 20: v0.2 routing pipeline silenciosamente caía a tier-3 legacy — `_BACKEND_DIR` se computaba relativo al `__file__` y no existía tras el install

**Descripción:** Cuando el setting `routing_mode=v02` está activo (default en instalaciones con `--mode assistant`), el executor intenta despachar la tarea por el "v0.2 routing pipeline":

```
10:11:02 [INFO]  task 82bf3c4f: using v0.2 routing pipeline
10:11:02 [ERROR] v0.2 modules not available — cannot execute in v02 mode
                 ModuleNotFoundError: No module named 'routing_service'
```

**Causa raíz** (corregida tras el reconocimiento de PR-27 — la descripción inicial de este bug era incorrecta): el `sys.path.insert` SÍ existía en `bin/task-executor.py:45-47`, pero la ruta que insertaba se computaba relativa al `__file__`:

```python
_BACKEND_DIR = Path(__file__).resolve().parent.parent / "niwa-app" / "backend"
```

`setup.py::_install_systemd_unit` copia el executor a `/home/niwa/.<instance>/bin/task-executor.py`, así que en producción `_BACKEND_DIR` resolvía a `/home/niwa/.<instance>/niwa-app/backend/` — **un directorio que el installer nunca creó** (sólo copia `secrets/`, `bin/task-executor.py` y enlaces a `data/`, `logs/`). El `sys.path.insert(path_inexistente)` es un no-op silencioso; el `import routing_service` posterior fallaba con `ModuleNotFoundError`; el executor caía a "tier-3 legacy" (camino con `claude -p` directo) que sí funciona.

**Consecuencia estratégica:** la ruta v0.2 (`routing_decisions`, `backend_runs`, state machine nueva, capability profiles, approval gate, fallback chain auditable) **nunca había corrido en ningún install real**. Toda la funcionalidad v0.2 estaba silenciosamente en standby; las tareas seguían ejecutándose por el camino legacy de v0.1.

**Mitigación temporal (pre-PR-27):** el fallback automático funcionaba — las tareas se ejecutaban por legacy. El único síntoma visible era **~5s de latencia extra** por tarea + ruido de logs + trazas `ERROR` engañosas. Por eso pasó desapercibido.

**Ubicación:** `bin/task-executor.py:45-47` (resolución relativa al `__file__`) + `setup.py::_install_systemd_unit` (no copiaba el árbol de backend a un sitio niwa-readable).

**Severidad:** **alta estratégica** (no bloquea install ni ejecución básica, pero invalida toda la verificación de PRs 01-12 en producción).

**Estado:** **ARREGLADO en PR-27.** Dos cambios:

1. **Installer (`setup.py::_install_systemd_unit`):** copia el árbol `niwa-app/backend/` a una ubicación niwa-readable mediante `shutil.copytree` (filtrando `__pycache__`). En rama root: `/opt/<instance>/niwa-app/backend/`. En rama user-scope: `cfg.niwa_home/niwa-app/backend/`. Idempotente en reinstall (rmtree antes de copiar). Inyecta `Environment="NIWA_BACKEND_DIR={path}"` en ambos templates de unit (root + user).
2. **Executor (`bin/task-executor.py:45-67`):** prefiere `os.environ["NIWA_BACKEND_DIR"]` sobre el fallback relativo. Si `_BACKEND_DIR` no existe, **fail loud**: `print(FATAL...)` a stderr y `sys.exit(2)`. La fail-loud combina con PR-25: el systemd `Restart=always` reintenta, el counter `NRestarts > 0` tras 15s dispara el aborto del install con journal tail visible.

Tests:
- `tests/test_task_executor_backend_dir.py` (4 casos): env var precedence, fail-loud con exit 2 si dir falta, mensaje incluye guía dev + install, fallback relativo sigue funcionando para repo-checkout.
- `tests/test_installer_backend_tree.py` (8 casos): repo backend tree existe, copytree con `ignore_patterns("__pycache__")`, idempotencia (rmtree o `dirs_exist_ok`), ambos unit templates exportan `NIWA_BACKEND_DIR`, executor prefiere env var sobre relativo (orden léxico).

**Trade-off documentado:** ahora hay **tres copias** del árbol `niwa-app/backend/` (repo source, container Docker build, host runtime install). El SPEC §8 prohíbe duplicación gratuita pero acepta replicación operacional necesaria — ver `docs/DECISIONS-LOG.md` PR-27 Decisión 1 para la justificación. La alternativa (mover los módulos a `niwa-app/common/` importable desde ambos entornos) es un refactor mayor fuera del scope quirúrgico de PR-27.

**Riesgos pendientes (follow-ups esperados tras merge):** una vez fixeado, la ruta v0.2 ejecutará por primera vez en producción. Plausible que aflore:
- Faltan `backend_profiles` seed en install quick → routing_service sin profile activo.
- `routing_decisions.contract_version` (PR-10a) recibe valores reales por primera vez.
- State machine de `backend_runs` ejercita transiciones nunca antes ejecutadas en prod.
- Path/permission de `artifact_root` puede no existir o no ser writable.

Estos NO son regresiones de PR-27 — son estado preexistente que el bug 20 ocultaba. Documentar como bugs nuevos cuando aparezcan, atacar uno a uno.

## 2026-04-15 — encontrado durante la verificación de PR-25 en el VPS

### Bug 21: hosting-server.service apunta a /root/ y crashea con Permission denied bajo User=niwa

**Descripción:** En un fresh install `./niwa install --quick --mode assistant --yes` con `sudo`, el servicio `niwa-<instance>-hosting.service` entra en crash-loop inmediato con:

```
/usr/bin/python3: can't open file '/root/.niwa/bin/hosting-server.py': [Errno 13] Permission denied
```

**Cadena causal:**

1. `install_hosting_server` copia `bin/hosting-server.py` a `cfg.niwa_home / "bin" / "hosting-server.py"`. Cuando el installer corre con `sudo`, `cfg.niwa_home = /root/.<instance>` (HOME del invoker root).
2. `/root/` tiene permisos `drwx------ (0700)` por política estándar de distro — sólo `root` puede recorrerlo.
3. El systemd unit que se escribe contiene `ExecStart=/usr/bin/env python3 {dest}` donde `dest` apunta a la copia bajo `/root/...`, pero `User=niwa`.
4. systemd hace `setuid(niwa)` antes de lanzar `python3`. El python no puede `stat()` el path porque el directorio padre es inaccesible para el uid del proceso → exit code 2.
5. `Restart=always`, `RestartSec=10` → crash-loop eterno.

Paralelismo con Bug 18: el executor YA sufrió un bug estructuralmente análogo (directorio root-only bloquea a niwa) y lo resolvió en `_install_systemd_unit` copiando el binary a `/home/niwa/.<instance>/bin/task-executor.py`. `install_hosting_server` nunca replicó ese patrón — es un Chesterton's fence al revés.

**Detección:** gracias a PR-25, el install abortó loudly con journal tail en vez de quedarse en crash-loop silencioso. Sin PR-25 este bug habría pasado desapercibido igual que Bug 18 durante horas.

**Ubicación:** `setup.py::install_hosting_server`, rama `run_as_root` (líneas ~2198-2227 pre-fix). El template del unit usa `{dest}` = `cfg.niwa_home / "bin" / "hosting-server.py"` sin el path swap a `/home/niwa/`.

**Severidad:** **alta** (bloqueante; el hosting server no arranca en ningún fresh install con `sudo`).

**Estado:** **ARREGLADO en PR-26.** `install_hosting_server` ahora, en la rama root:

1. Calcula `niwa_home = /home/niwa/.<instance>`.
2. Copia el binary a `niwa_home/bin/hosting-server.py`, hace `chmod 0755` y `chown niwa:niwa`.
3. Reasigna `dest = niwa_hosting_dest` antes de construir el template del unit, así `ExecStart=... {dest}` baked-in apunta al path niwa-readable.
4. Pre-crea `hosting.log` con `touch(exist_ok=True)` + `chown niwa:niwa` (defense-in-depth contra sub-bug 18a).
5. `chown -R niwa:niwa` sobre `hosting_projects_dir` para que el servidor pueda escribir bundles de proyectos.

Test en `tests/test_installer_hosting_path.py` (7 casos): regex estático sobre `setup.py` que pin-ean el copy, el chown, el `dest = niwa_hosting_dest` antes del template, la ausencia de `/root/` en el unit body, el touch+chown del log, y la persistencia del `_verify_service_or_abort` de PR-25.

### Bug 22: _quick_free_port no trackea asignaciones intra-sesión → gateway y caddy pueden pelearse por el mismo puerto

**Descripción:** Durante un install con el puerto default de gateway (`18810`) ocupado, `_quick_free_port` encuentra `18811` como siguiente libre y lo asigna al gateway. Cuando la misma sesión pide puerto para caddy, `_quick_free_port` vuelve a consultar el SO y — como el gateway aún no ha hecho bind — también devuelve `18811`. Ambos servicios intentan usar el mismo puerto y uno de los dos falla al arrancar.

**Repro observada en VPS:** dos intentos consecutivos de `./niwa install --quick --mode assistant --yes` en un VPS con un install previo colgado. Workaround: limpiar containers (`docker rm -f $(docker ps -aq)`) antes de reinstalar.

**Ubicación:** dos paths del wizard, ambos con la misma vulnerabilidad estructural:
- `setup.py::_quick_free_port` (helper usado por el path `--quick`).
- `setup.py::step_ports` (path interactivo legacy, tiene su propia copia inline del auto-bump loop sin reutilizar `_quick_free_port`).

**Severidad:** media (no corrupt data, no bloquea fresh installs sin ocupación previa; sí rompe reinstalls o installs en hosts compartidos). Encontrado por Claude-VPS durante la verificación de PR-25; segundo path (`step_ports`) detectado durante la review independiente de PR-28.

**Estado:** **ARREGLADO en PR-28** (en ambos paths del wizard).

1. **`--quick` (no-interactivo):** `_quick_free_port` ahora acepta `reserved: Optional[set]`. `build_quick_config` inicializa un `_reserved_ports = set()` local y le añade cada puerto asignado tras cada llamada. La función skipea cualquier port en `reserved` antes de consultar `detect_port_free`, evitando que dos servicios cuyos defaults sean consecutivos (gateway 18810 / caddy 18811) acaben en el mismo offset cuando el primero está ocupado a nivel SO. Default `reserved=None` preserva backwards-compat.

2. **`step_ports` (interactivo, legacy):** mismo patrón aplicado en su auto-bump loop inline. `_reserved_ports = set()` local al inicio del step. En el auto-bump, candidates ya reservados se saltan (`continue`). Tras `setattr(cfg, attr, n)`, `_reserved_ports.add(n)`. Además, el path interactivo añade un check sobre el input del usuario: si el usuario teclea manualmente un port ya asignado a otro servicio en este install, se rechaza con mensaje explícito (cierra el agujero adicional de "el usuario se equivoca y el wizard lo acepta").

Tests: `tests/test_installer_port_reservation.py` (14 casos):
- 8 unit del helper con `monkeypatch` sobre `detect_port_free` (cero sockets reales).
- 1 repro literal del escenario VPS (4 ports con 18810 ocupado → todos distintos, gateway != caddy).
- 1 guard estático sobre `build_quick_config` (cada `_quick_free_port` pasa el set reservado).
- 4 guard estáticos sobre `step_ports` (init del set, skip en auto-bump, add tras assign, rechazo de input colisivo).


## 2026-04-15 — encontrado durante audit pre-mortem v0.2 (post PR-27, pre primera ejecución en VPS)

Tras PR-27 desbloquear la ejecución real de la ruta v0.2 en producción, lancé un audit pre-mortem (Explore agent) sobre `routing_service`, `runs_service`, `backend_adapters/*`, `state_machines`, `capability_service`. Reportó 9 bugs candidatos. Verifiqué cada uno leyendo el código directamente. **De los 9, sólo 3 resistieron la verificación** — los demás eran especulación sin evidencia o false positives (p.ej., el agente preocupó por `seed_backend_profiles` no insertar nada, pero `_SEED_PROFILES` en `backend_registry.py:75-90` sí incluye `claude_code` con `enabled=1, priority=10`; el flow funciona).

Los 3 verificados:

### Bug 23: `_execute_task_v02` viola la state machine — UPDATE de `en_progreso` a `pendiente` cuando approval_required

**Descripción:** `_claim_next_task()` en `bin/task-executor.py:264` transiciona la tarea atómicamente de `pendiente` a `en_progreso` antes de invocar `_execute_task_v02()`. Dentro de `_execute_task_v02()`, si el routing decide que se requiere approval (línea 1058-1062), el código hace:

```python
c.execute(
    "UPDATE tasks SET status = 'pendiente', updated_at = ? "
    "WHERE id = ?",
    (_now_iso(), task_id),
)
```

Esto es una transición `en_progreso → pendiente`. Pero según `niwa-app/backend/state_machines.py:26` (y la copia en `bin/task-executor.py:90-99`):

```python
'en_progreso': frozenset({'waiting_input', 'revision', 'bloqueada', 'hecha', 'archivada'}),
```

`pendiente` NO está permitido como destino desde `en_progreso`. La state machine canónica indicaría `waiting_input` para "necesita acción humana antes de proceder".

El UPDATE es directo en SQL — no pasa por `_assert_task_transition()` (que sólo se llama en el path legacy, línea 666, no en v0.2). Es una violación silenciosa: la BD lo acepta, la UI ve la tarea de vuelta en `pendiente`, el siguiente poll del executor la reclama de nuevo, vuelve a fallar el check de approval, vuelve a la pendiente — bucle.

**Ubicación:** `bin/task-executor.py:1058-1062` (UPDATE directo). State machine canónica en `niwa-app/backend/state_machines.py:24-34` y `bin/task-executor.py:90-99`.

**Severidad:** **alta** — provoca bucle de procesamiento si una tarea queda con approval pendiente sin que el operador apruebe rápido. La tarea no progresa pero el executor la machaca.

**Detectado por:** Explore agent (audit pre-mortem); verificado leyendo código directamente.

**Estado:** **ARREGLADO en PR-29.** Fix en dos sitios estructurales (review independiente detectó que el diseño inicial con la transición en el HTTP handler era incompleto — la ruta del assistant/MCP bypasseaba el handler):

1. **`bin/task-executor.py::_execute_task_v02`**: en lugar de UPDATEar a `pendiente`, transiciona la tarea a `waiting_input` (el estado canónico per SPEC §2 para "necesita acción humana antes de proceder"). Validado con `_assert_task_transition('en_progreso', 'waiting_input')` antes del UPDATE.

2. **`niwa-app/backend/approval_service.resolve_approval`**: la transición inversa `waiting_input → pendiente` vive **dentro** del service, no en el handler HTTP. Tras la UPDATE de `approvals`, si `status == "approved"` y la tarea asociada sigue en `waiting_input`, el service la UPDATE a `pendiente` validando con `state_machines.assert_task_transition`. Diseño elegido para que **toda ruta que resuelva un approval** reciba el fix:
   - `POST /api/approvals/:id/resolve` (handler directo UI).
   - `POST /api/assistant/tools/approval_respond` (handler assistant).
   - `assistant_service.tool_approval_respond` (llamada directa desde MCP proxy).
   - Cualquier test/integración futuro que llame `resolve_approval` directo.

   `Reject` deliberadamente NO dispara la transición — el operador puede archivar, retomar manualmente o redirigir a otro backend.

**Limitación conocida (documentada en DECISIONS-LOG.md PR-29 Decisión 4):** `waiting_input` puede ser set por otros flows (p.ej. `task_request_input` MCP tool). Si una tarea está en `waiting_input` por un `task_request_input` pendiente Y tiene un approval pending, aprobar el approval flippea la tarea a `pendiente` aunque la pregunta del `task_request_input` siga sin respuesta. Race estrecha (requiere ambas causas simultáneas); accepted trade-off por la simplicidad del gating. Fix más riguroso (registrar en el approval la causa concurrente, o contar reasons) queda como follow-up si el race se observa en producción.

Tests:
- `tests/test_task_executor_approval_state.py` (6 casos): invariantes estáticos + compliance state machine + end-to-end con routing mockeado.
- `tests/test_approvals_resolve_transitions_task.py` (9 casos):
  - approve sobre `waiting_input` → `pendiente`.
  - approve sobre otros estados (archivada/pendiente/en_progreso) → no fuerza.
  - reject → no toca.
  - idempotencia: segundo approve es no-op.
  - `tool_approval_respond` (ruta assistant/MCP) también dispara la transición.
  - `tool_approval_respond` reject deja la tarea intacta.
  - state machine compliance (`waiting_input → pendiente` permitido, import de `assert_task_transition` presente).
  - app.py handler NO duplica la lógica (pin contra regresión a la arquitectura anterior).

112/112 tests approval+executor pasan.

### Bug 24: `artifact_root.mkdir()` puede lanzar `OSError`/`PermissionError` no capturado en `ClaudeCodeAdapter.start()`

**Descripción:** `niwa-app/backend/backend_adapters/claude_code.py:144-146`:

```python
artifact_root = run.get("artifact_root")
if artifact_root:
    Path(artifact_root).mkdir(parents=True, exist_ok=True)
```

Si `artifact_root` apunta a un path sin permisos para el user `niwa` (p.ej., dentro de un proyecto con ownership distinto), `mkdir` lanza `PermissionError`. El except más cercano está en `bin/task-executor.py:_execute_task_v02()` línea ~1210, que captura `Exception as e` genérico. Pero entre el `mkdir()` y el `except`, el `backend_run` ya se creó en estado `starting`. La excepción rompe antes del `runs_service.transition_run(..., "running", ...)` que habría dejado el run en estado terminal correcto. El run queda en `starting` indefinidamente hasta que un operador haga cleanup manual.

**Ubicación:** `niwa-app/backend/backend_adapters/claude_code.py:144-146`.

**Severidad:** **media** — sólo dispara si los permisos del filesystem están raros (project_dir owned por otro user). En un install normal con un solo proyecto creado vía UI, no debería pasar. Pero los runs zombie en `starting` ensucian la DB y confunden al operador.

**Detectado por:** Explore agent (audit pre-mortem).

**PR futuro donde se arreglará:** pendiente de asignar. Fix candidato: envolver `mkdir` en try/except específico, transicionar el run a `failed` con `error_code='artifact_root_mkdir_failed'` antes de re-lanzar.

### Bug 25: Codex tmpdir (`CODEX_HOME`) leak si `adapter.start()` falla en v0.2 path

**Descripción:** `bin/task-executor.py::_prepare_backend_env()` línea ~986, para profiles con `slug='codex'`:

```python
codex_home = _tmpfile.mkdtemp(prefix="niwa-codex-v02-")
extra_env["CODEX_HOME"] = codex_home
```

El path queda únicamente en el dict `extra_env` que se pasa al adapter. El path legacy (`_run_llm()` línea 807-813) sí limpia `codex_home` en su finally. La rama v0.2 no lo hace — si `adapter.start()` lanza después de `mkdtemp`, el directorio queda huérfano en `/tmp/niwa-codex-v02-*`.

**Ubicación:** `bin/task-executor.py::_prepare_backend_env` (mkdtemp) y `_execute_task_v02` (no cleanup en finally).

**Severidad:** **baja** — sólo afecta a installs que usan `codex` como backend (no `claude_code`, que es el default). Acumulación lenta pero real bajo tasks repetidas con codex.

**Detectado por:** Explore agent (audit pre-mortem).

**PR futuro donde se arreglará:** pendiente de asignar. Fix candidato: guardar `codex_home` en una variable de scope `_execute_task_v02` y limpiarlo en un finally al final de la función. Alternativa más limpia: pasar un cleanup callback al adapter.

---

**Bugs candidatos del audit que NO documenté tras verificación:**

- **"Seed de routing rules vacío sin fallback"** — falso positivo. `seed_backend_profiles` (`backend_registry.py:113`) inserta `claude_code` con `enabled=1` en `init_db()` (`app.py:272-273`). El default fallback de `routing_service.decide()` (línea 391-405) sí encuentra el profile.
- **"DB connection thread safety"** — especulación sin evidencia concreta de race observada. Si el audit tiene razón, lo veremos en producción y entonces sí lo documentamos.
- **"capability_service silent fallback"** — UX concern, no bug funcional.
- **"Heartbeat thread daemon=True"** — comportamiento intencional, no bug.
- **"UTF-8 encoding edge case"** — especulación.
- **"State machine `queued → failed` unused"** — observación de diseño, no bug funcional.

## 2026-04-16 — encontrado durante review externa (GPT 5.4 Pro sobre v0.2, verificado contra código)

La humana compartió una lectura de un modelo externo (GPT 5.4 Pro, modo investigador) sobre v0.2. Verificamos cada claim contra el código real. De los 8 hallazgos, 2 eran accionables quirúrgicamente (arreglados en PR-30), 3 son bugs reales pero fuera de scope (documentados abajo), y 3 eran observaciones pre-existentes ya conocidas o by-design.

### Bug 26: `run_niwa_update()` hacía `git pull origin main` hardcodeado — mezcla código de otra rama

**Descripción:** `niwa-app/backend/app.py::run_niwa_update()` contenía `["git", "pull", "origin", "main"]` hardcodeado (línea ~2369 pre-fix). En installs corriendo la rama `v0.2`, el botón "Actualizar" de la UI tiraba de `main` encima de `v0.2`, mezclando código de release lines distintas. Bug claro de release management.

**Ubicación:** `niwa-app/backend/app.py:2369` (pre-fix).
**Severidad:** **alta** (corrompe silenciosamente la release).
**Estado:** **ARREGLADO en PR-30.** Ahora detecta la rama actual con `git rev-parse --abbrev-ref HEAD` antes del pull. Fallback a `main` si git falla. Test estático en `tests/test_update_and_migrations.py` pinea que no haya hardcode de `"main"` y que se use `current_branch` variable.

### Bug 27: `_run_migrations()` no abortaba en fallo — servicio arrancaba con schema parcialmente migrado

**Descripción:** `niwa-app/backend/app.py::_run_migrations()` (líneas 847-849 pre-fix) capturaba excepciones de migraciones con `logger.error` + `break`. El servicio seguía arrancando sobre un schema que no coincidía con lo que el código esperaba → errores runtime sutiles horas después, casi imposibles de diagnosticar.

**Ubicación:** `niwa-app/backend/app.py:847-849` (pre-fix).
**Severidad:** **alta** (misma clase de "fail silent" que PR-25 cerró para systemd).
**Estado:** **ARREGLADO en PR-30.** Ahora `raise SystemExit(f"FATAL: migration {filename} failed: {e}. ...")`. El servicio para con mensaje claro. Test estático en `tests/test_update_and_migrations.py` pinea que la excepción del except block sea `SystemExit` y no un bare `break`.

### Bug 28: OAuth tokens persisted en SQLite en claro + endpoint `/api/auth/oauth/import` los acepta por HTTP

**Descripción:** `_save_oauth_tokens` (`app.py:1857`) persiste `access_token`, `refresh_token`, `id_token` directamente en SQLite sin cifrar. El endpoint `POST /api/auth/oauth/import` (`app.py:3844`) acepta un JSON con tokens y los guarda. Cualquiera con acceso al fichero de la DB (backup mal protegido, compromiso del host) se lleva credenciales reutilizables.

**Ubicación:** `app.py:1857` (`_save_oauth_tokens`) y `app.py:3844` (endpoint import).
**Severidad:** **media-alta** (scope: Niwa es single-user single-host, la DB tiene ownership `niwa:niwa` en `/opt/<instance>/data/`, y el endpoint está detrás de auth. El riesgo real es backup sin cifrar copiado a un lugar público, o acceso root comprometido donde el atacante ya tiene acceso a todo).
**PR futuro donde se arreglará:** pendiente de asignar. Scope estimado: ~200+ LOC (cifrado at-rest con key derivada de password o KDF + columna cifrada + decrypt on read). Requiere decisión de producto sobre key management.

### Bug 29: Cookie de sesión sin flag `Secure` — expuesta en tránsito si no hay TLS externo

**Descripción:** `app.py:3833` setea la cookie de sesión con `HttpOnly; SameSite=Lax` pero sin `Secure`. Si el operador expone Niwa sin TLS externo (p.ej., sin cloudflared o reverse proxy), la cookie viaja en claro y puede ser capturada por MITM. El Caddyfile tiene `auto_https off` (caddy es reverse proxy interno, no TLS terminator).

**Ubicación:** `app.py:3833` (Set-Cookie header).
**Severidad:** **media** (el modelo operacional de Niwa asume TLS del reverse proxy externo, pero no valida que esté configurado; un operador que se equivoque queda expuesto sin warning).
**PR futuro donde se arreglará:** pendiente de asignar. Fix candidato: añadir `Secure` condicionalmente cuando `cfg.public_domain` está set (indica acceso externo, implica que debería haber TLS). ~5 LOC.

### Bug 30: CI (`mcp-smoke.yml`) no prueba la integración MCP end-to-end

**Descripción:** `mcp-smoke.yml` declara explícitamente que no levanta el MCP gateway completo y usa un compose mínimo "app only". La integración más peligrosa (MCP gateway → app → executor → LLM) no tiene CI real.

**Ubicación:** `.github/workflows/mcp-smoke.yml`.
**Severidad:** **media** (no causa bugs pero tampoco los detecta — cualquier regresión en el flow MCP end-to-end pasa desapercibida hasta el VPS).
**PR futuro donde se arreglará:** pendiente de asignar. Scope: compose con gateway+app mínimos, seed de task, smoke vía MCP tool call, timeout 60s.

---

**Hallazgos de la review externa que NO documenté como bugs nuevos:**

- **Terminal privileged** — pre-existente, ya mitigado: está en `docker-compose.advanced.yml` (no en el base), fuera del `--quick` install. Test `test_approval_gate_integration.py:10-11` pinea que el compose principal NO tiene privileged.
- **Fragilidad estructural (scheduler INSERT, globals en tasks_helpers, NIWA_VERSION=0.1.0)** — deuda técnica pre-existente, no bugs funcionales. Documentada en la section de limpieza v0.3.
- **Hosting module smells (paths, http://, pkill)** — pre-existente, no bloquea. Limpieza v0.3.

## 2026-04-16 — encontrados durante verificación del happy path en VPS (post PRs 25-36)

### Bug 31: Resultado de Claude no se renderiza como markdown en la UI

**Descripción:** PR-36 añadió la sección "Resultado" en el detalle de tarea, pero el texto se muestra como pre-formateado (`whiteSpace: pre-wrap`). Claude genera markdown (tablas, negritas, headers, bloques de código) que debería renderizarse como HTML para ser legible. Actualmente `**bold**` se muestra literal.

**Ubicación:** `niwa-app/frontend/src/features/tasks/components/TaskDetailsTab.tsx` — la sección Resultado usa `<Text>` plano.
**Severidad:** **media** (UX: el resultado es legible pero feo; las tablas y formato se pierden).
**Estado:** **ARREGLADO en PR-37.** La sección Resultado ahora renderiza el `executor_output` vía `<ReactMarkdown remarkPlugins={[remarkGfm]}>` con override de `<a>` para abrir links externos en pestaña nueva (`rel=noopener noreferrer`). Sin nuevas deps: `react-markdown@9.1.0` y `remark-gfm@4.0.1` ya estaban en `package.json` (NoteEditor las usa desde antes). Se eliminó el wrapper `<Text>` para evitar HTML inválido (`<p>` dentro de `<p>`). Tests en `niwa-app/frontend/src/features/tasks/components/TaskDetailsTab.test.tsx` (5 casos): bold → `<strong>`, tablas GFM → `<table>`, links externos `target=_blank`, no render si vacío, HTML raw (`<script>`) queda escapado (react-markdown 9.x sin rehype-raw = no vector XSS).

### Bug 32: Tareas que Claude "completa" con exit 0 pero sin haber hecho nada (false-succeeded genérico)

**Descripción:** PR-33/34 detectan `permission_denials` del stream-json y marcan el run como `failed`. Pero si Claude sale con exit 0 sin permission denials pero su output dice "no pude hacerlo" (p.ej., por rate limit, por no entender la tarea, por error de otro tipo), el run se marca `succeeded` y la tarea como `hecha` — falso positivo. El usuario ve "completada" sin trabajo real.

**Ubicación:** `niwa-app/backend/backend_adapters/claude_code.py:826-870` — la lógica de outcome solo chequea exit code + permission_denials + is_error.
**Severidad:** **media** (no siempre dispara, pero cuando lo hace es confuso para el usuario).
**PR futuro donde se arreglará:** pendiente de asignar. Opciones: (a) heurística sobre el result text (buscar patrones "no pude", "error", etc. — frágil). (b) Chequear que al menos una tool_use con Write/Edit/Bash fue exitosa (más robusto). (c) Dejar que el usuario rechace la tarea manualmente y documente el caso — lo menos invasivo.

### Feature 1: Auto-registro de proyectos post-tarea

**Descripción:** Cuando Claude crea ficheros (p.ej., un index.html para un proyecto web), los ficheros existen en el filesystem pero NO aparecen en la sección "Proyectos" de la UI. Niwa no sabe que es un "proyecto" porque Claude no tiene acceso a los MCP tools de Niwa para registrarlo.

**Ubicación:** gap entre `bin/task-executor.py` (ejecuta Claude) y `niwa-app/backend/app.py` (gestiona proyectos).
**Severidad:** **alta UX** (el usuario espera ver su proyecto creado; dice "hecha" pero no hay proyecto visible).
**Estado:** **ARREGLADO en PR-38** (híbrido de las opciones (b) + (c) del menú original).

Dos capas complementarias:

1. **Pre-hook (`_auto_project_prepare`)** en `bin/task-executor.py`: cuando la tarea no tiene `project_id`, el executor genera `<slug>-<uuid6>`, hace `mkdir -p <NIWA_HOME>/data/projects/<slug>-<uuid6>/`, e inyecta el path en `task_dict["project_directory"]`. El adapter Claude Code ya lo lee como `cwd`. `_sanitize_slug` cierra path traversal (regex `[^a-z0-9-]+` → `-`, strip, cap a 40, fallback `task`).

2. **Prompt injection** en `ClaudeCodeAdapter._build_prompt`: cuando `project_directory` está set y `project_id` es null, el prompt incluye los args exactos para invocar el MCP tool `project_create` (que ya existía en `servers/tasks-mcp/server.py:689`). Si es una tarea conversacional, Claude puede saltárselo.

3. **Post-hook safety net (`_auto_project_finalize`)** dentro de `try/finally` del wrapper `_execute_task_v02`: tras `adapter.start()`, si el directorio tiene ≥1 fichero regular y no existe fila `projects` con ese `directory`, inserta una automáticamente. En cualquier caso (fila nueva o existente), `UPDATE tasks SET project_id=? WHERE id=? AND project_id IS NULL` (nunca roba tareas con proyecto explícito). Si no hay ficheros (conversacional), `rmtree` del directorio vacío.

Container/host path mismatch evitado: todo el mkdir vive en el host (executor), el MCP container no necesita crear directorios. Tests en `tests/test_auto_project.py` (16 casos): slug sanitization incluyendo path traversal, prepare no-op con project_id, unique slug por call, finalize empty cleanup, finalize inserts + associates, finalize reuses existing row (Claude llamó tool), finalize never steals explicit project_id, adapter prompt injection condicional.

### Feature 2: Toggle "modo sin restricciones" en UI (Sistema → Agentes)

**Descripción:** PR-34 puso `--dangerously-skip-permissions` siempre ON. El plan original (PR-33) era un toggle en la UI que el operador pudiera activar/desactivar. El backend lee `executor.dangerous_mode` de la tabla settings (código presente en PR-33, removido en PR-34 porque el flag se hizo default). Para restaurar el toggle: re-añadir la lectura del setting en el executor y crear el componente React.

**Ubicación:** frontend pendiente. Backend: `bin/task-executor.py` + `niwa-app/backend/backend_adapters/claude_code.py`.
**Severidad:** **baja** (el flag siempre ON es funcional; el toggle es control operacional).
**PR futuro donde se arreglará:** pendiente de asignar. ~30 LOC frontend + re-wire del setting en el executor.

### Feature 3: Configuración de DNS/dominios/subdominios desde la UI

**Descripción:** Actualmente los dominios, subdominios y DNS se configuran solo durante el install CLI (`--public-url`) y editando Caddyfile/cloudflared manualmente post-install. No hay panel en la UI para gestionar esto.

**Ubicación:** gap en el frontend. Backend parcial en `setup.py::configure_cloudflared` y `niwa-app/backend/hosting.py`.
**Severidad:** **media** (operadores avanzados lo hacen manual; operadores nuevos no saben cómo).
**PR futuro donde se arreglará:** pendiente de asignar. Scope mayor: endpoint CRUD de dominios + panel React + integración con Caddy admin API o rewrite del Caddyfile.

### Feature 4: Notificaciones/feedback visible de errores en la UI

**Descripción:** Cuando una tarea falla (permissions, auth, timeout), el usuario solo ve "hecha" o "en_progreso" sin explicación. Los errores están en los logs del executor o en backend_run_events, pero la UI no los surfacea de forma proactiva (toast, banner, badge).

**Ubicación:** gap en frontend. Backend: los errores ya están en `backend_run_events` con `event_type='error'`.
**Severidad:** **media UX** (el usuario no se entera de problemas hasta que mira los logs o los runs manualmente).
**Estado:** **ARREGLADO en PR-39 (parcial — solo detalle de tarea).**

Cambios:

1. Backend `tasks_service.get_task()` ahora expone `last_run` con shape `{id, status, outcome, error_code, finished_at, relation_type, backend_profile_slug, backend_profile_display_name}` vía LEFT JOIN con `backend_profiles`. Whitelist de columnas — los snapshots JSON (capability/budget/usage) nunca salen.

2. Frontend `TaskDetailsTab.tsx`: Alert rojo arriba del detalle cuando `last_run.outcome === 'failure'` (o hay `error_code`) AND `task.status !== 'hecha'`. La supresión en `'hecha'` es deliberada: si la tarea completó, un fallback triunfó y alarmar sería engañoso. El banner muestra `<backend_display_name> terminó con <error_code>` + botón "Ver runs" que navega a `/tasks/:id/runs`. Si el run es `relation_type='fallback'`, añade "(intento de fallback)".

Tests: 6 backend (`test_tasks_service_last_run.py`) incluyendo guard de leak de snapshots JSON y JOIN con backend_profiles; 4 frontend nuevos en `TaskDetailsTab.test.tsx` (banner visible, suprimido en hecha, suprimido sin last_run, suprimido con success).

**Follow-up pendiente (documentado explícitamente):** badge de error en listas/kanban. Sin ello, un usuario que no abre la tarea no se entera del fallo. Alternativa barata: añadir `has_failed_run: bool` al enriquecimiento `enrich_tasks_with_agent_info` (query agregada con `task_id IN (...)`), no JOIN en `fetch_tasks`. Candidato para PR-40+ si el usuario lo pide.
