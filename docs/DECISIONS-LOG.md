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
