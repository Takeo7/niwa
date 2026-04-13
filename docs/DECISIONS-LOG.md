# Decisiones tomadas durante implementación v0.2

Cada entrada: fecha, PR, decisión, motivo.

Formato sugerido:

```
## YYYY-MM-DD — PR-XX

**Decisión:** qué se decidió.
**Motivo:** por qué.
**Alternativas consideradas:** qué se descartó y por qué.
**Impacto:** qué otras partes del sistema se ven afectadas.
```

---

## 2026-04-12 — PR-00

**Decisión:** El nuevo ADR de arquitectura v0.2 se numera como `0002-v02-architecture.md`, no `0001` como indica el SPEC.
**Motivo:** Los ADRs son secuenciales a nivel de proyecto, no se reinician por versión de producto. Ya existe `0001-niwa-yume-separation.md` (historia válida del proyecto, creado 2026-04-08). El SPEC tiene un error de numeración en este punto.
**Alternativas consideradas:** Renumerar el ADR existente o usar un esquema de numeración por versión. Descartadas porque romperían enlaces existentes y complicarían la trazabilidad.
**Impacto:** El SPEC queda implícitamente corregido — futuros PRs deben seguir la numeración secuencial (0003, 0004, etc.).

## 2026-04-12 — Pre-PR-01

**Decisión:** Documentar el estado real del repositorio al inicio de v0.2 como baseline para PR-01 y siguientes.

### 1. Migraciones existentes (niwa-app/db/migrations/)

La última migración es `006`. Lista completa:

| # | Archivo | Contenido |
|---|---------|-----------|
| 001 | `001_baseline.sql` | Schema base |
| 002 | `002_chat_memory.sql` | Chat y memoria |
| 003 | `003_deployments.sql` | Deployments |
| 004 | `004_cleanup.sql` | Limpieza |
| 005 | `005_services_and_settings_unify.sql` | Unificación servicios/settings |
| 006 | `006_oauth_tokens.sql` | Tokens OAuth |

**Implicación para PR-01:** La nueva migración de v0.2 será `007_v02_execution_core.sql` (como dice el SPEC).

### 2. Ocurrencias de `--dangerously-skip-permissions` en código ejecutable

Tres ubicaciones en código real (no docs/spec/tests):

1. **`setup.py:1011-1014`** — El wizard lo añade automáticamente al comando Claude cuando se instala en Linux como root. Se activa sin confirmación del usuario.
2. **`setup.py:1650`** — Comentario mencionando que el flag falla como root (justificación del user `niwa`).
3. **`niwa-app/backend/app.py:2515`** — `base_flags = " --dangerously-skip-permissions"` — se aplica a **todos** los comandos de agente (chat/planner/executor) generados desde la UI de System > Agentes. Sin gate de aprobación.

**Severidad:** Alta. Dos de los tres puntos inyectan el flag sin consentimiento explícito. PR-04 y PR-05 deben gatearlo detrás de capability profiles y approvals.

### 3. Pipeline 3-tier Haiku→Opus→Sonnet

Sí, sigue activo en `bin/task-executor.py`, función `_execute_task()` (líneas 857-922):

- **Tier 1 (Chat → Haiku):** tareas con `source='chat'` van directas a `LLM_COMMAND_CHAT` (línea 870-877).
- **Tier 2 (Planner → Opus):** tareas no-chat pasan por `LLM_COMMAND_PLANNER` que decide `SPLIT_INTO_SUBTASKS` o `EXECUTE_DIRECTLY` (líneas 879-912).
- **Tier 3 (Executor → Sonnet):** ejecución real con `LLM_COMMAND_EXECUTOR` o `LLM_COMMAND` de fallback (líneas 914-922).

Además, en el prompt de Tier 1 (línea 441) se sigue instruyendo al chat a usar `assigned_to_claude=1` para trigger de ejecución automática — exactamente el anti-pattern que v0.2 depreca.

**Implicación:** Este pipeline se reemplazará por el sistema de backend adapters (PR-03/PR-04). Hasta entonces, sigue funcionando con la semántica v0.1.

**Motivo:** Establecer baseline verificable antes de las migraciones de PR-01.
**Alternativas consideradas:** Ninguna — es una auditoría, no una decisión de diseño.
**Impacto:** PR-01 (migración 007), PR-03/PR-04 (reemplazo del pipeline), PR-05 (gate del flag peligroso).

## 2026-04-12 — PR-01

### Decisión 1: Invariante schema.sql ↔ migraciones

**Decisión:** `schema.sql` representa el estado post-migración de un fresh install. Las migraciones que añaden tablas o columnas deben reflejarse también en `schema.sql`. `CREATE TABLE IF NOT EXISTS` y la comprobación explícita de existencia de columna antes de `ALTER TABLE ADD COLUMN` hacen que aplicar ambos sea seguro e idempotente.
**Motivo:** SQLite no soporta `ALTER TABLE ADD COLUMN IF NOT EXISTS`. Para mantener la invariante (schema.sql = estado completo), los tests usan un helper `_apply_sql_idempotent()` que comprueba `PRAGMA table_info()` antes de cada `ALTER TABLE ADD COLUMN` y lo salta si la columna ya existe. Esto es el equivalente funcional de `IF NOT EXISTS` para columnas.
**Alternativas consideradas:**
- try/except blanket para `duplicate column name` → tolerancia pasiva, no verificación. Rechazada.
- No incluir columnas nuevas en `schema.sql` → rompe la invariante de schema autoritativo. Rechazada.
- No usar ALTER TABLE en la migración → installs existentes no obtienen las columnas nuevas. Rechazada.
**Impacto:** Los 4 tests que aplican `schema.sql` + migraciones usan `_apply_sql_idempotent()` que verifica existencia de columna activamente. El test `test_migraciones_idempotentes_sobre_esquema` ahora aplica dos pases para verificar idempotencia real. Las migraciones 003, 005 y 004 violan esta invariante (ver BUGS-FOUND.md).

### Decisión 2: CHECK constraints solo para enums explícitos en SPEC PR-01

**Decisión:** Añadir CHECK constraints para `backend_kind`, `runtime_kind` y `relation_type`. No añadir CHECKs para `backend_runs.status` ni `approvals.status`.
**Motivo:** Los valores de estado de `backend_runs` y `approvals` se definen en PR-02 (máquina de estados). Adelantar esos CHECKs aquí violaría la regla de no adelantar trabajo de otros PRs.
**Alternativas consideradas:** Añadir CHECKs de status ahora con los valores del SPEC → rechazado por ser scope de PR-02.
**Impacto:** PR-02 deberá añadir los CHECK constraints para los campos de estado al implementar la máquina de estados.

### Decisión 3: FKs en ALTER TABLE (limitación de SQLite)

**Decisión:** Las columnas añadidas via ALTER TABLE (`requested_backend_profile_id`, `selected_backend_profile_id`, `current_run_id`) incluyen cláusula REFERENCES, pero SQLite no las enforce en columnas añadidas por ALTER TABLE. En `schema.sql` (fresh installs), estas FKs sí se enforcean porque están en el CREATE TABLE.
**Motivo:** Limitación conocida de SQLite. No hay workaround limpio sin recrear la tabla completa.
**Alternativas consideradas:** Recrear la tabla tasks → demasiado invasivo y riesgoso para datos existentes.
**Impacto:** En bases de datos actualizadas (no fresh install), las FKs de las 3 columnas nuevas no se validan a nivel de DB. La aplicación debe enforcar la integridad. Fresh installs no tienen este problema.

### Decisión 4: Tabla count — 9 tablas, no 8

**Decisión:** La migración crea 9 tablas nuevas (las 8 del título del SPEC + `secret_bindings` que también aparece en el listado detallado del SPEC PR-01).
**Motivo:** El SPEC lista explícitamente `secret_bindings` junto con las demás tablas en PR-01.
**Alternativas consideradas:** Ninguna — se implementó exactamente lo que dice el SPEC.
**Impacto:** Ninguno adicional.

## 2026-04-13 — PR-02

### Decisión 1: Reject es excepción autorizada a la state machine de tasks

**Decisión:** `hecha` es estado terminal en la state machine canónica — `can_transition_task('hecha', 'pendiente')` retorna `False`. El endpoint `/api/tasks/{id}/reject` bypasea la máquina de estados a través de `force_reject_task()`, una función dedicada que loguea cada uso para auditoría.
**Motivo:** Reject es un override humano explícito para tareas marcadas como hechas por error. No es un flujo automático, y tratarlo como transición válida rompería la semántica terminal de `hecha` para el resto del sistema.
**Alternativas consideradas:** Añadir `hecha → pendiente` como transición válida en la state machine — rechazado porque haría `hecha` no-terminal, afectando pipelines y métricas que asumen que `hecha` es final.
**Impacto:** Cualquier código futuro que necesite transicionar desde `hecha` debe decidir si la transición debería ser válida en la state machine o si necesita un bypass análogo documentado.

### Decisión 2: Transition maps duplicadas en tres runtimes

**Decisión:** Las transition maps de `tasks.status` se definen en tres ubicaciones: `niwa-app/backend/state_machines.py` (canónica), `servers/tasks-mcp/server.py` (inline) y `bin/task-executor.py` (inline). Las copias inline referencian la fuente canónica en un comentario.
**Motivo:** Los tres runtimes son independientes: el backend corre como proceso Python, el MCP server corre en un contenedor Docker separado, y el executor es un daemon host-side. No comparten sys.path ni filesystem. Añadir infraestructura compartida (paquete instalable, mount de volumen) excede el scope de PR-02.
**Alternativas consideradas:** (a) Paquete Python instalable con state_machines — scope excesivo para PR-02. (b) Mount del módulo en el contenedor Docker — acopla infraestructura al código.
**Impacto:** Los tests de PR-02 verifican que las tres copias son idénticas. Si un PR futuro refactoriza la distribución del código, deberá unificarlas.

### Decisión 3: No migrar datos existentes de `revision` a `waiting_input`

**Decisión:** La migración 008 no incluye `UPDATE tasks SET status='waiting_input' WHERE status='revision'`. Los datos existentes se dejan como están.
**Motivo:** No mezclar cambios de schema con modificaciones de datos en la misma migración. En el entorno de desarrollo actual no hay base de datos con tareas afectadas. Para instancias de producción futuras, la corrección de datos es un paso operacional manual.
**Alternativas consideradas:** Añadir UPDATE condicional en la migración — rechazado por el principio de no mezclar DDL y DML de corrección.
**Impacto:** Documentado en BUGS-FOUND.md como cleanup pendiente.

## 2026-04-13 — PR-03

### Decisión 1: Imports absolutos en módulos de backend, no relativos

**Decisión:** Los nuevos módulos (`backend_registry.py`, `backend_adapters/*.py`) usan imports absolutos (`from backend_adapters.base import BackendAdapter`) en lugar de relativos (`from .backend_adapters.base import ...`).
**Motivo:** El proyecto no trata `niwa-app/backend/` como un paquete Python instalable. Los archivos existentes (`state_machines.py`, `app.py`, etc.) se ejecutan con el directorio `niwa-app/backend/` en `sys.path`. Los imports relativos fallan en ese contexto porque Python no reconoce un paquete padre. Los tests de PR-02 siguen el mismo patrón: `sys.path.insert(0, BACKEND_DIR)` + imports absolutos.
**Alternativas consideradas:** (a) Crear un `setup.py`/`pyproject.toml` para instalar `niwa-app/backend` como paquete — scope excesivo, afecta toda la infraestructura de distribución. (b) Usar imports relativos y forzar ejecución como paquete — rompería `app.py` y `task-executor.py` que se ejecutan como scripts directos.
**Impacto:** Consistente con el resto del código. Si un PR futuro reorganiza la distribución, los imports se unificarán.

### Decisión 2: Seed de backend_profiles vía INSERT OR IGNORE en init_db()

**Decisión:** Los dos perfiles iniciales (`claude_code`, `codex`) se insertan con `INSERT OR IGNORE` en `seed_backend_profiles()`, llamada desde `init_db()` en `app.py`. No se usa una nueva migración SQL.
**Motivo:** La tabla `backend_profiles` ya existe (migration 007, PR-01). Insertar datos seed en una migración mezclaría DDL con DML de inicialización. `INSERT OR IGNORE` keyed on `slug` (UNIQUE) es idempotente: seguro en fresh install y en actualizaciones. Se ejecuta al arrancar la app, igual que los kanban_columns seed existentes.
**Alternativas consideradas:** (a) Migration 009 con INSERTs — rechazado porque mezcla schema con datos seed, y porque las migraciones de schema deben ser independientes de datos de aplicación. (b) Script de seed separado — añade complejidad operacional sin beneficio.
**Impacto:** Instalaciones existentes obtienen los perfiles en el siguiente arranque de la app. Fresh installs los obtienen en el primer arranque.

### Decisión 3: Eliminar --dangerously-skip-permissions sin romper el executor

**Decisión:** Se elimina `base_flags = " --dangerously-skip-permissions"` de `save_agents_config()`. Se mantiene la generación de `claude -p --model ... --max-turns N` (sin el flag peligroso) con un `TODO PR-04` para su reemplazo completo por backend adapters.
**Motivo:** `bin/task-executor.py` lee los settings `int.llm_command_*` directamente. Eliminar toda la generación de comandos rompería la ejecución antes de que PR-04 entregue el reemplazo basado en adapters. Eliminar solo el flag peligroso es seguro y cumple con el SPEC sin romper funcionalidad.
**Alternativas consideradas:** (a) Eliminar toda la generación de comandos — rechazado porque rompe la ejecución actual. (b) Dejar el flag con un TODO — rechazado porque el SPEC exige eliminarlo.
**Impacto:** Los comandos generados por la UI ya no incluyen `--dangerously-skip-permissions`. El flag en `setup.py` (inyección automática en Linux como root) queda fuera de scope de PR-03 — será atendido por PR-04/PR-05 con capability profiles.

### Decisión 4: Codex profile deshabilitado por defecto

**Decisión:** El seed de `codex` en `backend_profiles` se crea con `enabled=0` y `priority=0`. El seed de `claude_code` se crea con `enabled=1` y `priority=10`.
**Motivo:** El adapter de Codex es un stub hasta PR-07. Habilitar un backend cuyo `start()` lanza `NotImplementedError` causaría fallos en routing. Claude Code es el backend principal y estará implementado en PR-04.
**Alternativas consideradas:** Habilitar ambos — rechazado por el riesgo de routing a un backend no implementado.
**Impacto:** PR-07 deberá habilitar el perfil codex al implementar el adapter real.

### Decisión 5: Capabilities incluyen campos de budget con valores unknown

**Decisión:** `capabilities()` de cada adapter incluye 4 campos adicionales de resource-budget (`estimated_resource_cost`, `cost_confidence`, `quota_risk`, `latency_tier`) con valores `None`/`"unknown"` por defecto.
**Motivo:** Solicitud explícita del humano para anticipar la interfaz que PR-06 (routing determinista) necesitará. Los valores son inertes hasta PR-06.
**Alternativas consideradas:** No incluirlos hasta PR-06 — rechazado porque rompe la expectativa de la interfaz y fuerza cambios retroactivos.
**Impacto:** PR-06 reemplazará los defaults con lógica real de estimación.

## 2026-04-13 — PR-04

### Decisión 1: Mecanismo de ejecución — `claude -p --output-format stream-json`

**Decisión:** El adapter ejecuta `claude -p --output-format stream-json` como subproceso. El prompt se envía por stdin (pipe). Para resume se añade `--resume <session_id>`. `session_handle` = session_id devuelto por la CLI en los mensajes del stream.
**Motivo:** Es la forma documentada de usar Claude Code en modo no-interactivo con salida estructurada. El flag `-p` (print mode) consume stdin y produce respuesta. `--output-format stream-json` da JSON newline-delimited con tipos de evento que permiten streaming granular.
**Alternativas consideradas:** (a) PTY como task-executor.py — innecesariamente complejo para stream-json que ya va por stdout. (b) Escribir prompt en archivo temporal — stdin pipe es más limpio y evita archivos temporales huérfanos.
**Impacto:** El adapter depende de que `claude` esté en PATH. PR-06 (router) conectará esto al pipeline real.

### Decisión 2: Esquema de parse_usage_signals

**Decisión:** Esquema mínimo con 8 campos: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `model`, `cost_usd`, `duration_ms`, `turns`. Campos que la CLI no expone quedan como `null`.
**Motivo:** Sugerencia explícita del humano. Los tokens se extraen de `result.usage.*`, cost/duration de `result.cost_usd`/`result.duration_ms`, model de `result.model`, turns contando mensajes `assistant` en el stream.
**Alternativas consideradas:** Esquema más amplio con campos especulativos — rechazado por la regla de no fabricar datos.
**Impacto:** El esquema se serializa como JSON en `backend_runs.observed_usage_signals_json`. PR-06 puede extenderlo si necesita más señales.

### Decisión 3: Approval gate como stub en PR-04

**Decisión:** `check_approval_gate()` es una función libre en `claude_code.py` que siempre retorna `True`. Marcada con `TODO PR-05`.
**Motivo:** Instrucción explícita del humano: "deja un hook stub claramente marcado con TODO PR-05 que el adapter consulta antes de start(). Por defecto que devuelva permitido."
**Alternativas consideradas:** Implementar el sistema de approvals aquí — rechazado, es scope de PR-05.
**Impacto:** PR-05 reemplaza esta función con lógica real basada en capability_profiles y approval_service.

### Decisión 4: ClaudeCodeAdapter acepta db_conn_factory opcional

**Decisión:** El constructor toma `db_conn_factory: Callable | None = None`. Cuando se proporciona, el adapter escribe eventos/heartbeats/usage a la BD en tiempo real. Cuando es `None` (tests unitarios, queries de capabilities), no hace I/O de BD.
**Motivo:** La interfaz `BackendAdapter` de PR-03 no incluye `conn` en los métodos. El adapter necesita acceso a BD para streaming de eventos (requisito del SPEC). Un factory inyectable es la forma más limpia sin romper la interfaz base ni acoplar el adapter a una BD global.
**Alternativas consideradas:** (a) Pasar conn en cada método — rompe la interfaz del SPEC. (b) Singleton de BD global — acoplamiento innecesario. (c) Recopilar eventos en memoria y retornarlos — no cumple "logs parciales durante ejecución".
**Impacto:** `get_default_registry()` crea `ClaudeCodeAdapter()` sin factory (para capabilities). El caller real (PR-06) inyectará el factory al crear el adapter para ejecución.

### Decisión 5: runs_service.py implementa el ciclo de vida completo

**Decisión:** `runs_service.py` pasa de stubs a implementación real con: `create_run()`, `transition_run()`, `record_heartbeat()`, `record_event()`, `finish_run()`, `register_artifact()`, `update_session_handle()`.
**Motivo:** El adapter necesita estas operaciones para persistir el estado del run durante la ejecución. Son la capa de servicio entre el adapter y la BD.
**Alternativas consideradas:** Poner la lógica de BD directamente en el adapter — rechazado por separación de responsabilidades.
**Impacto:** PR-06 y PR-07 reutilizarán estas funciones para sus respectivos adapters.

### Decisión 6: artifact_root = workspace/.niwa/runs/<run_id>/

**Decisión:** Ruta determinista basada en run_id. Se crea en `start()`. Se escanea en `collect_artifacts()` para registrar archivos con sha256 y size.
**Motivo:** Instrucción explícita del humano. Ruta determinista permite localizar artifacts sin consultar BD.
**Alternativas consideradas:** Ruta basada en task_id — rechazado porque un task puede tener múltiples runs.
**Impacto:** El caller es responsable de pasar `artifact_root` en el dict `run`. El adapter crea el directorio si no existe.

### Decisión 7: Streaming de eventos — un evento por chunk relevante

**Decisión:** Cada línea JSON del stream se clasifica por `type` y se inserta como fila en `backend_run_events` con `event_type` descriptivo: `system_init`, `assistant_message`, `tool_use`, `tool_result`, `result`, `error`, `raw_output`.
**Motivo:** Instrucción explícita del humano: "No metas todo en un solo evento gigante al final." El streaming granular permite monitorización en tiempo real desde la UI (PR-10).
**Alternativas consideradas:** Agrupar mensajes por turno — más compacto pero pierde granularidad.
**Impacto:** La tabla `backend_run_events` acumulará muchas filas por run. PR-10 (UI) podrá paginar/filtrar por event_type.

### Decisión 8: Cancel idempotente con SIGTERM → SIGKILL

**Decisión:** `cancel()` envía SIGTERM, espera 5s, escala a SIGKILL si el proceso no respondió. Actualiza status a 'cancelled'. Es idempotente: llamar cancel sobre un run sin proceso activo retorna éxito.
**Motivo:** Instrucción explícita del humano. El intervalo de 5s es estándar para graceful shutdown.
**Alternativas consideradas:** Solo SIGKILL — rechazado porque no permite cleanup del proceso.
**Impacto:** Ninguno fuera de PR-04.

### Decisión 9: db_conn_factory en constructor del adapter — escritura directa en DB

**Decisión:** El adapter escribe directamente en DB desde el loop de streaming en lugar de reportar vía callback y que el caller persista.
**Motivo:** El requisito exige "logs parciales escritos a backend_run_events **durante** la ejecución". Si el adapter devolviera eventos vía callback, el caller necesitaría recibirlos en tiempo real mientras `start()` bloquea, requiriendo async o threads adicionales en el caller. Escribir directamente desde el loop es más simple y cumple la granularidad en tiempo real. `start()` y `resume()` lanzan `RuntimeError` si no se proporciona factory — nunca fallan silenciosamente.
**Alternativas consideradas:** `event_callback: Callable` inyectado en `start()` — descartado por complejidad innecesaria, el caller aún necesitaría un thread para recibir callbacks mientras `start()` bloquea. La interfaz abstracta `base.py` no cambia: `__init__` no forma parte de la interfaz.
**Impacto:** Adapter acoplado a factory de DB. PR-06 (router) inyecta el factory al crear el adapter para ejecución real. `get_default_registry()` crea instancias sin factory (solo para `capabilities()`).

### Decisión 10: artifact_root lo construye el caller, no el adapter

**Decisión:** El adapter recibe `artifact_root` como campo del dict `run`, no lo construye internamente. Solo crea el directorio (`mkdir -p`) y lo escanea en `collect_artifacts()`.
**Motivo:** Evitar acoplar el adapter a la configuración de paths del sistema. El SPEC dice "ruta determinista basada en run_id (ej: workspace/.niwa/runs/<run_id>/)", pero quién la construye no está especificado. El caller tiene el contexto necesario (workspace root, run_id).
**Alternativas consideradas:** Que el adapter calcule la ruta internamente — rechazado porque requeriría inyectar `WORKSPACE_ROOT` como configuración adicional del adapter.
**Impacto:** PR-06 (router) debe construir la ruta `workspace/.niwa/runs/<run_id>/` al crear el run via `runs_service.create_run()`.

### Decisión 11: Invocación de claude CLI no validada contra binario real

**Decisión:** El adapter usa `claude -p --output-format stream-json` con el prompt enviado por stdin (pipe). Probado solo contra `fake_claude.py`, no contra la CLI real. La CLI de Claude Code en modo `-p` (print) lee de stdin cuando no recibe argumento posicional.
**Motivo:** El requisito dice "No llames a la CLI real en CI." La validación real requiere credenciales de Anthropic y no es posible en el entorno de test.
**Alternativas consideradas:** Escribir el prompt en archivo temporal como hace `task-executor.py` — descartado porque stdin pipe es más limpio y evita archivos temporales huérfanos.
**Impacto:** Validación manual pendiente antes de PR-06. Si la CLI real exige el prompt como argumento posicional en lugar de stdin, `_build_command()` necesitará ajuste.

## 2026-04-13 — PR-05

### Decisión 1: Shell whitelist almacenada como constante Python, no en BD

**Decisión:** La whitelist de comandos shell (`ls`, `cat`, `grep`, `find`) para `shell_mode=whitelist` es una constante `DEFAULT_SHELL_WHITELIST` en `capability_service.py`. No se almacena en un campo dedicado de `project_capability_profiles`.
**Motivo:** El schema define `shell_mode TEXT` con valores `disabled|whitelist|free`. No hay columna dedicada para la lista de comandos permitidos. Añadir una columna `shell_whitelist_json` excede el scope del SPEC de PR-05.
**Alternativas consideradas:** (a) Codificar la lista en el valor del campo `shell_mode` (e.g., `"whitelist:ls,cat,grep,find"`) — parsing frágil, el campo es TEXT no JSON. (b) Añadir columna `shell_whitelist_json` — cambia el schema sin justificación en el SPEC.
**Impacto:** Per-project shell whitelists no son posibles hasta un PR futuro que añada el campo. La whitelist por defecto es suficiente para el MVP.

### Decisión 2: secrets_scope_json es no-op en PR-05

**Decisión:** El campo `secrets_scope_json` se almacena y se propaga, pero no se evalúa en runtime. No hay trigger asociado.
**Motivo:** Detectar acceso a secretos en runtime (variables de entorno, archivos sensibles) requiere hooking de procesos o análisis semántico del prompt — ambos fuera del alcance de PR-05. Los tests verifican que el campo no rompe nada.
**Alternativas consideradas:** Implementar checklist de paths sensibles en Bash — complejo, alta tasa de falsos positivos.
**Impacto:** El campo existe y se puede configurar. Un PR futuro puede implementar la evaluación cuando haya mecanismo fiable de detección.

### Decisión 3: quota_risk y estimated_resource_cost son no-op hasta PR-06

**Decisión:** La evaluación pre-ejecución (`evaluate()`) comprueba `quota_risk >= medium` y `estimated_resource_cost > max_cost_usd`, pero estos campos tienen valores `None`/`"unknown"` hasta que PR-06 (router determinista) los rellene. El trigger nunca se dispara en PR-05.
**Motivo:** El SPEC asigna la estimación de costos y riesgos a PR-06. PR-05 implementa la lógica de evaluación pero no genera los datos que la alimentan.
**Alternativas consideradas:** Hardcodear valores conservadores (e.g., `quota_risk="medium"` siempre) — rechazado porque bloquearía todas las ejecuciones sin beneficio.
**Impacto:** PR-06 debe popular `quota_risk` y `estimated_resource_cost` en las routing_decisions/tasks para que los triggers pre-ejecución se activen.

### Decisión 4: Seed de capability profiles para proyectos existentes, fallback para nuevos

**Decisión:** `seed_capability_profiles(conn)` inserta un perfil "standard" para cada proyecto existente que no tenga uno. Para proyectos sin perfil en BD (nuevos, o en fresh install sin proyectos), `get_effective_profile()` retorna `DEFAULT_CAPABILITY_PROFILE` como fallback.
**Motivo:** `project_capability_profiles.project_id` es `NOT NULL` con FK a `projects(id)`. No se puede insertar un perfil "global" sin un proyecto válido. El seed funciona para proyectos existentes; el fallback cubre el resto sin cambiar el schema.
**Alternativas consideradas:** (a) Hacer `project_id` nullable para perfil global — cambia el schema del SPEC. (b) Crear un proyecto sentinel — añade datos artificiales sin valor semántico.
**Impacto:** Cada arranque de la app seed automáticamente. Proyectos creados después del arranque usarán el fallback hasta el siguiente restart (o hasta que se cree su perfil explícitamente).

### Decisión 5: Runtime monitoring inserta return en el streaming loop

**Decisión:** Cuando se detecta una violación en el streaming loop, el adapter: (1) graba el evento en BD, (2) crea el approval, (3) transiciona el run a `waiting_approval`, (4) mata el proceso con SIGTERM→SIGKILL, (5) retorna inmediatamente desde `_execute()`.
**Motivo:** El proceso Claude debe morir cuando se detecta una violación — no se puede permitir que siga ejecutando. El `return` sale del loop y del método `_execute()`, y el `finally` block se encarga de limpiar el heartbeat thread.
**Alternativas consideradas:** (a) Pausar el proceso (SIGSTOP) y esperar resolución del approval — riesgo de procesos zombie, recursos de sistema ocupados indefinidamente. (b) Flag+break sin matar — el proceso seguiría ejecutando hasta terminar naturalmente.
**Impacto:** Tras resolver el approval como 'approved', se necesita un nuevo run con `relation_type='resume'` y `--resume <session_id>` (nota 4 del PR-05).

### Decisión 6: Terminal web movida a docker-compose.advanced.yml

**Decisión:** El servicio `terminal` (ttyd con `privileged: true`, `pid: host`, `network_mode: host`, `/:/host`) se elimina del `docker-compose.yml.tmpl` principal y se mueve a `docker-compose.advanced.yml`. Para habilitarlo: `docker compose -f docker-compose.yml -f docker-compose.advanced.yml up`.
**Motivo:** Instrucción explícita del humano (nota 5). El SPEC PR-05 dice "Desactivar terminal por defecto en install --quick" y "Mover a modo avanzado/operador".
**Alternativas consideradas:** Comentar el servicio en el compose principal — rechazado por instrucción explícita del humano ("No lo comentes — bórralo").
**Impacto:** Usuarios que necesiten el terminal deben usar el overlay. README actualizado con instrucciones.

### Decisión 7: Pre-execution denial con rapid state transitions

**Decisión:** Cuando la evaluación pre-ejecución deniega el run (con `approval_required=True`), el adapter hace transiciones rápidas `queued → starting → running → waiting_approval`. Si `approval_required=False`, la cadena es `queued → starting → running → failed`.
**Motivo:** La state machine no tiene caminos directos `queued → waiting_approval` ni `queued → failed`. Las únicas transiciones válidas son las definidas en PR-02. Las transiciones rápidas respetan la state machine sin requerir cambios.
**Alternativas consideradas:** (a) Añadir `queued → failed` a la state machine — fuera de scope de PR-05, cambia diseño de PR-02. (b) No hacer transiciones y solo retornar dict — deja el run en estado inconsistente (queued pero no ejecutable).
**Impacto:** En PR-05, la evaluación pre-ejecución siempre pasa (valores son None/unknown), así que las transiciones rápidas no se ejecutan realmente hasta PR-06.
