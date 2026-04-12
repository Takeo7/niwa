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
