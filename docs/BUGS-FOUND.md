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

- **Sub-bug 18a (severidad media, pendiente):** `niwa-<instance>-hosting.service` tiene el mismo patrón (`StandardOutput=append:/opt/<instance>/logs/hosting.log` + `User=niwa`) pero no crashea porque `bin/hosting-server.py` no hace Python-level `open()` del fichero — usa `print()` y hereda el fd de systemd. Bug latente: cualquier futuro intento de logging Python-level en hosting reproducirá Bug 18.
- **Sub-bug 18b (severidad media, pendiente):** `setup.py` reporta "✓ Enabled and started" tras `systemctl enable --now` sin verificar que el servicio esté _stable_ (i.e. no en restart loop). Propuesta: esperar 15s y confirmar que `systemctl is-active == active` y el contador de restarts no está creciendo. Si no, abortar el install con mensaje claro. Esto matches el principio "fail loud" del proyecto.
