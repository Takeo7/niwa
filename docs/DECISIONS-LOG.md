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

### Decisión 1: Shell whitelist almacenada en columna `shell_whitelist_json`

**Decisión:** La whitelist de comandos shell se almacena en una columna dedicada `shell_whitelist_json` (JSON array de strings) en `project_capability_profiles`. Migración 009 añade la columna para bases existentes. El seed "standard" la puebla con `["ls","cat","grep","find","pwd","echo"]`. `DEFAULT_SHELL_WHITELIST` en `capability_service.py` queda como fallback cuando la columna es NULL.
**Motivo:** Configurable por proyecto sin redeploy. Auditable: `capability_snapshot_json` en backend_runs puede capturar el valor real que regía en ese run. Separación limpia: `shell_mode` define la política (`disabled|whitelist|free`), `shell_whitelist_json` define los comandos permitidos.
**Alternativas consideradas:** (a) Constante Python — no configurable por proyecto, requiere redeploy, no auditable. (b) Codificar dentro de `shell_mode` (e.g., `"whitelist:ls,cat"`) — parsing frágil, mezcla semánticas.
**Impacto:** Migration 009 (ALTER TABLE ADD COLUMN) para bases existentes. Schema.sql actualizado para fresh installs.

### Decisión 2: secrets_scope_json — detección runtime no-op, validación pre-exec pendiente

**Decisión:** La detección RUNTIME de acceso a secretos (identificar si un `tool_use` accede a un secret concreto) es no-op en PR-05. No se implementa trigger runtime para `secrets_scope_json`.
**Motivo:** Detectar en runtime si un `Bash` tool_use lee una variable de entorno secreta o un `Read` accede a un archivo de credenciales requiere hooking del proceso o análisis semántico del comando shell — ambos fuera del alcance de PR-05 y con alta tasa de falsos positivos.
**Lo que SÍ queda posible (pendiente):** La validación PRE-EJECUCIÓN contra `secret_bindings` (tabla existente en schema) es viable: antes de arrancar un run, se puede verificar que el proyecto tiene bindings configurados para los secrets que necesita, y denegar si faltan. Esta validación pre-exec queda pendiente para un PR futuro que implemente el flujo de `secret_bindings`.
**Alternativas consideradas:** Implementar checklist de paths sensibles en Bash — complejo, alta tasa de falsos positivos. Regex sobre comandos shell para `$SECRET_NAME` — no fiable, los secrets pueden accederse indirectamente.
**Impacto:** El campo `secrets_scope_json` se almacena, se propaga, y no rompe nada. La mitad del campo (runtime) es no-op; la otra mitad (pre-exec contra bindings) es implementable y queda pendiente.

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

### Decisión 7: Pre-execution denial con transiciones `starting → waiting_approval|failed`

**Decisión:** Se añaden `starting → waiting_approval` y `starting → failed` a la state machine de runs en `state_machines.py`. Cuando la evaluación pre-ejecución deniega el run, el adapter transiciona `queued → starting → waiting_approval` (o `starting → failed`). El run nunca pasa por `running`.
**Motivo:** El estado `running` implica que un proceso Claude está activo. Un run denegado pre-ejecución nunca arrancó un proceso, así que `running` es semánticamente incorrecto. Añadir las transiciones a `starting` es más limpio que forzar un `running` ficticio.
**Alternativas consideradas:** (a) Rapid transitions `queued → starting → running → target` — contamina el timeline con un `running` falso, confunde monitorización y métricas. (b) Denegar antes de crear el backend_run — pierde la trazabilidad del intento.
**Impacto:** `state_machines.py` actualizado (fuente canónica). Los 3 runtimes del SPEC solo copian task transitions, no run transitions, así que no hay copias que actualizar. Los tests de PR-02 actualizados con las nuevas transiciones válidas.

## 2026-04-13 — PR-06

### Decisión 1: API pública del router — `routing_service.decide(task, conn)`

**Decisión:** El router expone una función única `decide(task, conn) -> dict` que retorna `routing_decision_id`, `selected_backend_profile_id`, `fallback_chain`, `reason_summary`, `matched_rules`, `approval_required`, `approval_id`. Es idempotente: si la tarea ya tiene una routing_decision activa (con `selected_profile_id` set), la reusa.
**Motivo:** Interfaz mínima y autocontenida. El caller (task-executor) solo necesita llamar a `decide()` y actuar sobre el resultado. La idempotencia previene decisiones duplicadas si el executor re-procesa la misma tarea.
**Alternativas consideradas:** (a) Dos funciones separadas (route + persist) — más complejo sin beneficio. (b) Retornar solo el profile_id — pierde trazabilidad de la decisión.
**Impacto:** `decide()` es el único punto de entrada al router. `get_fallback_chain()` es un helper de consulta sobre decisiones ya persistidas.

### Decisión 2: Orden de evaluación determinista — 5 pasos

**Decisión:** El orden es: (1) pin explícito, (2) capability check, (3) resume-aware, (4) reglas persistidas, (5) default por prioridad. Primera coincidencia gana. El orden es fijo e inmutable sin cambio de código.
**Motivo:** Instrucción explícita del humano (nota 4). El pin siempre gana porque es intención directa del usuario. El capability check antes de las reglas porque si el coste/quota impide la ejecución, no tiene sentido seleccionar backend. Resume-aware antes de reglas porque la continuidad de sesión es más valiosa que una regla genérica.
**Alternativas consideradas:** Hacer el orden configurable via DB — rechazado por complejidad innecesaria y riesgo de configuraciones incoherentes.
**Impacto:** Cualquier cambio en el orden requiere modificar `routing_service.decide()`.

### Decisión 3: Resolución backend_slug → profile_id en tiempo de decisión

**Decisión:** Las reglas usan `backend_slug` en `action_json`, no `profile_id`. La resolución a `profile_id` ocurre en `_resolve_backend_slug()` en tiempo de decisión. Si el profile existe pero `enabled=0`, la regla se considera "no aplicable" y se evalúa la siguiente.
**Motivo:** Instrucción explícita del humano (nota 7). Desacopla las reglas de los IDs de backend. Cuando PR-07 habilite Codex (`enabled=1`), las reglas que apuntan a `codex` empezarán a funcionar sin cambios en el router ni en las reglas.
**Alternativas consideradas:** Almacenar `profile_id` directamente en `action_json` — rechazado porque acoplaría las reglas a IDs generados en seed, frágil ante reinstalaciones.
**Impacto:** Las reglas son portables entre instalaciones. El slug es la clave estable.

### Decisión 4: Seed de routing_rules — solo si tabla vacía

**Decisión:** `seed_routing_rules()` solo inserta las 3 reglas iniciales si `routing_rules` tiene 0 filas. No usa `INSERT OR IGNORE` por nombre — comprueba el count total. Si el usuario ha añadido, modificado o eliminado reglas, el seed no las toca.
**Motivo:** Instrucción explícita del humano (nota 6): "Las reglas son editables después por el usuario vía UI de PR-10. El seed solo se ejecuta si la tabla routing_rules está vacía." `INSERT OR IGNORE` por nombre podría reinsertar reglas que el usuario eliminó intencionalmente.
**Alternativas consideradas:** `INSERT OR IGNORE` keyed on name — rechazado porque re-insertaría reglas eliminadas por el usuario.
**Impacto:** Un usuario que borre todas las reglas y reinicie la app recuperará las 3 reglas seed. Comportamiento deseado.

### Decisión 5: Capability check pre-routing con approval sin backend_run_id

**Decisión:** Cuando el capability check deniega (quota_risk >= medium o estimated_resource_cost > budget), el router crea un approval via `approval_service.request_approval()` con `backend_run_id=None`. No se crea backend_run ni se selecciona backend.
**Motivo:** El approval bloquea antes de seleccionar backend — no hay run que asociar. La columna `approvals.backend_run_id` es nullable en el schema (`TEXT REFERENCES ... ON DELETE SET NULL`, sin `NOT NULL`). Verificado en `schema.sql:335` y `migrations/007:109`.
**Alternativas consideradas:** (a) Crear un backend_run "phantom" solo para tener un ID — contamina la tabla de runs con registros sin ejecución real. (b) No crear approval, solo retornar el flag — pierde la trazabilidad del bloqueo y la posibilidad de resolución humana.
**Impacto:** `approval_service.request_approval()` acepta `backend_run_id=None` sin error. El approval queda vinculado solo al task_id.

### Decisión 6: Feature flag routing_mode — "v02" vs "legacy"

**Decisión:** El setting `routing_mode` en la tabla `settings` controla qué pipeline usa el executor. Valores: `"v02"` (router determinista + adapters) y `"legacy"` (pipeline 3-tier Haiku→Opus→Sonnet). Fresh installs seed `"v02"` via `INSERT OR IGNORE` en `init_db()`. DBs pre-v0.2 que nunca ejecutaron init_db v0.2 no tienen la key → el executor infiere `"legacy"`.
**Motivo:** Instrucción explícita del humano (nota 10). Permite coexistencia sin romper installs existentes. La transición es opt-in para installs existentes (cambiar el setting a `"v02"`) y automática para fresh installs.
**Alternativas consideradas:** (a) Detectar automáticamente si hay backend_profiles en DB — frágil, los profiles existen desde PR-03 pero no implican que el routing funcione. (b) Variable de entorno — no persistente, se pierde entre reinicios.
**Impacto:** El executor lee `routing_mode` una vez por tarea (no por iteración del worker loop). Chat tasks y retries siempre usan legacy independientemente del flag.

### Decisión 7: No fallback silencioso de v02 a legacy

**Decisión:** Una vez que `_execute_task_v02()` empieza, si algo falla (ImportError de módulos, NotImplementedError del adapter, cualquier otra excepción), la tarea falla en v0.2 — no se redirige silenciosamente al pipeline legacy. La única ruta a legacy es la decisión explícita del dispatcher al inicio de `_execute_task()`.
**Motivo:** Revisión del humano durante la implementación. Un fallback implícito ocultaría bugs del sistema v0.2 y haría imposible saber si las tareas se ejecutaron por el camino correcto. Si el adapter de Codex lanza NotImplementedError, la tarea debe fallar visiblemente, no ejecutarse silenciosamente por el pipeline legacy.
**Alternativas consideradas:** Fallback a legacy en ImportError (para installs incompletos) — rechazado porque enmascara problemas de deployment.
**Impacto:** En routing_mode="v02", si un adapter no está implementado (Codex pre-PR-07), las tareas ruteadas a ese adapter fallan con `[v02] adapter not implemented: codex`. El run se marca como `failed` con `error_code="adapter_not_implemented"`.

### Decisión 8: get_execution_registry(db_conn_factory) — factory fresca, no singleton

**Decisión:** `backend_registry.get_execution_registry(db_conn_factory)` crea una nueva instancia de `BackendRegistry` con adapters instanciados con el factory. No es singleton. `get_default_registry()` (singleton, sin factory) se preserva intacta para queries de `capabilities()`.
**Motivo:** Instrucción explícita del humano (nota 11). El executor necesita un registry con adapters capaces de escribir en DB. Separar los dos registries evita contaminar el singleton con un factory de DB que no todos los callers necesitan. Un fresh registry por llamada evita estado compartido entre ejecuciones.
**Alternativas consideradas:** (a) Añadir factory al singleton — acopla todos los callers a la DB. (b) Pasar factory en cada llamada a `start()` — rompe la interfaz `BackendAdapter`.
**Impacto:** `_execute_task_v02()` llama a `get_execution_registry(_conn)` donde `_conn` es el factory del executor. El lifecycle del registry es una instancia por invocación de `_execute_task_v02()`.

### Decisión 9: _execute_task() como dispatcher de 12 líneas

**Decisión:** `_execute_task()` se convierte en un dispatcher que decide entre v02 y legacy. El cuerpo original se extrae a `_execute_task_legacy()` sin modificaciones semánticas (solo se eliminaron comentarios redundantes). La lógica nueva va en `_execute_task_v02()`.
**Motivo:** Separación limpia entre los dos pipelines. El legacy es código probado en producción que no debe tocarse. El v02 es código nuevo que puede evolucionar independientemente.
**Alternativas consideradas:** (a) Meter un `if` al inicio de `_execute_task()` — mezcla dos flujos en una función de 150 líneas. (b) Reemplazar `_execute_task()` enteramente — rompe el legacy.
**Impacto:** El main loop del executor no cambia. Sigue llamando a `_execute_task(task)`. La decisión de pipeline es interna.

## 2026-04-14 — PR-07

### Decisión 1: Codex CLI invocation — `codex exec --json` con prompt por stdin

**Decisión:** El adapter invoca `codex exec --json` como subproceso. El prompt se envía por stdin (pipe). El output esperado es JSON lines por stdout, con tipos de evento (`status`, `message`, `command`, `command_output`, `result`, `error`).
**Motivo:** Instrucción explícita del humano. La forma exacta de invocación no ha sido validada contra la CLI real de Codex.
**Alternativas consideradas:** (a) Prompt como argumento posicional `codex exec --json "prompt"` — posible pero stdin es más limpio para prompts largos. (b) Usar la API de OpenAI directamente — fuera del scope (el SPEC dice CLI).
**Impacto:** Pendiente validar con CLI real antes de PR-08. Si la CLI real exige otra forma de invocación, `_build_command()` necesitará ajuste. El fake_codex.py fixture emula el formato esperado.

### Decisión 2: resume_modes=[] — Codex no soporta resume

**Decisión:** `capabilities()` devuelve `resume_modes=[]`. El método `resume()` transiciona el run a `starting → failed` con `error_code="resume_not_supported"` y registra un evento explicativo. El router (paso 3 resume-aware de `decide()`) ya salta backends con `resume_modes` vacío.
**Motivo:** La CLI de Codex no tiene un flag `--resume` ni equivalente. El stub PR-03 tenía `resume_modes=["new_session"]`, que era incorrecto — `new_session` implicaba que podía hacer algo, pero no hay mecanismo real.
**Alternativas consideradas:** Mantener `resume_modes=["new_session"]` como en PR-03 — rechazado porque llevaría al router a intentar resume en Codex, que fallaría.
**Impacto:** Tareas con `current_run_id` apuntando a un run de Codex no se reanudan vía Codex — el router busca otro backend o cae al default.

### Decisión 3: Credenciales — el adapter asume env configurado por el caller

**Decisión:** El adapter NO duplica `_get_openai_oauth_token()` de `bin/task-executor.py`. Asume que el caller (executor) ya configuró `CODEX_HOME` y `OPENAI_ACCESS_TOKEN` en el entorno del subproceso vía `os.environ`.
**Motivo:** Opción (b) del humano. Extraer a función compartida (opción a) requiere refactorizar el executor y crear infraestructura de imports compartidos entre `bin/` y `niwa-app/backend/` — fuera del scope de PR-07.
**Alternativas consideradas:** (a) Extraer `_get_openai_oauth_token()` a un módulo compartido — requiere refactor del executor, posible en un PR futuro de limpieza. (b) Duplicar la lógica en el adapter — rechazado por principio DRY.
**Impacto:** El executor debe configurar las variables de entorno antes de llamar al adapter. Si falta `OPENAI_ACCESS_TOKEN`, el proceso Codex falla con error de auth — el adapter reporta el fallo limpio via `exit_code != 0`.

### Decisión 4: Habilitación del perfil codex — INSERT OR IGNORE + UPDATE condicional

**Decisión:** `_SEED_PROFILES` ahora tiene `enabled=1, priority=5` para codex (fresh installs). Para installs existentes, `upgrade_codex_profile()` hace `UPDATE ... SET enabled=1, priority=5 WHERE slug='codex' AND enabled=0 AND priority=0`. Si el usuario cambió cualquiera de esos campos, no se toca.
**Motivo:** Instrucción explícita del humano (nota 6). El patrón respeta la configuración del usuario: solo actualiza si los valores son los defaults viejos de PR-03.
**Alternativas consideradas:** (a) Solo cambiar `_SEED_PROFILES` sin UPDATE — installs existentes quedan con codex deshabilitado hasta que el usuario lo active manualmente. (b) UPDATE incondicional — pisaría la configuración del usuario.
**Impacto:** `seed_backend_profiles()` llama a `upgrade_codex_profile()` en cada arranque. La función también actualiza `capabilities_json` para reflejar `resume_modes=[]`. Claude mantiene `priority=10`, así sigue siendo el default del paso 5 de `decide()`.

### Decisión 5: Fallback escalation en _execute_task_v02 — primary + 1 fallback

**Decisión:** `_execute_task_v02()` ahora itera sobre `fallback_chain[:2]` (primary + máximo 1 fallback). Si el adapter primary lanza una excepción (NotImplementedError, RuntimeError, etc.), crea un nuevo `backend_run` con `relation_type='fallback'` y ejecuta el siguiente adapter. Si el fallback también falla, la tarea falla con mensaje claro.
**Motivo:** El SPEC PR-06 define la fallback_chain pero `_execute_task_v02()` no la usaba — si el adapter fallaba, la tarea se marcaba como failed sin intentar el fallback. El humano pidió evaluar si cabe en PR-07; cabe porque son ~50 líneas de cambio bien contenidas.
**Alternativas consideradas:** (a) No implementar, dejar para PR de router avanzado — rechazado porque el test de fallback Claude↔Codex lo requiere. (b) Cascada ilimitada — rechazado por instrucción explícita del humano ("solo 1 escalado"). (c) Escalar también en returned failures — rechazado porque un adapter que completó ejecución (aunque con fallo) ya hizo su mejor intento.
**Impacto:** Cada escalado se registra como evento `fallback_escalation` en `backend_run_events`. No hay fallback silencioso — cada paso se logea. Los returned failures (adapter.start() retorna `{"status": "failed"}`) NO se escalan; solo excepciones.

### Decisión 6: Runtime capability monitoring — normalización de eventos Codex

**Decisión:** Los eventos `command` de Codex se normalizan al formato `tool_use` de Claude antes de pasarlos a `capability_service.evaluate_runtime_event()`. La función `_normalize_for_runtime_check()` convierte `{"type": "command", "command": "rm -rf /"}` a `{"type": "tool_use", "name": "Bash", "input": {"command": "rm -rf /"}}`.
**Motivo:** `evaluate_runtime_event()` solo evalúa eventos con `type="tool_use"`. Codex usa un formato diferente (`type="command"`). Normalizar permite reutilizar toda la infraestructura de capability checks (shell whitelist, deletion, network, filesystem scope) sin duplicar código.
**Alternativas consideradas:** (a) Modificar `evaluate_runtime_event()` para aceptar ambos formatos — rechazado porque contamina el servicio de capabilities con lógica específica de un backend. (b) No hacer runtime monitoring en Codex — rechazado porque el SPEC dice "Runtime monitoring sobre los events que Codex emita".
**Impacto:** Si la CLI real de Codex emite eventos en un formato diferente al esperado, `_normalize_for_runtime_check()` necesitará ajuste.

## 2026-04-14 — PR-08

### Decisión 1: Modelo del LLM conversacional — `agent.assistant.model` aislado del legacy

**Decisión:** El LLM conversacional de `assistant_turn` lee su modelo de `agent.assistant` (JSON en tabla `settings`, campo `model`). Cadena de fallback: `agent.assistant.model` → `agent.chat.model` → `svc.llm.anthropic.default_model` → `"claude-haiku-4-5"`. La API key sigue la cadena existente: `svc.llm.anthropic.api_key` → `int.llm_api_key` → env `ANTHROPIC_API_KEY` → env `NIWA_LLM_API_KEY`.
**Motivo:** El tier conversacional v0.2 (`assistant_turn`) es un subsistema nuevo que no tiene relación con el Tier 1 legacy (Haiku chat vía CLI). Reutilizar directamente `agent.chat.model` acoplaría ambos: cambiar el modelo del pipeline legacy afectaría al cerebro conversacional v0.2 y viceversa. Un setting aislado permite divergir sin interferencia. El fallback a `agent.chat.model` cubre installs que no hayan configurado el nuevo setting.
**Alternativas consideradas:** (a) Reutilizar `agent.chat.model` directamente — rechazado por el acoplamiento legacy↔v0.2. (b) Crear un setting completamente nuevo sin fallback a agent.chat — rechazado porque forzaría configuración manual en toda instalación existente.
**Impacto:** Installs existentes sin `agent.assistant` en settings funcionan sin cambios (fallback). La UI de PR-10 podrá exponer la configuración del modelo conversacional como setting separado.

## 2026-04-14 — PR-09

### Decisión 1: MCP server como proxy HTTP (no import directo de assistant_service)

**Decisión:** El MCP server (`servers/tasks-mcp/server.py`) actúa como traductor fino de protocolo MCP→HTTP. Las 11 tools v02-assistant se implementan como proxies HTTP que llaman a los endpoints de la app (`/api/assistant/turn` y `/api/assistant/tools/{name}`). No se importa `assistant_service` ni se accede a la BD directamente para tools v02.
**Motivo:** Evitar fallback silencioso (import disponible → import, no disponible → HTTP). Viola la lección del proyecto "fail loud" (PR-06 Dec 7). Además, un solo path HTTP hace los tests honestos: lo que se testea es lo que se usa en producción. El MCP server no necesita la API key ni acceso directo a la BD para las tools v02.
**Alternativas consideradas:** (a) Import condicional con fallback a HTTP — rechazado por fallback silencioso. (b) Import directo sin fallback — requiere backend en sys.path del contenedor, acopla el MCP server a los módulos del app.
**Impacto:** Las tools legacy (v0.1) siguen con acceso directo a BD. Las tools v02 pasan por HTTP. Requiere NIWA_APP_URL y NIWA_MCP_SERVER_TOKEN configurados.

### Decisión 2: Auth service-to-service vía Bearer token

**Decisión:** La app acepta `Authorization: Bearer <token>` como alternativa a la cookie de sesión. El token se configura via `NIWA_MCP_SERVER_TOKEN` (env var, preferido) o `svc.mcp_server.token` (setting en BD, fallback). Comparación con `hmac.compare_digest` (constant-time).
**Motivo:** El MCP server necesita autenticarse contra la app para llamar los endpoints HTTP. Las cookies de sesión no son prácticas para comunicación server-to-server. Bearer token es el mecanismo más simple y estándar. Sin JWT/OAuth/complejidad adicional.
**Alternativas consideradas:** (a) Sin auth (confiar en la red Docker) — rechazado porque no es zero-trust y no funciona fuera de Docker. (b) API key en query string — rechazado por riesgo de logs/leaks.
**Impacto:** La función `is_authenticated()` ahora acepta bearer tokens además de cookies. La autenticación existente por cookie no se afecta.

### Decisión 3: Un solo MCP server con filtrado por contract

**Decisión:** El MCP server de v0.1 (`servers/tasks-mcp/server.py`) se extiende con las 11 tools v02. El filtrado por contract se implementa server-side via la variable de entorno `NIWA_MCP_CONTRACT`. Si está definida, el server lee el JSON del contract y solo registra las tools listadas. Sin la variable, expone las 21 tools legacy.
**Motivo:** El SPEC y el humano piden un solo MCP server. El filtrado server-side evita refactorizar el gateway Docker (que no soporta filtrado por contract nativamente). La variable de entorno es el mecanismo de configuración estándar de Docker.
**Alternativas consideradas:** (a) Dos MCP servers separados — rechazado por instrucción explícita del humano. (b) Filtrado en el gateway — requiere refactor del gateway Docker, fuera de scope.
**Impacto:** En modo assistant (`NIWA_MCP_CONTRACT=v02-assistant`), el server expone solo 11 tools. En modo core (sin variable), expone las 21 legacy. No hay mezcla.

### Decisión 4: Endpoints HTTP uno-por-tool en /api/assistant/tools/{name}

**Decisión:** Se crea un endpoint genérico `POST /api/assistant/tools/{tool_name}` que despacha al `TOOL_DISPATCH[tool_name]()`. Input: `{project_id, params}`. El endpoint de `assistant_turn` (`/api/assistant/turn`) ya existía de PR-08 y se preserva intacto.
**Motivo:** Un endpoint por tool permite al MCP server dirigir cada tool call a un path HTTP específico, con error mapping por tool. Un solo endpoint genérico con dispatch interno es más simple que 10 endpoints individuales y permite añadir tools futuras sin cambiar app.py.
**Alternativas consideradas:** (a) 10 endpoints individuales (`/api/assistant/tools/task_list`, etc.) como funciones separadas en app.py — rechazado por volumen de código duplicado. (b) Un endpoint único `/api/assistant/dispatch` con tool_name en el body — funcional pero oscurece el routing en logs y métricas.
**Impacto:** app.py gana ~30 líneas. Las tools se invocan con la misma signatura `(conn, project_id, params)` que usan internamente.

### Decisión 5: contract_version en routing_decisions como kwarg de decide()

**Decisión:** `routing_service.decide()` acepta `contract_version: str | None = None` como keyword argument. Se persiste en `routing_decisions.contract_version` (migration 011). NULL cuando no se especifica (modo core, callers existentes).
**Motivo:** El SPEC sección 7 exige persistir la versión del contrato activo. Un kwarg opcional es retrocompatible: callers existentes no necesitan cambios. El valor es NULL para decisiones hechas fuera del modo assistant.
**Alternativas consideradas:** Leer el contract_version desde settings en lugar de recibirlo como parámetro — rechazado porque el setting podría cambiar entre decisiones; el caller sabe qué contrato está activo.
**Impacto:** Callers existentes (task-executor) no se afectan. PR-11 o futuro código que enrute via assistant mode pasará `contract_version="v02-assistant"`.

### Decisión 6: Docker image tags no pinneados — anotado para PR-11

**Decisión:** PR-09 deja sin pinnear estas imágenes en `docker-compose.yml.tmpl`:
  - `docker/mcp-gateway:latest` (servicio `mcp-gateway`, línea 48) — gateway streamable-http principal para modo assistant.
  - `docker/mcp-gateway:latest` (servicio `mcp-gateway-sse`, línea 88) — gateway SSE legacy, marcado como LEGACY en el comentario.

No se tocan otras imágenes (`tecnativa/docker-socket-proxy:0.3.0` ya está pinneada, `caddy:2-alpine` está pinneada por rama major, `${INSTANCE_NAME}-app:${NIWA_VERSION}` es imagen local con versión).

Se añaden comentarios `TODO PR-11: pin to a fixed tag` en ambas líneas. La razón del deferral: PR-11 (installer) es quien conoce el entorno target y puede resolver la versión semántica correcta del gateway en el momento del install — aquí en PR-09 no tenemos forma de validar que un tag concreto exista.
**Motivo:** Pinnear a un tag arbitrario puede romper installs existentes si el tag no existe en Docker Hub. El SPEC PR-11 dice explícitamente "Pinned Docker images, not `latest` in quick mode (`mcp-gateway` y `mcp-gateway-sse` están en `:latest` hoy; operational drift innecesario)". Scope explícito del installer.
**Alternativas consideradas:** (a) Pinnear a `:0.1.0` o similar — rechazado por riesgo de tag inexistente y acoplamiento a una versión sin validar. (b) Scripts de detección automática de tag — scope excesivo para PR-09.
**Impacto:** PR-11 debe resolver la versión del `docker/mcp-gateway` y reemplazar `:latest` por el tag fijo en ambas líneas del template. El template actual sigue funcionando (Docker resuelve `:latest` a la imagen más reciente en el registry).

### Decisión 7: OpenClaw skill file (niwa-skill.md) no actualizado — scope de PR-11

**Decisión:** `config/openclaw/niwa-skill.md` sigue documentando las tools v0.1. En v0.2 con contract v02-assistant, OpenClaw ve las 11 nuevas tools, no las 21 legacy. Actualizar el skill file es scope de PR-11 (installer), que es quien configura el modo assistant y registra el MCP.
**Motivo:** El skill file es un documento instructivo para OpenClaw, no una configuración técnica. Su contenido debe reflejar las tools que OpenClaw realmente ve, que depende de cómo PR-11 configure el NIWA_MCP_CONTRACT.
**Alternativas consideradas:** Actualizar ahora — rechazado porque sería trabajo de PR-11 y podría quedar stale si PR-11 cambia la configuración.
**Impacto:** Ninguno inmediato. PR-11 debe actualizar el skill file.

## 2026-04-14 — PR-10a

### Decisión 1: Promover `TaskDetail` de Modal a ruta `/tasks/:taskId` con sub-tabs

**Decisión:** `TaskDetail` deja de ser un Mantine `Modal` y pasa a ser una página con rutas anidadas. URL canónicas:
  - `/tasks/:taskId`          → tab "Detalles" (`TaskDetailsTab`, body de edición migrado desde el Modal previo)
  - `/tasks/:taskId/runs`     → tab "Runs" (`RunsTab` con `RunList` + `RunTimeline`)
  - `/tasks/:taskId/routing`  → tab "Routing" (`RoutingTab`)

El layout vive en `TaskDetailPage.tsx`, que renderiza header + `<Tabs>` + `<Outlet />` pasando el task al contexto del outlet para que los hijos no refetcheen. `TaskList` y `KanbanBoard` ahora hacen `navigate(\`/tasks/\${id}\`)` en lugar de abrir modal; el archivo antiguo `features/tasks/components/TaskDetail.tsx` se elimina.

**Motivo:** El volumen informacional de PR-10a (lista de runs + timeline granular de eventos + explicación de routing) excede lo razonable para un Modal. Más importante: el Modal no tiene URL estable, no soporta back/forward ni deep-linking, y no permite compartir enlace a "el run que falló en la tarea X". Mi primera propuesta (tabs dentro del Modal) se revirtió tras feedback del humano. La promoción a ruta replantea el patrón que PR-10b/c/e también usarán (approvals, artifacts, chat a nivel de tarea).

**Alternativas consideradas:**
- Modal con Tabs internas (propuesta original, rechazada). Sin URL estable, incompatible con compartir enlaces.
- Modal + rutas separadas para Runs/Routing (opción B del humano). Requeriría duplicar el header de tarea en múltiples vistas y dejar el Modal como punto de entrada asimétrico.
- Promover solo Runs/Routing a rutas, Detalles sigue en Modal. Inconsistente.

**Impacto:** Router gana 3 rutas; `TaskList.onRowClick` y `KanbanBoard.onTaskClick` pasan a `navigate`. El patrón queda como plantilla para PR-10b (`/tasks/:id/approvals`), PR-10c (`/tasks/:id/artifacts`) y cualquier otra vista de tarea futura. Cero dependencias npm añadidas — `react-router-dom@7` ya estaba en el árbol.

### Decisión 2: Tests de UI diferidos hasta que se añada vitest

**Decisión:** PR-10a no añade infra de tests de frontend (vitest, @testing-library/react, jsdom, happy-dom). Los componentes nuevos (`StatusBadge`, `Timeline`, `DurationLabel`, `RelativeTime`, `MonoId`, `RunList`, `RunTimeline`, `RunsTab`, `RoutingTab`, `TaskDetailPage`, `TaskDetailsTab`) quedan sin cobertura de tests unitarios. Tests de backend (32 nuevos en `test_runs_endpoints.py` + `test_runs_service_read_queries.py`) cubren el contrato HTTP que consume la UI.

**Motivo:** `package.json` no declara ningún runner de tests. Montar vitest + configuración + mocks de TanStack Query + MantineProvider + BrowserRouter en PR-10a mezclaría un PR de producto con uno de infraestructura. El humano lo confirmó vía escalado.

**Alternativas consideradas:**
- Añadir vitest ahora — rechazado: scope creep + decisión de infra que debe coordinarse con el lint/CI actual.
- Tests con Playwright / Cypress — descartado por coste de infra y lentitud en CI.

**Impacto:** Cuando se añada vitest (PR dedicado, candidato: antes de PR-12 "Tests de verdad"), escribir tests unitarios para los componentes shared/ primero (son puros, sin red), luego para las hooks de `features/runs/` con `QueryClient` mockeado, y finalmente un smoke test por página.

### Decisión 3: `TaskDetail` Modal eliminado, no coexiste con la nueva ruta

**Decisión:** `features/tasks/components/TaskDetail.tsx` se elimina del árbol de fuentes en este PR. No se deja como wrapper deprecated ni alias.

**Motivo:** Regla del SPEC apartado 8: "si es unused, bórralo completamente". Dos consumidores (`TaskList`, `KanbanBoard`) se migran en el mismo PR, así que no queda ningún import colgante.

**Impacto:** Cualquier rama abierta que importe `TaskDetail` tendrá conflicto de import. Las dos migraciones son visibles en el diff del PR.

### Decisión 4: Endpoints de lectura en `runs_service.py`, no módulo nuevo

**Decisión:** Los cuatro helpers nuevos (`list_runs_for_task`, `get_run_detail`, `list_events_for_run`, `get_routing_decision_for_task`) viven en `niwa-app/backend/runs_service.py`, no en un módulo separado `runs_api.py` ni `runs_queries.py`.

**Motivo:** El módulo ya es la home del dominio "runs". Cuatro funciones de lectura caben sin que el archivo crezca desproporcionadamente (~190 líneas añadidas sobre ~200 previas). Añadir un módulo por cada slice de PR-10 crearía fragmentación artificial.

**Alternativas consideradas:**
- Módulo dedicado `runs_api.py` — rechazado por sobre-ingeniería para 4 funciones.
- Embebido en `app.py` — rechazado: `app.py` ya es el monstruo que PR-03 dejó documentado evitar.

**Impacto:** Si PR-10b/c/d añade helpers similares de lectura, se evalúa si el archivo sigue siendo legible. Si supera ~800 líneas, extraer.

### Decisión 5: Bug 11 esquivado por lectura directa de columna

**Decisión:** `get_routing_decision_for_task()` lee `reason_summary` directamente de la tabla `routing_decisions`. No pasa por `assistant_service._tool_run_explain`, que contiene Bug 11 (lee `d.get("reason_summary_json")`, columna inexistente).

**Motivo:** Instrucción explícita del humano en el prompt de PR-10a. Corregir el bug pertenece a un PR de limpieza distinto.

**Impacto:** La vista de Routing muestra el reason real siempre que la columna esté poblada. El test `test_reason_summary_read_directly_bypasses_bug_11` queda como guarda anti-regresión.

### Decisión 6: Shape de runs incluye el backend_profile joined

**Decisión:** `list_runs_for_task` y `get_run_detail` hacen `LEFT JOIN backend_profiles` y exponen `backend_profile_slug` + `backend_profile_display_name` en el mismo payload. La UI no hace una segunda query por profile.

**Motivo:** Densidad informacional alta y tabla plana son expectativa del registro editorial. Evitar N+1 queries desde el cliente. `LEFT JOIN` (no `INNER JOIN`) porque `backend_profile_id` puede ser NULL si el profile fue borrado con `ON DELETE SET NULL`.

**Impacto:** Si en un futuro `backend_profiles` gana más columnas que interese exponer, se añaden al SELECT con un solo cambio.

### Decisión 7: Events ordenados por `created_at ASC, rowid ASC`

**Decisión:** `list_events_for_run` ordena por `created_at ASC, rowid ASC`. SQLite mantiene `rowid` en orden de inserción, así que sirve como desempate estable cuando los eventos se emiten dentro del mismo segundo (timestamps se truncan a segundos por `_now_iso()`).

**Motivo:** El adapter emite varios eventos por segundo durante tool loops. Ordenar solo por `created_at` produciría orden no determinista cuando coinciden timestamps.

**Alternativas consideradas:**
- Cambiar `_now_iso()` a microsegundos — fuera de scope, afecta a muchos callers.
- Secundario `id ASC` con UUIDs — no determinista porque UUIDs son aleatorios.

**Impacto:** La timeline de la UI respeta el orden cronológico real de emisión.

### Decisión 8: `/api/tasks/:id/routing-decision` devuelve 404 cuando no hay decisión

**Decisión:** El endpoint responde `404` con `{"error": "no_decision"}` cuando la tarea existe pero aún no tiene routing decision (ej: tarea en `inbox` pre-routing, tarea creada antes de v0.2). El hook `useTaskRoutingDecision` intercepta el 404 y devuelve `null` en lugar de propagar el error.

**Motivo:** Es un estado normal, no una condición de error. Un hook que renderiza error rojo ante la ausencia de datos legítimos ensucia la UX. La separación "404 = no hay dato" vs "500/otro = falló algo" preserva la semántica HTTP.

**Alternativas consideradas:**
- Devolver `200 {}` — ambiguo, rompe el discriminador entre "sin datos" y "respuesta vacía por error parseo".
- Exponer `routing_decision: null` dentro de un payload más ancho — obliga al cliente a diferenciar "no hay tarea" de "no hay decisión", complicando tipado.

**Impacto:** La `RoutingTab` renderiza estado vacío con mensaje instructivo cuando no hay decisión; el resto de la UI no se rompe.

## 2026-04-14 — PR-10b

### Decisión 1: `POST /api/approvals/:id/resolve` con verbo explícito, no `PATCH /api/approvals/:id`

**Decisión:** La resolución de un approval se expone como `POST /api/approvals/:id/resolve` con body `{decision: "approve"|"reject", resolution_note?: string}`. No se usa `PATCH /api/approvals/:id` con `{status: "approved"|"rejected"}`.

**Motivo:** (a) Consistencia con el precedente del repo — `POST /api/tasks/:id/reject` ya usa la forma "verbo explícito" y aquí aplica la misma lógica. (b) El método backend se llama `approval_service.resolve_approval` — exponer el mismo verbo en HTTP evita la doble traducción mental "PATCH status → resolve". (c) Separa resoluciones de futuras mutaciones (si en v0.3+ se permite editar `resolution_note` post-hoc, ese cambio es PATCH; la acción de resolver nunca lo será).

**Alternativas consideradas:**
- `PATCH /api/approvals/:id` con `status` — más "RESTful" formalmente, pero ambigua: ¿permite también cambiar `resolution_note` de un approval ya resuelto? Abre preguntas innecesarias para v0.2.
- `POST /api/approvals/:id/approve` y `POST /api/approvals/:id/reject` como dos endpoints distintos — redundante; ambos comparten body y validación.

**Impacto:** La UI invoca un único endpoint. El mapeo `decision → status` (approve→approved, reject→rejected) vive exclusivamente en el handler del endpoint.

### Decisión 2: `resolved_by = NIWA_APP_USERNAME` es proxy de identidad válido SOLO en v0.2 mono-usuario

**Decisión:** El endpoint `POST /api/approvals/:id/resolve` escribe `approvals.resolved_by = NIWA_APP_USERNAME` (el valor del env var/setting global con el que se firma la cookie de sesión). No se añade columna nueva ni se introduce un modelo de usuarios en esta capa.

**Motivo:** En v0.2 la instalación es mono-usuario por diseño — hay un único `NIWA_APP_USERNAME` y una única cookie válida. En ese régimen, el nombre del usuario global es un proxy aceptable de "quién resolvió": si la cookie es válida, fue ese usuario. La columna `resolved_by` es `TEXT` sin FK, así que cualquier string es válido como identificador.

**Lo que esto NO es — aviso explícito para el futuro:**
- `NIWA_APP_USERNAME` NO es identidad real. Es la etiqueta del único usuario configurado en el env var global, no un identificador de sujeto autenticado.
- Los valores de `resolved_by` escritos en v0.2 NO son auditoría fiable retroactiva cuando v0.3+ introduzca multiusuario. Si se cambia `NIWA_APP_USERNAME` entre resoluciones (o se renombra la instancia), todos los registros previos quedan asociados al username *actual* del momento en que se leen los logs, no al del momento del resolve. Nada en v0.2 previene esa deriva.
- Consumidores de los logs de approvals de v0.2 deben tratar `resolved_by` como "la instancia Niwa" o "el único operador", no como "el usuario humano X".

**Pendiente para v0.3+:** Modelo real de usuarios (tabla `users`, sesiones con `user_id`, FK desde `approvals.resolved_by` al `users.id`), migración que trate los `resolved_by` legacy como strings opacos sin promocionarlos a FK, y documentación que marque la frontera entre los dos regímenes.

**Alternativas consideradas:**
- Hardcodear `"web-ui"` — pierde la información de qué instalación lo resolvió (si alguien migra la BD a otro host sigue siendo útil saberlo).
- Dejar `resolved_by = NULL` — rompe el contrato del schema (columna documentada como "quién resolvió", aunque técnicamente nullable).
- Añadir ya una tabla `users` mínima — fuera de scope de PR-10b y afecta migraciones y auth, mucho mayor que lo que el PR pide.

**Impacto:** Documentado arriba. Código queda aceptable para v0.2 y marca la deuda clara para v0.3+.

### Decisión 3: Tab "Approvals" en TaskDetailPage siempre visible con empty state

**Decisión:** El tab "Approvals" en `/tasks/:taskId` aparece en la lista de tabs independientemente de si la tarea tiene approvals. Con cero approvals renderiza un estado vacío con copy explicativo.

**Motivo:** Instrucción explícita del humano en el prompt de PR-10b (restricción D): "No lo escondas condicionalmente — rompería la estabilidad de URLs deep-linkables". Alineado con PR-10a Dec 1 (promoción de Modal a ruta): la razón para tener sub-rutas es precisamente que las URLs sobrevivan a back/forward/share, lo cual requiere que la ruta exista aunque el contenido sea vacío.

**Alternativas consideradas:** Ocultar el tab si `approvals.length === 0` — rompe el deep-link `/tasks/:id/approvals` compartido (aparecería 404 o redirigiría a `/tasks/:id`), y fuerza al usuario a descubrir el tab solo cuando la tarea ya tiene approvals.

**Impacto:** Añade un tab permanente en TaskDetailPage. El empty state es copy-only — sin coste de renderizado relevante.

### Decisión 4: Enrichment helpers nuevos en `approval_service`, no JOIN en `app.py`

**Decisión:** Se añaden `approval_service.list_approvals_enriched` y `approval_service.get_approval_enriched` con LEFT JOIN a `tasks` para exponer `task_title` y `task_status` inline. No se toca la firma existente de `list_approvals` / `get_approval` — los siguen usando rutas internas (`capability_service`, `routing_service`) que no necesitan el enrichment.

**Motivo:** Consistencia con PR-10a Dec 4 (helpers de lectura en `runs_service.py`, no módulo aparte ni JOIN en el handler HTTP). Concentra la lógica de forma de datos en el módulo de dominio; el handler HTTP solo valida input y serializa.

**Alternativas consideradas:**
- Hacer el JOIN en `app.py` — mezcla dominio y transporte; el test unitario del join solo se alcanza vía tests end-to-end del endpoint en vez de tests de unit del service.
- Extender `list_approvals` con un flag `enriched: bool` — firmas con flags "cambian de forma" son mala práctica; cada caller elegiría su variante y las refactorizaciones futuras requerirían más cuidado.

**Impacto:** `approval_service.py` crece ~60 líneas. Ambas funciones son reutilizables por futuros callers (MCP server, CLI, reporting).

### Decisión 5: Frontend mapea `risk_level` con fallback visible, no silencioso

**Decisión:** `features/approvals/riskLevel.ts` mapea los 4 valores canónicos (`low|medium|high|critical`) a una paleta Mantine sobria (gray/yellow/orange/red). Cualquier otro valor se renderiza gris + variante `outline` + label con el string crudo + tooltip "Valor no canónico (ver BUGS-FOUND Bug 9)".

**Motivo:** Bug 9 (PR-06) documenta que `approval_service.request_approval` no valida `risk_level` contra valores canónicos, así que la BD puede contener drift. Normalizar silenciosamente (p.ej. "desconocido" → `low`) oculta la deriva y dificulta rastrearla. Renderizar verbatim con un indicador visual distinto hace que un humano revisando la lista vea "aquí pasó algo raro" sin abrir la BD.

**Alternativas consideradas:**
- Ocultar la badge si `risk_level` no es canónico — esconde información.
- Mostrar solo el string sin color ni tooltip — pierde la pista visual de "esto no es lo esperado".
- Normalizar backend → canónico antes de servir — arregla el Bug 9 pero eso pertenece a otro PR (prompt explícito: "No arreglar aquí").

**Impacto:** La UI de v0.2 tolera cualquier valor que el backend inserte hoy. Cuando Bug 9 se arregle, la badge pasará a renderizarse como canónica sin cambios en el frontend.

### Decisión 6: UI sin tests unitarios — extensión de PR-10a Decisión 2

**Decisión:** PR-10b sigue sin añadir infra de tests de frontend (vitest, @testing-library/react, jsdom). Los componentes nuevos (`ApprovalList`, `ApprovalsPage`, `ApprovalsTab`, `ApprovalResolveModal`) quedan sin cobertura de tests unitarios. Backend tests (25 nuevos en `test_approvals_endpoints.py`) cubren el contrato HTTP que consume la UI.

**Motivo:** PR-10a Dec 2 ya estableció la postura — añadir vitest + configuración + mocks aquí mezcla un PR de producto con uno de infra. El plan sigue siendo un PR dedicado de test infra (candidato: antes de PR-12).

**Alternativas consideradas:** Añadir vitest mínimo ahora — mismo análisis que en PR-10a; el humano lo confirmó vía escalado en PR-10a.

**Impacto:** Los caminos críticos (mapeo `decision → status`, respuesta 409 en conflicto, forma del payload enriquecido) se verifican vía los 25 tests de backend. Los componentes React quedan sin verificación automatizada hasta el PR de infra.

### Decisión 7: Filtro `status=all` es un sentinel frontend-only

**Decisión:** El `SegmentedControl` de `/approvals` incluye la opción `"all"`. Cuando el usuario la selecciona, el hook `useApprovals` NO envía el query param `status` al backend (el endpoint lo interpretaría como valor no canónico y filtraría a cero resultados, ya que `approvals.status` solo tiene `pending|approved|rejected`).

**Motivo:** Traducir `"all"` en el backend a "sin filtro" obligaría a tratar un valor mágico en el handler; traducirlo en el frontend a "no mandar param" es natural con `URLSearchParams`.

**Alternativas consideradas:** Aceptar `status=all` en el backend como equivalente a sin-param — mezcla semántica de la API con preferencias de la UI.

**Impacto:** El backend mantiene un contrato limpio (`status` es opcional; si se pasa, se usa literal). El frontend es quien conoce el sentinel `"all"`.

### Decisión 8: Invalidación amplia de queries tras resolve — incluye `['tasks']` (lista)

**Decisión:** `useResolveApproval.onSuccess` invalida cinco familias de queries: `['approvals']`, `['task-approvals', taskId]`, `['approval', id]`, `['task-routing', taskId]`, `['task', taskId]`, y `['tasks']` (lista plural).

**Motivo:** Un approval resuelto en `approved` puede desbloquear la tarea: el adapter crea un run de resume (PR-05 Dec 5) que transiciona la tarea fuera de `waiting_approval` eventualmente. La lista de tareas y la vista de detalle deben reflejar ese cambio tan pronto el backend lo produzca, sin depender de la siguiente ronda de polling. El coste de invalidar es bajo; el de no hacerlo es UI desincronizada hasta 10s (refetch interval).

**Alternativas consideradas:** Invalidar solo lo relacionado con el approval y dejar que el polling de tasks (si existe) refresque su lista — asume un loop de polling que el repo no garantiza (`useTasks` no tiene `refetchInterval`).

**Impacto:** Un resolve toca 6 query keys. Sobrecoste de red mínimo; la UI queda coherente en el siguiente render.

## 2026-04-14 — PR-10c

### Decisión 1: Artifacts viven dentro de la tab "Runs", no como ruta o tab propia

**Decisión:** La vista de artefactos se integra como tercera sección dentro de `RunsTab` (`/tasks/:taskId/runs`), debajo del grid `RunList`/`RunTimeline`. No se añade una ruta nueva (`/runs/:runId`) ni una tab aparte a `TaskDetailPage`. El contenido cambia según el run seleccionado en `RunList`.

**Motivo:** Los artifacts son por `backend_run_id`, no por tarea — no encajan como sub-tab a nivel de tarea (PR-10a Dec 1 decidió que los sub-tabs son por tarea). Crear una ruta top-level `/runs/:runId` introduciría un punto de entrada asimétrico: los runs solo se alcanzan desde el contexto de una tarea, así que un permalink a run suelto no tiene ancla natural en la navegación. Mantenerlos en `RunsTab` preserva el flujo "entro en tarea → miro su ejecución → veo sus artefactos" sin saltos.

**Alternativas consideradas:**
- Ruta independiente `/runs/:runId` con pestañas Timeline/Artifacts — rechazada porque duplica el header de run y requeriría propagar el contexto de tarea de vuelta (breadcrumb). Sin ganancia clara.
- Sub-tab "Artifacts" en `TaskDetailPage` — rechazado: un task tiene N runs con M artifacts cada uno; agrupar por tarea mezclaría artifacts de runs distintos y confundiría qué artifact pertenece a qué ejecución.

**Impacto:** `RunsTab` gana una sección pero no rutas. Si en un futuro se quiere permalink a artifacts de un run concreto, se podría añadir query param (`?run=<id>`) sin mover el componente.

### Decisión 2: Sin endpoint separado de event detail — `GET /api/runs/:id/events` ya devuelve `payload_json`

**Decisión:** El drawer de detalle de evento consume el mismo payload ya cargado por `useRunEvents`. No se crea `GET /api/runs/:id/events/:eventId`. El hook encuentra el evento por id en el array cacheado y lo pasa al drawer.

**Motivo:** El endpoint de PR-10a ya emite la fila completa (`id, backend_run_id, event_type, message, payload_json, created_at`). El tamaño por evento es del orden de KBs; el array completo por run es manejable en cliente. Duplicar un endpoint por elemento añadiría round-trips y complicaría el routing para nada.

**Alternativas consideradas:** Endpoint dedicado `GET /api/runs/:id/events/:eventId` que cargue sólo el evento seleccionado — útil si los payloads fueran megabytes. No es el caso: los eventos de `stream-json` raramente superan decenas de KB. La optimización prematura no aplica.

**Impacto:** Si un run genera cientos de miles de eventos, la carga inicial del timeline podría ser pesada — pero eso es un problema de `list_events_for_run` (paginación), no de detail. El parámetro `limit` del endpoint ya existe para acotar la lista.

### Decisión 3: Sin preview inline de artifacts en v0.2

**Decisión:** `ArtifactList` muestra solo metadata (tipo, path relativo, tamaño humano, sha256 truncado, timestamp). No abre ni descarga el contenido. Cualquier viewer (texto, imagen, JSON) queda para un PR futuro dedicado.

**Motivo:** Instrucción explícita del prompt de PR-10c: "Si requiere más complejidad que eso, NO — solo muestra metadata y queda para futuro PR de viewer." Abrir el contenido exige: (a) un endpoint nuevo que sirva el archivo con content-type correcto, (b) controles de tamaño máximo por tipo, (c) guardas contra path traversal al traducir `path` relativo a la ruta real del host, (d) decisiones sobre caching. Todo eso desborda el scope "read-only quick win" de PR-10c.

**Alternativas consideradas:** Preview solo para text/JSON con límite de 100KB — aún así añade endpoint y manejo de errores; mejor un PR limpio dedicado.

**Impacto:** La UI es estrictamente observacional en v0.2. Un operador que quiera inspeccionar el contenido debe ir al filesystem vía SSH/terminal.

### Decisión 4: `JsonBlock` usa `JSON.stringify(v, null, 2)` — sin dependencia de `react-json-view`

**Decisión:** El pretty-print del payload de eventos en el drawer se implementa con `JSON.stringify(value, null, 2)` dentro de un `<Code block>` de Mantine. No se añade `react-json-view`, `@uiw/react-json-view`, `react-json-pretty` ni ningún paquete equivalente.

**Motivo:** Instrucción explícita del prompt de PR-10c (restricción F): "Esa es la opción correcta para v0.2." Añadir una dependencia nueva para un feature read-only de diagnóstico es desproporcionado — la mayoría de consumidores quiere ver el JSON, no editarlo ni colapsar niveles de forma interactiva. Un bloque monospace con indentación es suficiente.

**Alternativas consideradas:** `@mantine/code-highlight` (ya en el árbol) con `language=json` para colorizar keys/strings — útil pero también requiere importar CSS adicional y añade peso al bundle por un detalle cosmético. Si el feedback de usuarios lo pide, se puede migrar en un PR posterior sin romper el contrato.

**Impacto:** Cero dependencias nuevas en PR-10c. El bloque de payload es funcional y legible aunque no tenga coloreo sintáctico. Futuros PRs pueden reemplazar la implementación de `JsonBlock` manteniendo su interfaz.

### Decisión 5: `Timeline.onItemClick` como prop opcional — extensión retrocompatible

**Decisión:** `shared/components/Timeline.tsx` gana dos props opcionales: `onItemClick?: (item) => void` y `activeItemId?: string | null`. Cuando `onItemClick` está definido, cada fila se renderiza dentro de un `UnstyledButton`. Cuando no, el renderizado es idéntico al de PR-10a (sin click handler, sin cursor pointer). El único consumidor actual (`RunTimeline`) activa la extensión; otros callers hipotéticos seguirían funcionando sin cambios.

**Motivo:** Evitar bifurcar el componente (`ClickableTimeline` vs `Timeline`) y evitar obligar a todos los callers a manejar click events que no les importan. El patrón props opcionales es canónico en Mantine.

**Alternativas consideradas:**
- Crear un componente nuevo `InteractiveTimeline` — duplica 120 líneas para añadir un callback.
- Exponer un `renderItem` prop — flexible pero sobre-ingeniería: el único caso de uso en v0.2 es "abrir detalle".

**Impacto:** El inline payload dentro del timeline pasa a renderizarse con `lineClamp=3` (teaser de 3 líneas en vez de payload completo). La autoridad pasa al drawer. Cambio de UX mínimo — antes el payload ocupaba mucho espacio por evento y obligaba a scroll; ahora cada fila tiene altura predecible y el operador abre el drawer si quiere profundizar.

## 2026-04-14 — PR-10d

### Decisión 1: Nuevo top-level `/settings` con sub-tab "Backends" (opción b)

**Decisión:** Se añade una ruta nueva `/settings` como item top-level "Ajustes" en el AppShell, con Tabs y una sola pestaña en PR-10d ("Backends"). No se incrusta dentro del item "Sistema" existente.

**Motivo:** SystemView (`/system`) es operacional (services, agents, config, routines, logs, styles) — un panel de gobierno de runtime. Los perfiles de backend v0.2 definen política de ejecución (router/adapters/capabilities), conceptualmente distinto. Mezclarlos confundiría la navegación y acoplaría PR-11 (installer) al layout de SystemView. Crear `/settings` con un solo tab inicial prepara terreno para que PR-11 añada paneles propios (assistant mode, install options) sin reestructurar el nav.

**Alternativas consideradas:**
- (a) Nuevo item top-level "Backends" — descartado: no es escalable; PR-11 necesitará más superficie.
- (c) Extender SystemView con una tab "Backends" — mezcla operacional (services, logs) con política (ejecución v0.2). Degrada la legibilidad del nav.

**Impacto:** Router gana una ruta (`/settings`), nav gana un item (shortcut `J`, visual only). `features/settings/` nace como home de futuras superficies de configuración v0.2.

### Decisión 2: `ProjectDetail` añade tab "Capabilities" con state local, no sub-rutas

**Decisión:** La tab "Capabilities" se integra en `ProjectDetail` (`/projects/:slug`) reutilizando el patrón `Tabs` + `activeTab` state que ya usan `overview/tasks/files/uploads`. No se promueve a sub-rutas tipo `/projects/:slug/capabilities` como hace `TaskDetailPage` (PR-10a Dec 1).

**Motivo:** Scope mínimo del PR. Promover `ProjectDetail` a sub-rutas requiere refactor no trivial (layout con `<Outlet />`, hooks de contexto para propagar `project`, migración de callers que usan `activeTab`). PR-10d no es el sitio para abrir ese frente.

**Matiz explícito:** ProjectDetail queda con patrón de tabs por state local en lugar de sub-rutas deep-linkables como TaskDetailPage (PR-10a). Decisión deliberada de no ampliar scope de PR-10d. La inconsistencia de patrón entre las dos vistas de detalle del producto queda pendiente para un PR de unificación UX. Hasta entonces, compartir URL de "capabilities de un proyecto" no lleva directo a la tab — abre ProjectDetail en su tab por defecto ("overview").

**Alternativas consideradas:**
- Promover ProjectDetail a sub-rutas en este PR — rechazado por scope.
- Ruta independiente `/projects/:slug/capabilities` con layout propio — fragmentaría la vista del proyecto y duplicaría header.

**Impacto:** La tab "Capabilities" es el 5º miembro del Tabs. Compartir un permalink del proyecto abre "Resumen" por defecto; el operador hace click en la tab. Unificación pendiente.

### Decisión 3: Edición de JSON con `Textarea` monospace, no extensión de `JsonBlock`

**Decisión:** Los campos JSON editables de `CapabilitiesTab` (`shell_whitelist_json`, `filesystem_scope_json`, `secrets_scope_json`, `resource_budget_json`) se editan en `Textarea` monospace con validación cliente (`JSON.parse`) para bloquear el submit si el texto no parsea. `JsonBlock` permanece como componente read-only y se usa tal cual en `BackendProfileRow` para `capabilities_json`.

**Motivo:** Extender `JsonBlock` a un modo editable introduce acoplamiento entre vista y edición que el componente actual no contempla (necesitaría detección de cambios, estado controlado, onChange, error state). `Textarea` con CSS monospace cumple el requisito sin bifurcar un shared component por un caso concreto.

**Alternativas consideradas:**
- Extender `JsonBlock` a modo editable — escalado en el prompt; el refactor queda desproporcionado para el beneficio.
- Añadir un editor JSON con dependencia npm (p.ej. `@monaco-editor/react`) — viola "no dependencias nuevas" del SPEC.

**Impacto:** `JsonBlock` sigue intacto. La validación de forma (enums, shape) la aplica el backend via `validate_capability_input()`; el frontend solo garantiza que el string pasa `JSON.parse`.

### Decisión 4: Ediciones desde UI "congelan" el `upgrade_codex_profile` — semántica heredada respetada, no re-implementada

**Decisión:** El endpoint `PATCH /api/backend-profiles/:id` no contempla ningún tratamiento especial para `codex`. Al persistir cambios manuales (p.ej. `enabled=0` o `priority=99`), el WHERE condicional de `upgrade_codex_profile()` (`WHERE slug='codex' AND enabled=0 AND priority=0`, PR-07 Dec 4) deja de casar y el upgrade automático se vuelve no-op sobre esa fila. No se añade un flag nuevo ni columna auxiliar.

**Motivo:** La semántica de "respetar la configuración del usuario" ya estaba codificada en PR-07. Replicarla en la capa HTTP introduciría una fuente de verdad duplicada y riesgo de deriva.

**Impacto:** La UI muestra un banner informativo al editar `codex` avisando al operador de que su cambio prevalece frente a futuros upgrades automáticos. El test `test_patch_freezes_codex_upgrade` guarda la invariante.

### Decisión 5: Auditoría a stdout como placeholder — no se crea tabla de auditoría en PR-10d

**Decisión:** Cada edición (PATCH backend_profile o PUT capability_profile) emite una línea de log estructurada `AUDIT <entidad>.<campo> <id>: <old> → <new>` vía `logger.info` / `print(..., flush=True)`. No se crea tabla `audit_log` ni migración asociada.

**Motivo:** PR-10d no exige persistencia auditable y añadir schema ahora obliga a decidir modelo de retención, índices y endpoint de consulta — scope de un PR posterior de observabilidad. Una línea en stdout es suficiente para rastrear cambios en entornos v0.2 (single-node, logs capturados por Docker/systemd).

**Alternativas consideradas:**
- Tabla `audit_log` con migración 012 — rechazado por scope (retention policy, columnas para quién hizo el cambio, endpoint de consulta, etc.).
- Archivo JSON append-only en `var/audit/` — añade I/O sin beneficio frente al stdout capturado por el runtime.

**Deuda documentada:** Un PR futuro de observabilidad debe materializar `audit_log` con:
- Tabla con `id, entity_type, entity_id, field, old_value, new_value, actor, created_at`.
- Migración idempotente.
- Endpoint `GET /api/audit?entity_type=...&entity_id=...`.
- Mover los `logger.info(AUDIT ...)` actuales a `audit_service.record_change()`.

**Impacto:** Operadores revisando cambios de política dependen de logs de contenedor hasta que exista audit_service.

### Decisión 6: `PUT` con upsert para capability-profile, no `PATCH` separado de `POST` create

**Decisión:** `/api/projects/:id/capability-profile` acepta `PUT` con semántica de upsert: si no existe fila, la crea desde `DEFAULT_CAPABILITY_PROFILE` + overrides; si existe, aplica el parche. Un body `{}` en un proyecto sin fila materializa la fila con defaults.

**Motivo:** PR-05 Dec 4: los proyectos sin fila usan `DEFAULT_CAPABILITY_PROFILE` como fallback y cualquier edición tiene que crear la fila primero. Exponer dos endpoints distintos (POST create + PATCH update) obliga al cliente a saber de antemano si la fila existe, duplicando lógica. PUT upsert encapsula ambas transiciones bajo una sola llamada atómica.

**Alternativas consideradas:**
- `POST /api/projects/:id/capability-profile` (create) + `PATCH` (update) — cliente debe consultar estado primero; más round-trips.
- `PATCH` único con auto-create — PATCH implica recurso existente; usar PUT es más honesto con la semántica HTTP.

**Impacto:** UI simplifica a un único hook `useUpdateCapabilityProfile`. El botón "Personalizar para este proyecto" invoca `PUT {}`, que materializa el row. Un empty PUT posterior sobre el mismo proyecto es idempotente (actualiza `updated_at` si hubiera cambios, pero con `{}` no hay SET clauses y queda como no-op).

### Decisión 7: `capabilities_json` y `command_template` son read-only en v0.2

**Decisión:** Se listan dos campos de `backend_profiles` en `UPDATABLE_BACKEND_PROFILE_FIELDS`: `enabled`, `priority`, `default_model`. Los demás campos (`slug`, `display_name`, `backend_kind`, `runtime_kind`, `capabilities_json`, `command_template`) devuelven `unknown_field` al intentar patcharlos.

**Motivo:** Editar `capabilities_json` requiere validación contra el schema que los adapters consumen (resume_modes, fs_modes, shell_modes, etc.) — cualquier desalineación rompería el router en silencio. `command_template` es un formato interno del executor legacy que está siendo migrado fuera del camino por PR-04+. `slug` y los `*_kind` son identidad inmutable del perfil. Mantener todo esto read-only previene que la UI se convierta en vector de corrupción del seed.

**Alternativas consideradas:**
- Exponer `capabilities_json` como texto editable con validación JSON básica — deja pasar errores de shape (claves incorrectas, valores fuera de dominio) que el adapter no tolera.
- Permitir editar `display_name` — trivial pero irrelevante para la semántica; se deja fuera por consistencia (read-only mientras no haya caso de uso).

**Impacto:** La UI expone claramente los campos como read-only con un label "read-only en v0.2". Cualquier ampliación requiere (a) validación de shape en backend, (b) actualizar el frontend para editar. Escalado de scope, no deuda técnica silenciosa.

## 2026-04-14 — PR-10e

### Decisión 1: Borrado completo de `features/chat/` legacy + limpieza de tipos/hooks/store asociados

**Decisión:** Se elimina la totalidad del chat legacy del frontend React: `niwa-app/frontend/src/features/chat/{components,hooks}/*` (ChatView, ChatInput, MessageBubble, useChat re-export). Además se retiran del shared los 5 hooks consumidos únicamente por ChatView (`useChatSessions`, `useChatMessages`, `useCreateChatSession`, `useSendChatMessage`, `useDeleteChatSession` en `shared/api/queries.ts`), los tipos `ChatSession` y `ChatMessage` (`shared/types/index.ts`) y las propiedades `activeChat`/`setActiveChat` del zustand store (`shared/stores/app.ts`). Antes del borrado se auditó con grep que ninguna otra feature consume esos símbolos.

**Motivo:** SPEC PR-10 exige "chat web mínimo sobre assistant_turn". El chat legacy (3-tier Haiku→Opus→Sonnet via `source='chat'` tasks) es incompatible semánticamente con el nuevo tier conversacional (PR-08). Mantener ambos frontends sobre las mismas tablas introduce confusión y duplica estado. Los hooks/tipos compartidos solo tienen un consumidor (ChatView); moverlos o mantenerlos sería código muerto.

**Alternativas consideradas:**
- Mantener el chat legacy en paralelo bajo `/chat-legacy` — rechazado: el SPEC pide un único chat web, y el esfuerzo de mantener dos duplica todo el estado tanto de UI como de queries.
- Conservar los hooks compartidos por si un PR futuro los necesita — rechazado: escalar sin consumidores produce deuda. Cuando un futuro PR necesite persistir chat sessions lo hará bajo el contrato v0.2 (assistant_turn).

**Impacto:** `Router.tsx` pasa a importar `ChatPage` desde `features/chat/components/ChatPage.tsx` (nuevo). El nav de `AppShell` conserva el item "Chat" con path `/chat` sin cambios. El build TypeScript no tiene referencias colgantes tras el borrado.

### Decisión 2: Endpoints HTTP del chat legacy se preservan intactos

**Decisión:** Los endpoints `/api/chat/sessions` (GET/POST), `/api/chat/sessions/:id/messages` (GET), `/api/chat/sessions/:id/delete` (POST) y `/api/chat/send` (POST) en `niwa-app/backend/app.py` se mantienen sin modificación. Las funciones `get_chat_sessions`, `create_chat_session`, `get_chat_messages`, `send_chat_message`, `delete_chat_session` tampoco se tocan.

**Motivo:** Esos endpoints son consumidos por (a) `niwa-app/frontend/static/app.js` (SPA legacy v0.1 servida desde `/static/app.js` a quien abra `/static/index-legacy.html` manualmente; no es el default de producción pero sigue servida por `_serve_static`) y (b) indirectamente por `bin/task-executor.py` via tasks con `source='chat'` (pipeline 3-tier). PR-06 Dec 6 estableció que `routing_mode=legacy` sigue funcional hasta v0.3 y el pipeline v0.1 sigue vivo. Borrarlos rompería usuarios en modo legacy sin aviso.

**Alternativas consideradas:**
- Marcar los endpoints como deprecated con `410 Gone` — rechazado: el pipeline legacy (fuera de scope de PR-10e) los usa.
- Borrarlos asumiendo que nadie los usa — rechazado: instrucción explícita del prompt + riesgo de regresión silenciosa.

**Impacto:** La deuda queda explícita: un PR futuro (probablemente PR que retire `routing_mode=legacy` a la vez que el pipeline v0.1) deberá eliminar los endpoints, las 5 funciones y la lógica de auto-ingest de tareas delegadas en `get_chat_messages` (líneas 931-996 de `app.py`).

### Decisión 3: Nuevo endpoint `GET /api/chat-sessions/:id/messages` separado del legacy

**Decisión:** Se añade un endpoint fresco `GET /api/chat-sessions/:id/messages` en `app.py` que devuelve una lista plana de mensajes (`id, role, content, task_id, created_at`) ordenados por `created_at ASC` para una `chat_sessions.id` dada. 404 si la sesión no existe. El path usa `chat-sessions` (guion) en lugar de `chat/sessions` (slash) precisamente para no colisionar con el legacy ni con el patrón `chat/sessions/:id/messages` que ya hace cosas invasivas (auto-complete de tasks pendientes, auto-inject de mensajes de tareas delegadas).

**Motivo:** El endpoint legacy `GET /api/chat/sessions/:id/messages` no es una lectura pura: ejecuta side effects (ver `get_chat_messages` en `app.py:897-998`). El chat nuevo consume mensajes escritos por `assistant_service._persist_user_message()` y `_persist_assistant_message()` sin needing ningún auto-complete — leer y devolver. Reutilizar el endpoint legacy significaría ejecutar efectos irrelevantes en cada poll y generar mensajes "sistema" fantasma en la conversación v0.2.

**Alternativas consideradas:**
- Extender el endpoint legacy con un query param `?raw=1` que desactive los side effects — rechazado: ensucia el endpoint legacy sin beneficio.
- No crear endpoint y leer directamente `chat_messages` desde el frontend via algún otro mecanismo — imposible, no hay acceso directo a DB desde el browser.

**Impacto:** El nuevo endpoint es ~15 líneas en `app.py` + fila en la tabla de routing del handler. Tests propios en `tests/test_chat_sessions_endpoint.py`.

### Decisión 4: `session_id` generado client-side con `crypto.randomUUID()`

**Decisión:** El chat web genera un `session_id` nuevo al montarse el componente `ChatPage` con `crypto.randomUUID()`. El mismo id se reusa para todos los turns de la conversación. El botón "Nueva conversación" regenera. `assistant_service._ensure_session()` ya crea la fila en `chat_sessions` si el id no existe (ver `assistant_service.py:112-126`), por lo que no se necesita un endpoint explícito de "crear sesión".

**Motivo:** El contrato de `assistant_turn` admite session_id arbitrario; si no existe, se crea. Esto nos permite evitar el round-trip "POST /sessions → usar id devuelto" que forzaba el legacy. Generar client-side simplifica el flujo y permite incluir el `session_id` incluso en la primera llamada (útil si el backend falla y el frontend quiere reintentar con el mismo id).

**Alternativas consideradas:**
- Crear endpoint `POST /api/chat-sessions` y llamar en mount → doble round-trip, UX innecesaria.
- Usar `sessionStorage` para persistir el id entre recargas → scope creep; el SPEC pide "mínimo" y no pide persistencia cross-reload.

**Impacto:** Recargar la página genera una sesión vacía nueva. Para v0.2 es aceptable — el SPEC explícitamente dice "suficiente con un botón 'Nueva conversación' que cree session_id nuevo. No añadas lista de conversaciones pasadas". Si un usuario quiere persistir entre reloads, lo resuelve un PR futuro.

### Decisión 5: Selector de proyecto con pre-selección desde query param `?project=<slug>` + persistencia en `localStorage`

**Decisión:** `ChatPage` carga `useProjects()` y muestra un `Mantine Select` obligatorio. El proyecto pre-seleccionado se resuelve en este orden: (a) query param `?project=<slug>` si presente y válido, (b) último proyecto usado (persistido en `localStorage` con clave `niwa.chat.lastProjectId`), (c) nada (placeholder "Elige un proyecto para empezar" — el input de mensaje queda deshabilitado).

**Motivo:** El prompt pide "Si el usuario viene de /projects/:slug con contexto, pre-seleccionarlo". Un query param cubre ese caso sin necesidad de modificar `ProjectDetail` en este PR. `localStorage` evita al operador elegir el mismo proyecto en cada visita sin introducir backend state. Si ambos faltan, placeholder explícito.

**Alternativas consideradas:**
- Tomar el proyecto del primer item de `useProjects()` — rechazado: silencio semántico, el usuario puede terminar operando sobre el proyecto equivocado sin notarlo.
- Modificar `ProjectDetail` para añadir un botón "Abrir en chat" — scope creep.

**Impacto:** El selector queda visible en el header del `ChatPage`. `localStorage` guarda el último proyecto tras el primer turn exitoso. Ninguna feature existente se toca.

**Caveat (añadido en review):** `niwa.chat.lastProjectId` en localStorage es estado client-side global sin scope de usuario. Válido mientras la instalación sea mono-usuario (v0.2). Cuando v0.3+ introduzca multiusuario en el mismo navegador, el valor debe scoparse por user_id o moverse a server-side.

### Decisión 6: Manejo de errores estructurados en el cliente — `fetch` crudo en lugar de `apiPost`

**Decisión:** El hook `useChat` no usa `apiPost()` de `shared/api/client.ts` para el turn del assistant. Usa `fetch()` directo para capturar el body completo (incluye `error`, `message`, `session_id`) incluso en respuestas 4xx/5xx. `apiPost()` lanza `ApiError` que preserva el status pero descarta el `message` humano estructurado.

**Motivo:** El contrato PR-08 devuelve JSON bien formado tanto en 200 como en 400/409 (ver `app.py:3917-3920`). La UI necesita el `message` para distinguir `routing_mode_mismatch` (HTTP 409 → banner claro a /settings), `project_not_found`, `llm_not_configured`, `empty_message`, etc. Cada error estructurado se mapea a un mensaje UI específico; para errores no estructurados (red, 500 sin body) se muestra un error genérico con el status.

**Alternativas consideradas:**
- Parsear `ApiError.message` (que contiene `body.error`) — rechazado: perdemos el `message` humano del backend.
- Modificar `apiPost()` para devolver body completo en errores — rechazado: cambia contrato de todos los callers existentes, fuera de scope.

**Impacto:** `useChat.ts` contiene la lógica de fetch directo (~30 líneas). Los demás hooks del chat (`useSessionMessages` para cargar historial al mount) sí usan `api()` normal porque esas rutas devuelven 200 o lanzan 404 sin body rico.

**Caveat (añadido en review):** Esta excepción al patrón `apiPost` aplica exclusivamente a endpoints con contrato de error estructurado específico como `assistant_turn` (body con `{error, message}` a preservar). El resto de endpoints sigue usando `apiPost`. Si otra feature necesita fetch crudo, re-evaluar caso a caso — no asumir que "assistant_turn lo hace así" es precedente.

### Decisión 7: Registro visual editorial — sin bubbles, sin avatares, sin timestamps absolutos

**Decisión:** `TurnView` renderiza cada turn como un bloque textual separado por border-hairline, con (a) el mensaje del usuario en texto plano con prefijo sutil "Tú", (b) la respuesta del assistant en texto plano con prefijo sutil "Niwa", (c) si el turn tiene `actions_taken` no vacío, una fila de chips/badges con los IDs clicables, (d) `RelativeTime` al lado del prefijo con tooltip al timestamp absoluto. Mantine colors por defecto (`dimmed` para metadata). Nada de `Paper` con fondo de color, nada de `Avatar`, nada de burbujas.

**Motivo:** El prompt prohíbe explícitamente el patrón ChatGPT-style. Linear/Raycast/Cursor hacen exactamente esto: texto denso, border-hairline, sin avatares. Es el registro editorial que el resto del producto (dashboard, lists) ya usa.

**Alternativas consideradas:** N/A — decisión estética explícita del prompt.

**Impacto:** El código es más simple (no hay cálculos de `justifyContent`, no hay theming de burbujas). El `ReactMarkdown` previamente usado en `MessageBubble` no se reusa: se muestra texto plano con `white-space: pre-wrap` (el contenido de `assistant_message` es texto plano per PR-08). `react-markdown` y `remark-gfm` siguen en package.json porque `NoteEditor` los usa.

### Decisión 8: Linkificación de IDs mencionados — regex propia en un helper compartido

**Decisión:** Se crea `niwa-app/frontend/src/shared/components/LinkifiedText.tsx` que toma un string y emite spans con `Link` a `/tasks/:id`, `/approvals/:id` según patrón. El regex detecta UUIDs con contexto (prefijos "tarea", "task", "approval", etc.) en el texto del `assistant_message`, y además procesa los IDs exactos de `actions_taken.task_ids`, `approval_ids`, `run_ids` como chips separados bajo el mensaje. La navegación usa `useNavigate` de react-router.

**Motivo:** El prompt prohíbe introducir dependencias nuevas (react-markdown para linkificación es overkill; regex propia suficiente). El helper queda en `shared/` para reutilizarlo en PRs futuros si algún otro lugar necesita linkificar menciones.

**Alternativas consideradas:**
- Sólo renderizar chips de `actions_taken.*_ids` (sin scanear el texto) — más simple pero pierde referencias que el LLM hace en prosa. Compromiso: los chips son la fuente canónica; el escaneo del texto es bonus.
- Usar `react-markdown` con renderers custom — rechazado por peso y porque el texto no es markdown.

**Impacto:** `LinkifiedText` es ~40 líneas. Los chips de IDs canónicos (`task_ids`, `run_ids`, `approval_ids` devueltos por `actions_taken`) se renderizan en `TurnView` como lista horizontal con `MonoId` + icono de navegación. `run_ids` navegan a `/tasks/:taskId/runs` si hay task_id asociado — si no, a `/tasks` (run_id sin task_id es raro en este contrato; el assistant casi siempre devuelve tasks y runs juntos).

## 2026-04-14 — PR-11

### Decisión 1: Pin de `docker/mcp-gateway` a `v0.40.4` via `NIWA_MCP_GATEWAY_IMAGE`

**Decisión:** `docker-compose.yml.tmpl` sustituye `docker/mcp-gateway:latest` por la variable `${NIWA_MCP_GATEWAY_IMAGE}` en las dos ocurrencias (servicios `mcp-gateway` y `mcp-gateway-sse`, líneas 49 y 89 antes del cambio). `setup.py` declara `NIWA_MCP_GATEWAY_IMAGE_DEFAULT = "docker/mcp-gateway:v0.40.4"` y `execute_install()` usa ese valor salvo que el operador exporte `NIWA_MCP_GATEWAY_IMAGE` en el entorno antes del install.

**Motivo:** PR-09 Decisión 6 defirió el pin a PR-11 porque pinnear sin validar un tag existente rompía installs. En 2026-04-14 la consulta a Docker Hub devuelve `v0.40.4` como release estable más reciente (semver, multi-arch `linux/amd64` + `linux/arm64`, publicada hace 5 días). Usar `v0.40.4` en lugar de un tag mayor (`v2`) mantiene el determinismo exigido por el SPEC PR-11 ("Imágenes Docker pinneadas, no `latest` en quick mode"). La variable permite ascender sin parchar el template.

**Alternativas consideradas:** (a) Usar `v2` (tag mayor) — rechazado porque sigue siendo rolling dentro del mayor, el SPEC pide pin fijo. (b) Omitir la variable y hardcodear `v0.40.4` — rechazado porque operadores que necesiten un pin distinto tendrían que editar el template generado, lo cual el comentario del template prohíbe explícitamente. (c) Dejar `:latest` — violación directa del SPEC.

**Impacto:** `secrets/mcp.env` gana la clave `NIWA_MCP_GATEWAY_IMAGE`. Installs existentes que regeneren el compose (via `niwa install` o `niwa update`) empezarán a usar el tag pinneado. README y compose template reflejan el pin. Cuando Docker publique una versión estable nueva, actualizar `NIWA_MCP_GATEWAY_IMAGE_DEFAULT` en `setup.py` (un solo sitio).

### Decisión 2: `generate_catalog_yaml(contract_file=...)` sobrescribe, no intersecta

**Decisión:** Cuando se pasa un contract file a `generate_catalog_yaml`, el listado de tools expuesto por el catálogo pasa a ser **exactamente** `contract["tools"]`, no la intersección con las tools descubiertas en `config/mcp-catalog/*.json`. La lógica anterior (intersección) se eliminó porque descartaba las 11 tools v02 (`assistant_turn`, `task_cancel`, `task_resume`, `approval_list`, `approval_respond`, `run_tail`, `run_explain`, `project_context`, …) que no viven en los catálogos v0.1.

**Motivo:** Los catálogos v0.1 (`config/mcp-catalog/niwa-core.json` y hermanos) y el contract v02 (`config/mcp-contract/v02-assistant.json`) son dos mecanismos distintos que conviven:
  - Los catálogos v0.1 enumeran las 21 tools legacy que implementa `servers/tasks-mcp/server.py::_LEGACY_TOOL_DEFS`. Se siguen usando en modo core (sin contract env) y por el pipeline legacy `routing_mode=legacy`.
  - El contract v02 lista las 11 tools conversacionales expuestas en modo assistant. Esas tools viven sólo en `_V02_TOOL_DEFS` del mismo server y se implementan como proxy HTTP a `/api/assistant/turn` y `/api/assistant/tools/{name}` (PR-09 Dec 1).
  - En modo assistant el gateway filtra por el contract y expone sólo las 11 tools v02. En modo core, usa los catálogos v0.1 y expone las 21.
  - El doble filtro — catálogo a nivel gateway + `NIWA_MCP_CONTRACT` a nivel server — es deliberado: el gateway decide qué tools publicita en `tools/list` (por el catálogo) y el server decide qué tools implementa (por el env var). Ambas capas deben coincidir o el cliente ve tools que el server rechaza (o al revés). Usar `contract["tools"]` como fuente autoritativa a nivel catálogo alinea los dos filtros.

**Alternativas consideradas:**
- (a) Añadir las tools v02 a algún archivo `config/mcp-catalog/*.json` → contaminaría el inventario legacy con tools v02 que el pipeline v0.1 no conoce.
- (b) Mantener la intersección y requerir que los callers manden primero las v02 en un catálogo sombra → scope creep, mecanismo paralelo sin beneficio.

**Impacto:** `generate_catalog_yaml` tiene un único camino autoritativo cuando hay contract: `contract["tools"]`. Callers legacy (sin contract) siguen funcionando igual. El test `TestCatalogGeneration::test_contract_overrides_to_contract_tools` guarda la invariante.

### Decisión 3: Idempotencia del quick install — abort defensivo en cambio de modo

**Decisión:** `install --quick --mode X` sobre un workspace ya instalado se comporta según tres reglas:

  (a) **Mismo modo (core→core, assistant→assistant):** procede como update-in-place. El schema es idempotente (`CREATE TABLE IF NOT EXISTS`, `INSERT OR IGNORE`), `docker compose up -d` reemplaza contenedores sin perder el volumen de datos, `secrets/mcp.env` se reescribe con **tokens y admin password nuevos**. Se emite un `warn()` antes del install explicando la rotación. Los clientes MCP previamente registrados (Claude, OpenClaw) necesitarán reaceptar el nuevo token — su entry en `openclaw.json` se actualiza en el mismo run si procede.

  (b) **Cambio de modo (core↔assistant):** **aborta** con exit code `2` y un mensaje explicando las tres salidas posibles: (1) repetir con el modo existente, (2) pasar `--force` para sobrescribir, (3) desinstalar primero. Sin `--force`, jamás se sobrescribe silenciosamente.

  (c) **Fresh install (no hay `secrets/mcp.env`):** procede normalmente.

La detección del modo actual la hace `detect_existing_quick_mode(niwa_home)` leyendo `NIWA_MCP_CONTRACT` en `secrets/mcp.env`. Si vale `v02-assistant` es assistant; cualquier otro valor (incluyendo vacío o ausente) se trata como core.

**Motivo:** La regla C del prompt PR-11 exige "detectar y abortar cuando los modos no coinciden; `--force` para sobrescribir". Una instalación core sobre un workspace assistant (o viceversa) implica cambios no reversibles por la vía de update-in-place: `openclaw mcp set` ya dejó estado en `~/.config/openclaw/openclaw.json` que un install core no sabe limpiar; un install assistant sobre workspace core sí puede registrar el endpoint sin perder nada. El abort defensivo protege al operador del primer caso sin complicar el segundo — ambos requieren consentimiento explícito.

**Alternativas consideradas:**
- (a) Sobreescribir siempre (comportamiento previo) — riesgo de perder estado assistant sin aviso al reinstalar en core.
- (b) Implementar un wizard de migración (core→assistant incluye registro OpenClaw; assistant→core desinstala el skill) — scope creep para PR-11; `--force` es la válvula mínima viable.
- (c) Permitir el cambio de modo sin `--force` pero requerir `-y` en ausencia de `--yes` → redundante con la regla actual de `-y`.

**Impacto:** El flag `--force` sólo existe en `install --quick`. `install` interactivo clásico sigue igual. `INSTALL.md` documenta los tres escenarios. Tests cubren la detección y los tres caminos (mismo modo, cambio bloqueado, cambio forzado).


---

## 2026-04-14 — PR-12

### Decisión 1: PR-12 no añade cobertura nueva

**Decisión:** el checklist del SPEC PR-12 (16 ítems) ya estaba cubierto por los PRs 01-11, que escribieron sus propios tests en el mismo PR que la feature. PR-12 no escribe tests nuevos para los ítems ya cubiertos; en su lugar documenta la trazabilidad item↔test en `docs/TEST-AUDIT-PR12.md` (§2) y se limita a (a) borrar tests legacy que el SPEC declara inservibles, (b) cerrar los dos bugs conocidos (12, 13) que dejaban cobertura existente fallando en full-suite.

**Motivo:** la regla "tests junto a la feature" del SPEC §8 se cumplió. Escribir tests-espejo con nombres literales del checklist añadiría redundancia sin subir confianza real. El audit trail sirve como índice — ante una lectura del SPEC, cada ítem apunta a archivo::clase::método concreto.

**Alternativas consideradas:**
- (a) Añadir un test-espejo por ítem del checklist con nombre literal (p. ej. `test_backend_run_created_on_claim`) — rechazado: duplica `TestV02PipelineCreatesRun::test_full_pipeline` con otro nombre, no añade señal.
- (b) Reescribir toda la suite alrededor de las 16 áreas — rechazado: borraría 800+ tests que ya están bien organizados por PR y por servicio.

**Impacto:** el audit trail queda como entrada única cuando alguien pregunte "¿dónde se testa el ítem N del checklist PR-12?". Si un ítem pierde cobertura en el futuro, actualizar la tabla es obligatorio.

### Decisión 2: el smoke catálogo↔server en `test_smoke.py` excluye tools v02

**Decisión:** `tests/test_smoke.py::TestSuperficieMCP::test_herramientas_catalogo_coinciden_con_servidor` y `tests/test_smoke.py::TestMCPCatalogIntegrity::test_catalog_yaml_matches_server` filtran las tools v02-exclusivas (`assistant_turn`, `task_cancel`, `task_resume`, `approval_list`, `approval_respond`, `run_tail`, `run_explain`) antes de comparar con los catálogos `config/mcp-catalog/*.json`. Las tools compartidas entre `_V02_TOOL_DEFS` y `_LEGACY_TOOL_DEFS` (como `task_list`, `task_get`, `task_create`, `project_context`) siguen validándose.

**Motivo:** los catálogos v01 y el contract v02 son dos mecanismos distintos que conviven. Los catálogos enumeran las tools legacy del dispatcher `_LEGACY_TOOL_DEFS`; las tools v02-exclusivas viven en `config/mcp-contract/v02-assistant.json` y el gateway las filtra por contract (PR-09 Decisión 3, PR-11 Decisión 2). El smoke catálogo↔server debía reflejar ese split. No se toca `config/mcp-catalog/` ni se añaden tools v02 a los catálogos — la fuente autoritativa del contract es `tests/test_mcp_contract.py::TestV02AssistantContractShape`.

**Alternativas consideradas:**
- (a) Añadir un `config/mcp-catalog/niwa-v02.json` con las tools v02 — rechazado por PR-09 Dec 1 y PR-11 Dec 2 (contaminaría el inventario legacy con tools que `_LEGACY_TOOL_DEFS` no conoce, rompiendo la invariante `catalog ↔ dispatcher`).
- (b) Borrar estos dos tests y delegar en `test_mcp_contract.py` — rechazado: sigue siendo valioso tener un smoke rápido que detecte divergencias entre los catálogos legacy y su implementación en el server, independientemente del contract v02.

**Impacto:** el helper `_load_v02_tool_names` en `test_smoke.py` parsea el source de `servers/tasks-mcp/server.py` para localizar `_V02_TOOL_DEFS` y `_LEGACY_TOOL_DEFS` por nombre de símbolo. Si algún día se renombran, el test debe actualizarse — no hay otra vía sin añadir dependencias en tiempo de test.

### Decisión 3: tests frontend de árbol estático de componentes salen de la suite

**Decisión:** se eliminan `tests/test_smoke.py::TestFrontendBuild::test_all_react_components_exist` y `tests/test_smoke.py::TestImageGeneration::test_chat_renders_images`. La comprobación de "qué componentes React existen" pasa a apoyarse en `npm run build` del CI. Cualquier cobertura UI futura queda diferida al PR de infra de tests de frontend (ver PR-10a Decisión 2).

**Motivo:** PR-10e borró el chat web v0.1 (con él `ChatView.tsx`, `MessageBubble.tsx`), y PR-10 añadió rutas nuevas (`features/runs`, `features/routing`, `features/approvals`, `features/artifacts`, `features/settings`). Mantener una lista hardcodeada de rutas en un test Python es trabajo manual recurrente que no detecta regresiones reales — la verdad la dice el build.

**Alternativas consideradas:**
- (a) Actualizar la lista con las rutas v0.2 — rechazado: seguiríamos con el mismo problema estructural la próxima vez que se mueva un componente.
- (b) Reemplazarlo por un walk recursivo de `src/features/*/components/*.tsx` como regresión de vida-mínima — fuera de scope (no es el rol de PR-12).

**Impacto:** el test de lista estática deja de existir. El dev que mueva componentes no ve fallos espurios en `pytest tests/`; en su lugar se apoya en `npm run build` (CI frontend).

### Decisión 4: borrado de `tests/test_e2e.py` sin sustituto aquí

**Decisión:** `tests/test_e2e.py` se elimina por completo (Bug 5 en BUGS-FOUND.md). No se escribe un E2E nuevo en PR-12.

**Motivo:** el test dependía de (a) `assigned_to_claude=1` (campo deprecado en PR-00) y (b) la BD `~/.niwa/data/niwa.sqlite3` (ruta de producción). Ambos son pre-v0.2. El contrato equivalente en v0.2 — "un claim real crea un `backend_run`" — ya está cubierto por `tests/test_task_executor_routing.py::TestV02PipelineCreatesRun::test_full_pipeline`, que monta su propia BD temporal y no depende de un proceso externo.

**Alternativas consideradas:**
- (a) Reescribirlo para que spawnee el executor v0.2 y espere a ver un `backend_run` creado — rechazado: E2Es reales con el executor requieren un binario de Claude/Codex en PATH o mocks intrusivos que ya hacemos en `test_claude_adapter_integration.py` con `fake_claude.py`.
- (b) Dejarlo marcado como `@pytest.mark.skip` con referencia a Bug 5 — rechazado: el SPEC PR-12 dice literalmente "no sirven para v0.2", un skip prolonga ruido.

**Impacto:** un renglón menos en la suite, ningún hueco de cobertura.

## 2026-04-15 — PR-25

### Decisión 1: criterio de "healthy" post-`systemctl enable --now` es estricto

**Decisión:** el installer considera un servicio `healthy` si y sólo si, tras esperar **15 segundos**, `systemctl is-active` devuelve exactamente `"active"` Y `systemctl show --property=NRestarts` devuelve `0`. Cualquier otra combinación (`failed`, `activating`, `inactive`, o `NRestarts >= 1`) aborta el install con `sys.exit(1)` y dump de `journalctl -u <unit> -n 20`.

**Motivo:** Bug 18b (`docs/BUGS-FOUND.md`) — PR-23 arregló el crash-loop del executor por ownership del log, pero el installer siguió reportando "Enabled and started" mientras el servicio llevaba 830+ restarts. La mentira duró horas en producción. El criterio estricto invierte el default: en vez de "silent pass", `fail loud`. Cualquier restart durante los 15s post-install en un entorno limpio es pathológico por definición — el happy path es `NRestarts == 0`, no "NRestarts subió poco".

**Alternativas consideradas:**
- (a) `NRestarts <= 1` como tolerancia — rechazado: enmascara exactamente la clase de fallo que Bug 18b estaba diseñado para detectar.
- (b) Wait shorter (5s) — rechazado: el `RestartSec=10` del unit significa que un crash-loop puede no haber completado siquiera su primer restart a 5s; 15s cubre al menos un ciclo completo.
- (c) Wait más largo (30-60s) — rechazado: 15s es tiempo suficiente para detectar crash loops y mantiene el coste del install bajo. Añadimos 30s en total al install (executor + hosting) — aceptable, una vez por install.

**Impacto:** cada install paga +30s (15s × 2 servicios) vs. el flujo previo. Ningún usuario volverá a terminar un install con "éxito" y el executor en restart loop.

### Decisión 2: `systemctl reset-failed` antes de cada `enable --now` (no baseline-delta)

**Decisión:** justo antes de cada `systemctl enable --now`, el installer llama `systemctl [--user] reset-failed <unit>` (best-effort, errores tragados). El contador `NRestarts` usado en la comprobación post-install es el absoluto reportado por `systemctl show`, no un delta contra un baseline leído antes.

**Motivo:** un reinstall sobre una unidad previamente crasheada (escenario real del VPS actual donde PR-23/24 se aplicaron encima de 830 restarts) tendría `NRestarts > 0` de historia antigua, disparando un falso positivo en el health check nuevo. `reset-failed` resetea el contador dentro de systemd de forma atómica y con semántica clara.

**Alternativas consideradas:**
- (a) Leer `NRestarts` baseline antes de `enable --now` y comparar delta tras 15s — rechazado: más código, más condiciones de borde (¿qué pasa si el unit file no existía todavía? ¿si `show` devuelve error?), mismo resultado funcional.
- (b) No resetear y vivir con el falso positivo en reinstalls — rechazado: un reinstall que aborta correcto-pero-falso pone al usuario a debuggear problemas que ya no existen.

**Impacto:** el `reset-failed` es best-effort — si la unidad no existe (fresh install, primer run), devuelve error silencioso y el flow sigue. Si existe y estaba failed, la limpieza ocurre. Uso trivial, una línea de riesgo cero.

### Decisión 3: helpers en `setup.py` siguen siendo stdlib-only, inyectables en tests

**Decisión:** los tres helpers nuevos (`_wait_for_service_stable`, `_verify_service_or_abort`, `_reset_failed_unit`) viven dentro de `setup.py` y exponen `sleep` y `runner` como parámetros kwargs con defaults `time.sleep` y `subprocess.run`. Tests los sobrescriben con `lambda _: None` y un fake runner que replaya respuestas canned.

**Motivo:** el SPEC §8 obliga a stdlib-only en el backend — esa regla aplica al installer también, que se ejecuta antes de que el proyecto pueda instalar nada. Ningún `unittest.mock`, ningún `pytest-subprocess`, ningún decorator externo. La inyección explícita mantiene el coste del test en ~0.11s para las 18 pruebas.

**Alternativas consideradas:**
- (a) Extraer los helpers a `niwa-app/backend/` — rechazado: el installer corre antes de que el backend exista; además crearía una dependencia circular innecesaria entre setup y runtime.
- (b) Tests integracionales con systemd real vía Docker — rechazado: fuera del scope de un fix quirúrgico; aumenta el coste de CI de forma desproporcionada al bug que estamos resolviendo.

**Impacto:** los helpers son puros, el 15s real sólo corre en producción (o si alguien invoca el código sin inyectar `sleep`), y la suite entera de PR-25 corre en <0.2s.

## 2026-04-15 — PR-26

### Decisión 1: hosting binary se copia a `/home/niwa/.<instance>/bin/`, no se intenta abrir `/root/` al niwa user

**Decisión:** `install_hosting_server`, cuando corre como root, replica el patrón pre-existente de `_install_systemd_unit` (executor) y copia `hosting-server.py` a `/home/niwa/.<instance>/bin/hosting-server.py` antes de baker el `ExecStart` del unit. El path swap es explícito: `dest = niwa_hosting_dest` antes del template del unit.

**Motivo:** `cfg.niwa_home` cuando el installer corre con `sudo` resuelve a `/root/.<instance>` (HOME del invoker, no del target user). El unit corre como `User=niwa` y `/root/` es `drwx------` por distro policy — niwa no puede ni siquiera hacer `stat()`, y python3 sale con exit 2 antes de parsear el archivo. El executor ya resolvía esto; que hosting no lo hiciera fue un Chesterton's fence asimétrico.

**Alternativas consideradas:**
- (a) Cambiar los permisos de `/root/` para que niwa pueda leer — rechazado: violación grave de la política estándar del sistema, amplia attack surface, rompe políticas de seguridad estándar de distros.
- (b) Hacer que `cfg.niwa_home` apunte directamente a `/home/niwa/...` cuando running-as-root desde el principio — rechazado: cambio invasivo que afecta a docenas de call-sites distintos; el swap local dentro de `install_hosting_server` es quirúrgico y preserva la semántica existente de "el install root es donde el invoker vive, los artefactos runtime migran al target user".
- (c) Extraer un helper `_get_niwa_runtime_home(cfg)` compartido entre executor y hosting — tentador pero out-of-scope para PR-26. Candidato para un PR de refactor cuando haya un tercer call-site.

**Impacto:** fix quirúrgico, +20 LOC en `install_hosting_server`. El executor queda intacto. Tests regex pin-ean el orden: copy → chown → `dest = ...` → unit template.

### Decisión 2: pre-crear `hosting.log` aunque hosting-server.py no abra el fichero hoy

**Decisión:** PR-26 también añade `hosting_log.touch(exist_ok=True)` + `chown niwa:niwa hosting_log` antes del `systemctl enable --now` para el hosting service. Mirror exacto de lo que PR-23 hizo para el executor.

**Motivo:** sub-bug 18a de `docs/BUGS-FOUND.md` estaba documentado como latente: "no crashea hoy porque `hosting-server.py` usa `print()` y hereda el fd de systemd; cualquier logger Python-level futuro reproducirá Bug 18". Pre-crearlo ahora cierra la puerta definitivamente y cuesta dos líneas. Defense-in-depth por la ley del cheapest-win-wins.

**Alternativas consideradas:**
- (a) Esperar al primer logger Python-level real antes de pagar el coste — rechazado: el coste del "fix preventivo" son dos líneas; el coste del bug real sería otro crash-loop silencioso (el health check de PR-25 lo detectaría pero el install abortaría, no queremos llegar ahí).
- (b) Extraer el patrón "pre-create log + chown" a un helper — declinado: dos call-sites, no hay presión de duplicación; esperar a un tercer servicio antes de refactorizar.

**Impacto:** cierra parcialmente sub-bug 18a (el patrón estructural queda cubierto; el detector de PR-25 cubre el resto). +3 LOC.

### Decisión 3: `chown -R` del hosting_projects_dir para writes de runtime

**Decisión:** `hosting_projects_dir = /opt/<instance>/data/projects` recibe un `chown -R niwa:niwa` explícito en `install_hosting_server`. Técnicamente el executor-install ya hace `chown -R niwa:niwa /opt/<instance>` antes, pero ese chown ocurre en `_install_systemd_unit` y se aplica sobre el árbol existente en ese momento; `hosting_projects_dir` se crea DESPUÉS (en `install_hosting_server`) y sin este chown quedaría con ownership `root:root`.

**Motivo:** el hosting server escribe bundles de proyectos bajo ese directorio. Sin el chown, el primer intento de escritura tras el install falla con `PermissionError` — no crash-loop (el servicio arranca OK) pero el feature principal del hosting no funciona, y el fallo aparece en runtime, no en el install. Anti-patrón "fail late and confusing".

**Alternativas consideradas:**
- (a) Reordenar el install para que `hosting_projects_dir.mkdir()` ocurra antes del `chown -R` del executor — rechazado: acopla dos funciones que deberían estar desacopladas; el `install_hosting_server` debe ser autocontenido respecto a los permisos de lo que crea.
- (b) Crear el directorio con `os.makedirs(mode=0o777)` — rechazado: permisos world-writable son un olor a suciedad; ownership correcto es mejor que permisos permisivos.

**Impacto:** +3 LOC, chown targeted, semántica clara.

## 2026-04-15 — PR-27

### Decisión 1: aceptar tres copias de `niwa-app/backend/` (repo + container + host runtime)

**Decisión:** el installer copia el árbol `niwa-app/backend/` desde el repo a una ubicación niwa-readable (`/opt/<instance>/niwa-app/backend/` en root mode, `cfg.niwa_home/niwa-app/backend/` en user mode). El executor en el host importa de esa copia vía `NIWA_BACKEND_DIR` env var. Resultado: tres réplicas del mismo código en disco — repo source-of-truth, container Docker build (`COPY niwa-app/backend /app/niwa-app/backend`), host runtime (PR-27).

**Motivo:** el executor corre en el host, fuera de Docker, y necesita los módulos `routing_service`, `runs_service`, `backend_adapters/*` para ejecutar la ruta v0.2. Las alternativas estructuralmente "más limpias" (un solo árbol compartido) requieren cambios significativos:

- **Symlink `/opt/<instance>/niwa-app/backend → <repo>/niwa-app/backend`**: rechazado. El repo vive bajo `/root/.niwa/` (mode 0700) que niwa no puede atravesar. Cambiar permisos de `/root/` viola política estándar de distros y abre attack surface.
- **Mover los módulos a un paquete separado importable** (`niwa-app/common/` o pip-installable): refactor mayor, fuera del scope quirúrgico. Cambiaría ~30 imports en ~15 archivos. Candidato para v0.3 si el coste de mantener tres copias se vuelve real.
- **Que el executor delegue al container vía HTTP/socket**: cambia el modelo de ejecución completo, requiere endpoints nuevos en el container, latencia extra. Out of scope.

**Coste real de las tres copias:** 686 KB en disco × 2 (container + host install). Sincronización: el installer recopia desde el repo en cada `niwa install`. Si alguien edita los módulos del backend post-install sin reinstalar, las copias divergen — pero ése es el caso de uso de "modificar código en prod sin redeploy" que ya está mal por otros motivos. Documentado.

**Alternativas consideradas y rechazadas:**
- (a) Container-only execution del routing v0.2 (executor delega al container) — out of scope.
- (b) Refactor a paquete instalable pip — out of scope, requiere ~50% más LOC.
- (c) Symlink al repo — bloqueado por permisos `/root/`.

**Impacto:** PR-27 +50 LOC en setup.py, +20 LOC en task-executor.py, +200 LOC tests. Tres copias documentadas.

### Decisión 2: env var (`NIWA_BACKEND_DIR`) sobre auto-discovery

**Decisión:** el executor prefiere `os.environ["NIWA_BACKEND_DIR"]` sobre la resolución relativa al `__file__`. El installer setea esa env var explícitamente en el systemd unit.

**Motivo:** la resolución relativa al `__file__` es **silenciosa cuando rompe** — `Path(...) / "niwa-app" / "backend"` siempre devuelve un path object, viva o no exista el directorio. `sys.path.insert(path_inexistente)` no falla. El error sólo aparece luego al `import routing_service`, semánticamente desconectado del problema real. Una env var explícita en el unit es:

1. **Auditable:** `cat /etc/systemd/system/niwa-niwa-executor.service` muestra exactamente qué path se está usando.
2. **Operacional:** un operador puede sobrescribir vía `systemctl edit niwa-niwa-executor.service` sin tocar código.
3. **Forzable:** si el operador setea `NIWA_BACKEND_DIR=/foo/bar` y `/foo/bar` no existe, el executor sale loudly con exit 2 + mensaje claro (ver Decisión 3) en lugar de silencioso fallback.

**Alternativas consideradas:**
- (a) Auto-discovery walk: el executor sube por el filesystem buscando `niwa-app/backend/` — rechazado por implícito y frágil. Si hay dos checkouts de Niwa el orden de descubrimiento es ambiguo.
- (b) Hardcode `/opt/<instance>/niwa-app/backend/` en el executor — rechazado por acoplar al installer y romper el dev mode (repo checkout).
- (c) Solo env var sin fallback relativo — rechazado por romper el dev/CI mode.

**Impacto:** dos líneas de cambio en `task-executor.py`. Cero cambio en el dev mode (relative path resolves correctly when running from a repo checkout).

### Decisión 3: fail-loud (sys.exit(2)) si `_BACKEND_DIR` no existe — complementario al health check de PR-25

**Decisión:** si `_BACKEND_DIR` no existe, el executor imprime un mensaje FATAL multiline a stderr (incluyendo guía dev y guía install) y `sys.exit(2)`. No hay fallback "ignora v0.2 y corre sólo legacy".

**Motivo:** el bug 20 sobrevivió meses precisamente porque había un fallback silencioso. PR-25 introdujo "fail loud post-enable" en el installer; PR-27 extiende el principio al runtime del executor. Si el backend tree no se copió (bug en setup.py), el executor crashea, systemd `Restart=always` reintenta, `NRestarts > 0` tras 15s dispara el aborto del install con journal tail visible. La cadena PR-25 + PR-27 garantiza que CUALQUIER misconfiguración de `NIWA_BACKEND_DIR` sea visible en el momento del install, no escondida durante meses.

**Alternativas consideradas:**
- (a) Warning + fallback automático a tier-3 — rechazado: replica exactamente el patrón que ocultó Bug 20.
- (b) Fail loud sólo si `routing_mode=v02` — rechazado: el executor no sabe el routing_mode hasta que lee la DB, que ocurre después del bloque de imports.
- (c) Fail loud silencioso (sys.exit(2) sin mensaje) — rechazado: el operador necesita el mensaje para diagnosticar; el coste de imprimir 7 líneas a stderr es trivial.

**Mensaje multiline incluye:**
- Path concreto que falló (`{_BACKEND_DIR}`).
- Guía dev: "keep bin/task-executor.py peer of niwa-app/backend/".
- Guía operacional: "set NIWA_BACKEND_DIR in the unit's Environment= to /opt/<instance>/niwa-app/backend".

**Impacto:** un escenario nuevo en el que el executor exitea (backend dir missing) que antes era silencioso. Cubierto por test directo + complementado por PR-25 desde el installer.

### Decisión 4: aceptar el riesgo de la lluvia de follow-ups post-PR-27

**Decisión:** PR-27 fixea el import. Una vez merged, la ruta v0.2 ejecutará por primera vez en producción. Asumimos que aflorarán bugs nuevos que estaban ocultos por el fallback a tier-3 (faltan profiles seed, transiciones de state machine no probadas, paths de artifacts no existentes, etc.). No los pre-arreglamos especulativamente — esperamos a que aparezcan en el smoke real del VPS y los atacamos uno a uno.

**Motivo:** especular desde aquí qué va a romper es ineficiente — la ruta v0.2 tiene meses sin ejecutarse, no sabemos qué supuesto hace cada módulo sobre el contexto runtime. Mejor pagar el coste real del descubrimiento que el coste especulativo de pre-fixearlo.

**Alternativas consideradas:**
- (a) Pre-fix de "todos los problemas conocidos" antes de merge — rechazado: no sabemos cuáles son los problemas reales, sólo hipótesis. Pre-fixearlos genera código adivinatorio.
- (b) PR-27 "shadow mode" donde v0.2 se ejecuta en paralelo a tier-3 sin afectar el outcome — tentador para reducir riesgo, pero +50% código y nunca llegamos a ejercer la ruta para detectar bugs reales. Rechazado.

**Mitigación operacional:** después del merge, Claude-VPS ejecuta el smoke end-to-end y reporta CUALQUIER trace de error en los logs del executor. Cada bug nuevo se documenta en BUGS-FOUND con severidad y se ataca como PR aparte.

**Impacto:** PR-27 abre una superficie que llevaba meses inactiva. Expectativa realista: 1-3 follow-up PRs durante 1-2 días post-merge para estabilización.

## 2026-04-15 — PR-28

### Decisión 1: `_quick_free_port` recibe un set de reservas explícito en vez de tener estado global

**Decisión:** `_quick_free_port` añade un parámetro opcional `reserved: Optional[set]`. El wizard (`build_quick_config`) crea un `_reserved_ports: set = set()` local, lo pasa a cada llamada y lo amplía tras cada retorno. La función no mantiene estado a nivel de módulo.

**Motivo:** la causa raíz de Bug 22 era que el helper sólo consultaba el SO (`detect_port_free`) y el SO no sabe que un port "ya asignado" por una llamada previa de la misma sesión está esperando bind. Un set externo que el wizard threadea es la solución más simple y mantiene el helper sin estado global. Estado global → tests con setup/teardown frágiles + bugs cuando hay múltiples wizards paralelos (que no es nuestro caso pero marca la dirección correcta).

**Alternativas consideradas:**
- (a) Variable global `_RESERVED_PORTS = set()` en `setup.py` — rechazado: pollución del namespace, tests requieren reset entre runs, no resuelve el caso de wizards paralelos.
- (b) Que `_quick_free_port` haga `socket.bind()` real con `SO_REUSEADDR` y mantenga el socket abierto hasta el final del wizard — rechazado: complica el lifecycle, requiere cleanup explícito de los sockets, y rompe en sistemas donde el bind temporal interfiera con el real (Docker network namespaces).
- (c) Aumentar la step entre defaults (18810, 18820, 18830, 18840) — rechazado: parche cosmético, no resuelve el problema de fondo (cualquier secuencia con dos defaults adyacentes seguiría rota).

**Impacto:** +12 LOC en `setup.py`, parámetro retrocompatible (`reserved=None` mantiene el comportamiento anterior). +180 LOC tests con `monkeypatch` sobre `detect_port_free` (cero sockets reales en CI). El wizard refactor en `build_quick_config` es 4 líneas extra (`_reserved_ports.add(...)`).

### Decisión 2: el helper NO se auto-añade al `reserved` set — el caller es dueño de su lifecycle

**Decisión:** `_quick_free_port` lee `reserved` pero no lo muta. Es el caller quien debe hacer `reserved.add(got)` después de cada llamada exitosa.

**Motivo:** mantener la simetría "función pura, caller decide qué hacer con el resultado". Si el helper se auto-añadiera, el caller que olvide añadir manualmente seguiría sufriendo Bug 22 hasta que alguien diagnostique por qué; con la responsabilidad del caller, olvidar el `add()` rompe en el siguiente test que ejerza la combinación. Tests pinean "reserved no es mutado" para evitar regresión accidental hacia el otro estilo.

**Alternativas consideradas:**
- (a) Auto-añadir al reserved — rechazado por las razones anteriores. También complica casos donde el caller quiere `_quick_free_port` puramente como "consulta sin reserva" (advanced-mode prompts).

**Impacto:** trivial. Documentado en docstring del helper y test explícito (`test_reserved_not_mutated`).



## 2026-04-15 — PR-29

### Decisión 1: usar `waiting_input` como destino de la transición, no permitir `en_progreso → pendiente` en la state machine

**Decisión:** la tarea transita de `en_progreso` a `waiting_input` cuando el routing reporta `approval_required`, respetando la state machine canónica en `state_machines.TASK_TRANSITIONS`. NO se modifica la state machine para permitir `en_progreso → pendiente`.

**Motivo:** `waiting_input` es el estado semánticamente correcto per SPEC-v0.2 §2 — "necesita acción humana antes de proceder". `pendiente` significa "esperando a un worker que la reclame", que es la semántica equivocada: mientras el approval está pending, la tarea NO debería ser reclamable por el executor; relajar la state machine a permitir `en_progreso → pendiente` reabría el bucle de procesamiento (executor reclama, vuelve a fallar, vuelve a pendiente, repeat).

**Alternativas consideradas:**
- (a) Añadir `'pendiente'` al set permitido desde `en_progreso` en `state_machines.py` — rechazado: relaja la invariante sin fix real del bucle.
- (b) Hacer que el executor detecte tasks con approval pending y las skipee en `_claim_next_task` — rechazado: acopla el claimer al approval state, duplica lógica, y no ayuda a la UI (la tarea "pendiente" en la UI es misleading para un operador que espera aprobar).
- (c) Usar `revision` en vez de `waiting_input` — rechazado: `revision` es para "revisión humana del output final", no pre-execution gate.

**Impacto:** 5 líneas cambiadas en `bin/task-executor.py::_execute_task_v02`. Cero cambios en `state_machines.py`.

### Decisión 2: la transición inversa vive DENTRO de `approval_service.resolve_approval`, no en el HTTP handler

**Decisión:** la UPDATE de `tasks.status` desde `waiting_input` a `pendiente` vive en `approval_service.resolve_approval` — NO en el handler HTTP `POST /api/approvals/:id/resolve` de `app.py`. Se ejecuta dentro de la misma transacción que la UPDATE de `approvals`.

**Motivo (post-review):** el diseño inicial de PR-29 ponía la transición en el handler HTTP. Review independiente (agente de double-check sobre el primer commit) descubrió que `assistant_service.tool_approval_respond` — reachable vía `POST /api/assistant/tools/approval_respond` Y vía el MCP tool `approval_respond` — llama `resolve_approval` directo, bypasseando el handler HTTP. Con la lógica sólo en el handler, el path assistant/MCP seguía dejando tasks orfanas en `waiting_input` (exacto el failure mode que Bug 23 claims to fix). Lección: la lógica que debe dispararse en cada resolve pertenece al service que hace el resolve, no a uno de los múltiples callers.

Ubicar la transición en el service garantiza que **toda ruta presente y futura** que llame `resolve_approval` reciba el fix automáticamente. Cero coupling nuevo entre callers — al contrario, elimina duplicación latente (el handler y el tool habrían acabado copiando la misma lógica si se mantenía en el handler).

**Alternativas consideradas:**
- (a) Extraer un helper `_transition_task_on_approve(task_id, conn)` y llamarlo desde cada caller (handler + tool_approval_respond + futuros) — rechazado: requiere modificar cada caller presente y futuro. El bug original fue exactamente que un caller olvidó el paso.
- (b) Scheduler/worker que haga poll de approvals recién aprobadas — rechazado: latency artificial, complejidad innecesaria, acopla un nuevo componente a un flow sincrono que ya funciona.
- (c) Executor observa approvals via poll — rechazado: rompe el principio de "executor sólo ve tasks con status='pendiente'". Acopla executor al approval_service.
- (d) Callback/webhook desde approval_service al task_service — rechazado: indirección innecesaria cuando ambos viven en el mismo proceso, misma conn, misma transacción.

**Reject** deliberadamente NO dispara la inversa — el operador que rechaza un approval puede querer archivar, retomar, o redirigir manualmente.

**Impacto:** +40 LOC en `resolve_approval`. `app.py` handler simplificado (-45 LOC — elimina la duplicación que había metido la versión inicial). `tool_approval_respond` NO se toca, recibe el fix automáticamente por llamar al service.

### Decisión 3: aceptar la race con `task_request_input` como limitación documentada, no arreglar en PR-29

**Decisión:** `waiting_input` es un estado compartido — puede ser set por el routing-approval flow (PR-29) o por el MCP tool `task_request_input` (PR-02). `resolve_approval` gateia sólo en `task.status == 'waiting_input'`, sin verificar la causa. En la race estrecha donde una tarea está en `waiting_input` por un `task_request_input` pendiente Y simultáneamente tiene un approval pending, aprobar el approval fuerza la tarea a `pendiente` aunque la pregunta del `task_request_input` siga sin respuesta.

**Motivo para NO arreglar ahora:** la race requiere **ambas causas simultáneas**. El approval_required de routing se evalúa en pre-execution; si se disparó, la tarea nunca llegó a ejecutar el subprocess del adapter, y `task_request_input` — que sólo se puede llamar desde dentro del subprocess ejecutando — no tiene oportunidad de dispararse en esta iteración. La única manera de tener ambas simultáneas es: tarea ejecuta, termina pidiendo `task_request_input` → `waiting_input`; luego alguien crea manualmente un approval sobre esa tarea (path manual sin workflow automático en v0.2) o capability_service detecta violación retrospectiva (no hay camino hoy). El race es real pero sólo si alguien crea approvals manualmente sobre tasks ya en `waiting_input`, que no es un workflow documentado.

**Alternativas consideradas:**
- (a) Registrar en `approvals` cuál fue el motivo del `waiting_input` para disambiguar en resolve — rechazado: requiere columna nueva + migration + cambios en callers que crean approvals. Scope desproporcionado para un race narrow.
- (b) Contar "motivos" de `waiting_input` en una tabla separada — rechazado: igual overhead.
- (c) Documentar como limitación y atacar sólo si se observa en producción — aceptado.

**Impacto:** cero LOC. Documentación en BUGS-FOUND.md entry del Bug 23 y en el docstring de `resolve_approval`. Si el race se observa en producción, abrir un issue con repro y atacar entonces.

### Decisión 4: fix en dos sitios requiere dos bloques de tests independientes — el de la ruta assistant/MCP es crítico

**Decisión:** Bug 23 tiene dos mitades estructurales (executor side + approval_service side). Cada mitad tiene su archivo de tests — `tests/test_task_executor_approval_state.py` y `tests/test_approvals_resolve_transitions_task.py` — con invariantes estáticos (regex sobre source) + behaviour tests (sqlite real + llamadas directas al service). El test de `tool_approval_respond` específicamente verifica que el service-centric design funciona para la ruta del assistant/MCP (el gap que review detectó en el primer commit).

**Motivo:** si alguien refactoriza una de las dos mitades sin entender que la otra depende de ella, queremos que los tests de la mitad afectada fallen loud y apunten a la otra. Los dos archivos referencian mutuamente en sus docstrings. El test `TestHandlerNoLongerHasDuplicateBlock` pinea explícitamente que el handler HTTP no re-duplique la lógica (guard contra la arquitectura anterior).

**Alternativas consideradas:**
- (a) Un solo archivo de tests que cubre ambas mitades — rechazado: confunde el scope de cada test y hace difícil localizar el fallo cuando uno de los sides rompe.

**Impacto:** 15 tests nuevos (9 en el archivo approval + 6 en el executor). 112/112 pasa la suite approval+executor.
