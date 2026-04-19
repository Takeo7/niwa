# PR-B4 — Planner tier crea subtareas reales en DB y bloquea al padre

**Hito:** B
**Esfuerzo:** L (riesgo real de exceder 400 LOC — ver §Decisiones abiertas)
**Depende de:** PR-B1 (merged), PR-B2 (merged)
**Bloquea a:** PR-D1 (smoke E2E del happy path completo)

## Qué

Convertir el "planner tier" hoy parcial en un mecanismo end-to-end:
trigger explícito (`decompose=true` por tarea o `description` por
encima de un umbral), output estructurado parseado por Niwa, creación
de subtareas con `parent_task_id` en DB, scheduler que ejecuta hijas
antes que el padre, y agrupación mínima en la UI.

## Por qué

Cierra el bullet 4 del happy path (`docs/MVP-ROADMAP.md §1`): tarea
compleja se desgrana automáticamente y se ejecuta sin intervención.

## Estado actual del terreno [Hecho — leído]

- `bin/task-executor.py:1855-1913` — el planner tier existe **solo en
  `_execute_task_legacy`** (no en v0.2). Se dispara con
  `LLM_COMMAND_PLANNER` configurado + no-retry + no-worker. Sin flag
  `decompose`, sin umbral de description.
- `bin/task-executor.py:1073-1139` — `_build_planner_prompt` instruye
  al modelo a usar MCP `task_create` para crear hijas y responder
  `SPLIT_INTO_SUBTASKS`. **Niwa no parsea ni crea nada**: confía en
  que el modelo invoque MCP, lo cual no garantiza
  `parent_task_id`.
- `niwa-app/db/migrations/013_task_parent.sql` — `parent_task_id`
  TEXT nullable + índice. Sin FK.
- `niwa-app/backend/tasks_service.py:154-180` — `create_task` y
  `update_task` ya aceptan `parent_task_id`.
- `niwa-app/frontend/src/shared/types/index.ts:30` y
  `TaskForm.tsx:141-144` — el frontend ya conoce `parent_task_id`,
  no hay vista que lo agrupe.
- `bin/task-executor.py:185-189` — `LLM_COMMAND_PLANNER` y
  `PLANNER_TIMEOUT` están parseados.

## Scope — archivos que toca

### Backend
- `niwa-app/db/migrations/017_task_decompose.sql` (nuevo):
  `ALTER TABLE tasks ADD COLUMN decompose INTEGER DEFAULT 0` +
  índice opcional. Migration 016 fue PR-C3.
- `niwa-app/db/schema.sql`: añadir `decompose INTEGER DEFAULT 0` en
  `tasks` para fresh installs.
- `bin/task-executor.py`:
  - Reescribir `_build_planner_prompt` para pedir output
    **estructurado** (bloque JSON entre marcadores), no MCP.
  - Nuevo helper `_parse_planner_output(text) -> list[dict]` que
    extrae las subtareas.
  - Nuevo trigger en `_execute_task` (no solo en legacy): correr
    planner si `task.decompose == 1` o
    `len(task.description or "") > NIWA_PLANNER_DESCRIPTION_THRESHOLD`
    (default 400 chars, env-tunable) **y** `LLM_COMMAND_PLANNER` está
    configurado.
  - Cuando el planner devuelve subtareas: insertar cada una en `tasks`
    con `parent_task_id=padre.id`, `project_id=padre.project_id`,
    `status='pendiente'`. Marcar el padre como `bloqueada` con
    `notes` indicando "esperando N hijas".
  - Si el planner falla o el output no parsea: caer al executor
    directo (comportamiento actual de fallback).
- `niwa-app/backend/scheduler.py`: hook `on_task_completed` (o
  equivalente) que, cuando una hija pasa a `hecha`, comprueba si
  todas las hermanas están `hecha`; si sí, desbloquea al padre y lo
  marca `hecha` con resumen ("3/3 subtareas completadas").
- `niwa-app/backend/tasks_service.py`: helpers
  `list_children(parent_id)` y `count_children_by_status(parent_id)`.
  Ya existe `parent_task_id` en `create_task`/`update_task`, no hay
  que tocar el writer.

### Frontend (mínimo viable)
- `niwa-app/frontend/src/features/tasks/components/TasksList.tsx` (o
  el componente equivalente que renderiza la lista — confirmar al
  empezar): añadir badge inline `↳ N/M hijas` en filas con hijas.
  **No** crear `TaskTreeView.tsx` standalone en este PR — ver
  decisión 5.
- `niwa-app/frontend/src/features/tasks/components/TaskForm.tsx`:
  checkbox `decompose` (visible solo en create).

### Tests nuevos
- `tests/test_planner_split_creates_children.py`: planner devuelve
  3 subtareas → 3 filas en DB con `parent_task_id` correcto y padre
  `bloqueada`.
- `tests/test_planner_threshold_trigger.py`: description > umbral
  dispara planner; description corta no.
- `tests/test_scheduler_unblocks_parent.py`: cuando última hija
  pasa a `hecha`, padre pasa a `hecha` con resumen.
- `tests/test_planner_malformed_output.py`: output no-parseable cae a
  executor directo, no rompe la tarea.

## Fuera de scope (explícito)

- **No** se crea `TaskTreeView.tsx` como vista standalone (queda como
  follow-up; en este PR solo badge inline).
- **No** se cambia el wiring v0.2 vs legacy más allá de meter el
  trigger del planner en ambos paths. El planner sigue siendo
  opcional (requiere `LLM_COMMAND_PLANNER` set).
- **No** se decompone recursivamente (las hijas de hijas son fuera
  de MVP, ver §1 del roadmap).
- **No** se añade re-prompt al padre tras hijas (el padre se cierra
  con resumen, no se re-ejecuta).
- **No** se cambia el formato del MCP `task_create` actual (sigue
  disponible para que un agente cree tareas manualmente).
- **No** se tocan approvals, hosting, ni adapters.

## Tests

- **Nuevos:** los 4 ficheros listados arriba.
- **Existentes que deben seguir verdes:** todos los `test_pr55_*`
  (tocan `parent_task_id`), todo `test_scheduler_*`, todo
  `test_executor_*`.
- **Baseline esperada tras el PR:** `≥1033 pass / ≤60 failed /
  ≤104 errors` (no regresar nada). Los 4 tests nuevos suman `pass`.

## Criterio de hecho

- [ ] Migration 017 corre sin error en DB existente y fresh install.
- [ ] Tarea con `decompose=1` o `description > 400 chars` invoca al
      planner; tarea normal no.
- [ ] Planner devuelve JSON parseable → N filas insertadas con
      `parent_task_id` correcto; padre pasa a `bloqueada`.
- [ ] Cuando todas las hijas pasan a `hecha`, el padre pasa
      automáticamente a `hecha`.
- [ ] Output del planner malformado → fallback a executor directo
      (sin pérdida de tarea).
- [ ] Badge `↳ N/M` visible en `TasksList`.
- [ ] Checkbox `decompose` visible en `TaskForm` create.
- [ ] `pytest -q` sin regresiones respecto al baseline 1033 pass.
- [ ] Codex review resuelto.

## Riesgos conocidos

1. **Tamaño del PR**. Estimación honesta: 450-550 LOC (migration ~20,
   executor ~150, scheduler ~80, tasks_service ~30, frontend ~60,
   tests ~150-200). Excede el límite duro de CLAUDE.md de 400 LOC.
   Mitigación: ver §Decisión 1.
2. **Output del planner es no-determinista**. Mitigación: parser
   tolerante (busca primer bloque ```json válido), fallback claro a
   executor directo, test de output malformado.
3. **Interacción con retry**. El retry hoy salta el planner
   (`not retry_prompt`). Mantengo ese comportamiento — si el padre
   falla y el humano pide retry, no se vuelve a desgranar.
4. **Schema migration en producción**. Como toda migration nueva:
   probar idempotente sobre DB con datos.
5. **Concurrencia padre-hijas**. Si el scheduler ejecuta dos hijas en
   paralelo y ambas terminan a la vez, el `unblock_parent` puede
   correr dos veces. Mitigación: lectura+escritura del estado del
   padre dentro de la misma transacción / `WHERE status='bloqueada'`.

## Decisiones abiertas — necesito tu "ok" o tu "mejor X"

1. **Tamaño / división.** Trade-off:
   - **(a)** Aceptar overshoot a ~500 LOC y mantener PR-B4 unitario
     (lo que el roadmap declara como L). Ventaja: una unidad
     mergeable. Desventaja: rompe la regla de 400 LOC.
   - **(b)** Dividir en **PR-B4a** (migration + planner crea hijas
     en DB + tests backend, ~350 LOC) y **PR-B4b** (scheduler
     cierra padre + UI badge + checkbox + tests, ~200 LOC).
     Ventaja: ambos ≤400 LOC, B4a mergeable solo. Desventaja: dos
     ciclos de review, B4a deja al padre `bloqueada` permanente
     hasta que B4b mergee.
   - **Mi recomendación:** **(b)**. La regla de 400 LOC existe por
     algo y B4 es desgranable limpio.

2. **Trigger.** El roadmap dice "flag `decompose=true` **o**
   `description > N chars`". Confirmo: ambos triggers, OR. ¿Default
   N? Propongo 400 chars (env `NIWA_PLANNER_DESCRIPTION_THRESHOLD`).

3. **Formato del output del planner.** Trade-off:
   - **(a)** Mantener MCP `task_create` actual. Más "agentic", menos
     código en Niwa. Pero frágil: el modelo puede olvidar
     `parent_task_id`, MCP puede no estar disponible, no hay forma
     de auditar qué se pidió crear.
   - **(b)** Output estructurado JSON entre marcadores (`<SUBTASKS>
     [...]\n</SUBTASKS>`). Niwa parsea y crea. Más control, más
     fiable, más testeable.
   - **Mi recomendación:** **(b)**. El planner es un componente
     interno de Niwa; el MCP `task_create` queda para casos
     "el agente crea una tarea espontánea".

4. **Estado del padre tras hijas.** Trade-off:
   - **(a)** Padre pasa a `hecha` automáticamente con resumen
     "3/3 subtareas completadas" cuando todas hijas → `hecha`.
   - **(b)** Padre vuelve a `pendiente` para que el executor lo
     re-corra como "review/integración" final.
   - **Mi recomendación:** **(a)**. Más simple, menos calls al LLM.
     Si una hija deja artefactos que necesitan integración, eso es
     responsabilidad de la hija, no de re-correr al padre.

5. **UI — vista standalone vs badge inline.** Trade-off:
   - **(a)** Solo badge `↳ N/M hijas` en TasksList (lo propuesto).
   - **(b)** Componente nuevo `TaskTreeView.tsx` con expansión
     real del árbol.
   - **Mi recomendación:** **(a)** en este PR para acotar tamaño.
     `TaskTreeView.tsx` real va como follow-up cuando lo demande
     PR-D1 o feedback.

6. **Wiring v0.2 vs legacy.** Hoy el planner solo corre en legacy.
   El roadmap no lo aclara. Propongo: trigger del planner se evalúa
   en `_execute_task` (entry point común) **antes** de elegir
   pipeline. Si dispara, corre planner; si no, sigue al pipeline
   normal (v0.2 o legacy según `routing_mode`).

## Notas para Claude Code

- **No tocar código hasta el "ok" del humano** sobre las 6
  decisiones de arriba.
- Si las respuestas confirman división (1.b): este brief se
  reescribirá como PR-B4a y se creará PR-B4b aparte.
- Tests primero (rojos verificados), luego implementación, luego
  Codex review obligatorio (es L).
- Commits pequeños imperativos en inglés.
