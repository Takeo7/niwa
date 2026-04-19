# PR-B4b — Planner tier cierra padre y expone UI (hijas + decompose)

**Hito:** B
**Esfuerzo:** M (estimado ~200 LOC backend + tests + frontend)
**Depende de:** PR-B4a (merged, #91), PR-C1 (autodeploy — merged)
**Bloquea a:** PR-D1 (smoke E2E)

## Contexto del split

PR-B4 original (L) se dividió en:
- **PR-B4a (merged #91):** trigger del planner + parseo + inserción de
  hijas con `parent_task_id` + padre pasa a `bloqueada`.
- **PR-B4b (este PR):** cierre automático del padre cuando todas las
  hijas terminan + UI (badge hijas + checkbox `decompose`).

Estado operativo actual: una tarea desgranada deja al padre en
`bloqueada` indefinidamente (documentado como riesgo aceptado en el
brief de B4a). Este PR lo resuelve.

## Qué

Cuando la última hija de una tarea `bloqueada` por planner split
transiciona a `hecha`, Niwa transiciona al padre a `hecha`
automáticamente con un resumen. Se añade un badge `↳ N/M` en la lista
de tareas para los padres con hijas, y un checkbox "Desgranar con
planner" en `TaskForm` que setea `decompose=1` al crear.

## Por qué

Cierra el bullet 4 del happy path (`docs/MVP-ROADMAP.md §1`): tarea
compleja se desgrana y termina sin intervención manual. Sin este PR,
PR-B4a no es usable en producción.

## Estado actual del terreno [Hecho — leído]

- `bin/task-executor.py:875-900` — `_finish_task` actualiza
  `tasks.status` directamente por SQL; no pasa por `tasks_service`.
- `bin/task-executor.py:2180-2195` — `_handle_task_result` detecta
  sentinel `_PLANNER_SPLIT_SENTINEL` y mueve el padre a `bloqueada`.
- `niwa-app/backend/tasks_service.py:181-225` — `update_task` es la
  ruta de UI; ya contiene un hook post-commit (`_maybe_autodeploy`)
  para status `hecha`.
- `niwa-app/backend/tasks_service.py:115-137` — `fetch_tasks` devuelve
  `tasks` vía JOIN con `projects`; no incluye conteos de hijas.
- `niwa-app/backend/tasks_service.py:33-112` — `get_task` tampoco
  incluye conteos de hijas.
- `niwa-app/backend/tasks_service.py:140-178` — `create_task` acepta
  payload de la UI; la whitelist de columnas NO incluye `decompose`
  (añadido por migration 017 en PR-B4a).
- `niwa-app/backend/tasks_helpers.py` — ya es sitio natural para
  helpers compartidos entre executor y backend (no reviso aquí si el
  executor lo importa directamente, lo verificaré en Paso 3).
- `niwa-app/frontend/src/features/tasks/components/TaskForm.tsx:1-247`
  — formulario de creación/edición con `Checkbox` de Mantine ya
  importado (para "urgent"). Añadir otro es trivial.
- `niwa-app/frontend/src/shared/types/index.ts:2-38` — interfaz
  `Task` centralizada, incluye `parent_task_id?`. Ampliar con
  `child_count_total?` y `child_count_done?` + `decompose?`.
- Migration 017 (PR-B4a) añadió `tasks.decompose INTEGER NOT NULL
  DEFAULT 0`. No hay migration nueva en este PR.

## Decisiones y trade-offs

1. **Dónde cierra el padre: hook en los dos sitios de transición a
   `hecha`.**
   - Opción A (elegida): hook directo en `_finish_task` (executor) y
     en `update_task` (tasks_service) → cierre inmediato.
   - Opción B (descartada): sweep periódico en scheduler → simple
     pero hasta 60s de delay; además desalinea con el modelo actual
     (hook en `update_task` para autodeploy).
   - Trade-off: duplicar la llamada en dos sitios, pero la lógica va
     en **un único helper** (`tasks_helpers.close_parent_if_children_done`)
     para que solo exista una implementación.

2. **Helper usa SQL directo, no vuelve a invocar `update_task`.**
   Evita re-disparar autodeploy del proyecto del padre (las hijas ya
   dispararon deploys si aplicaba) y el recorrido del state machine
   completo. El helper asserta la transición `bloqueada → hecha`
   explícitamente usando `_TASK_TRANSITIONS` canonical.

3. **Condición para cerrar padre:** `parent.status == 'bloqueada'`
   AND el número de hijas con `status NOT IN ('hecha','archivada')` es
   0. `archivada` cuenta como "terminada a efectos de padre" para no
   dejar bloqueos por hijas archivadas a mano.

4. **Idempotencia:** si el helper se llama concurrentemente (dos
   hijas que terminan a la vez desde dos procesos), SQLite serializa
   writes. Cada llamada re-lee el status del padre y re-cuenta
   hijas dentro de la misma conexión → no hay doble cierre.

5. **Badge UI:** "↳ N/M" donde N = hijas hechas, M = total hijas. Solo
   se renderiza cuando M > 0. No se añade vista standalone
   (`TaskTreeView` queda fuera; era del scope original de B4 L y no
   es necesario para el happy path).

6. **Checkbox `decompose` en TaskForm:** solo visible en modo "crear";
   no editable en tareas existentes (consistent con cómo se maneja
   `parent_task_id`). El payload añade `decompose: 1` cuando está
   marcado.

7. **Autodeploy del padre al cerrarse:** NO se dispara (Opción A.2).
   El padre cerrado por closure no debe re-deployar el proyecto.

## Scope — archivos que toca (B4b)

**Backend:**
- `niwa-app/backend/tasks_helpers.py`: nuevo helper
  `close_parent_if_children_done(conn, parent_id, now_iso) -> bool`.
  SQL puro, asserta transición, inserta `task_event`
  `type='status_changed'` + `type='completed'` con payload
  `{'source': 'planner_parent_closure'}`.
- `niwa-app/backend/tasks_service.py`:
  - `update_task`: tras commit, si `status_value == 'hecha'` y
    `current_task.get('parent_task_id')` → llamar al helper.
  - `fetch_tasks`: añadir subquery correlada
    `(SELECT COUNT(*) FROM tasks c WHERE c.parent_task_id=t.id) AS
    child_count_total` y análoga con `status='hecha'` →
    `child_count_done`.
  - `get_task`: mismo patrón.
  - `create_task`: aceptar `decompose` en el payload; INSERT lo
    incluye.
- `bin/task-executor.py`:
  - `_finish_task`: si `status == 'hecha'` y la tarea tiene
    `parent_task_id`, invocar el helper. El executor ya tiene
    `sys.path` apuntando a `_BACKEND_DIR`; import lazy (`from
    tasks_helpers import close_parent_if_children_done`) dentro
    de la función para no romper arranque si hay imports pesados.
    **Verificar en implementación** si el import es sano.
    Alternativa fallback: inline la SQL en el executor (mismo helper
    copiado) para evitar acoplamiento. Decidir en Paso 3.

**Frontend:**
- `niwa-app/frontend/src/shared/types/index.ts`:
  - Añadir a `Task`: `decompose?: number`, `child_count_total?:
    number`, `child_count_done?: number`.
- `niwa-app/frontend/src/features/tasks/components/TaskForm.tsx`:
  - Estado `decompose: boolean` (init `false`).
  - Checkbox "Desgranar con planner" visible solo si `!isEditing`.
  - Si marcado, `data.decompose = 1` en submit.
- `niwa-app/frontend/src/features/tasks/components/TaskList.tsx`:
  - Badge `↳ N/M` junto al título cuando `child_count_total > 0`.

**Migration:** ninguna. 017 ya añadió `decompose`.

## Fuera de scope (explícito)

- Vista standalone `TaskTreeView` (del scope original de PR-B4 L).
- Re-prompt al padre con los outputs de las hijas.
- Decomposición recursiva (hijas de hijas).
- Cambio en el comportamiento del planner (sigue como en B4a).
- Editar `decompose` en tareas existentes.
- Autodeploy al cerrar el padre.
- Notificaciones o tooltips enriquecidos en el badge.
- Scheduler sweep como safety-net (documentar en post-mortem si
  resulta necesario).

## Tests

**Nuevos:**
- `tests/test_planner_parent_closure_backend.py`:
  - Setup: 1 padre `bloqueada`, 3 hijas `pendiente`, todas con
    `parent_task_id` del padre.
  - Marcar 2 hijas `hecha` vía `update_task` → padre sigue
    `bloqueada`.
  - Marcar la 3ª hija `hecha` → padre pasa a `hecha`,
    `completed_at` setteado, task_event `type='completed'` con
    `payload_json` conteniendo `source='planner_parent_closure'`.
  - Edge: hija `archivada` cuenta como terminada (no bloquea cierre).
  - Edge: si padre está `pendiente` (no `bloqueada`), el helper no
    lo modifica — transición inválida → no-op, no excepción.
  - Edge: hija sin `parent_task_id` → helper nunca llamado
    (verificar que `update_task` no lo invoca).
- `tests/test_planner_parent_closure_executor.py` (o extender
  `test_planner_split_creates_children.py`):
  - Simular `_finish_task(child_id, "hecha", "...")` con 1 sola
    hija. Verificar que el padre pasa a `hecha`.
- `tests/test_task_decompose_flag_create.py`:
  - POST `/api/tasks` con `decompose: 1` → `SELECT decompose` = 1.
  - POST sin el campo → `decompose` = 0 (DEFAULT).
- `tests/test_task_child_counts_api.py`:
  - `GET /api/tasks` para padre con 3 hijas (2 hechas, 1 pendiente)
    devuelve `child_count_total=3, child_count_done=2`.
  - Tarea sin hijas → ambos 0 o ausentes (decidir en impl, consistente
    con el schema del response).

**Existentes que deben seguir verdes:**
- `tests/test_planner_split_creates_children.py` (PR-B4a).
- `tests/test_planner_threshold_trigger.py`.
- `tests/test_planner_malformed_output.py`.
- `tests/test_pr55_*` (tocan `parent_task_id`).
- `tests/test_executor_*`, `tests/test_scheduler_*`,
  `tests/test_c1_autodeploy_*`.

**Frontend:**
- Extender `TaskForm.test.tsx` con caso "create con decompose
  marcado envía `decompose: 1` en payload".

**Baseline esperada tras el PR:** `≥1033 + 5 nuevos pass` (los tests
nuevos suman). `≤60 failed / ≤104 errors / ≥87 subtests pass`.

## Criterio de hecho

- [ ] Padre `bloqueada` con N hijas transiciona a `hecha`
      automáticamente cuando la última hija pasa a `hecha`, vía
      executor (flujo autónomo) y vía UI (`update_task`).
- [ ] Padre cerrado por closure NO dispara autodeploy.
- [ ] `GET /api/tasks` y `GET /api/tasks/:id` devuelven
      `child_count_total` y `child_count_done` para padres con
      hijas.
- [ ] `POST /api/tasks` con `decompose: 1` persiste ese valor; sin
      el campo persiste 0.
- [ ] TaskList renderiza badge `↳ N/M` solo cuando hay hijas.
- [ ] TaskForm muestra checkbox "Desgranar con planner" solo en
      modo crear; al marcarlo, el payload incluye `decompose: 1`.
- [ ] `python3 -m pytest -q` sin regresiones vs baseline 1033 pass;
      los tests nuevos pasan.
- [ ] `npm --prefix niwa-app/frontend run test` (Vitest) verde.
- [ ] Codex review invocado (PR es M) y sus blockers resueltos.

## Riesgos conocidos

1. **Acoplamiento executor → backend module.** El executor ya añade
   `_BACKEND_DIR` al `sys.path` (línea 86-87) y podría importar
   `tasks_helpers`. Si al implementar resulta que el import arrastra
   dependencias indeseadas, la alternativa es duplicar las 15 líneas
   del helper en el executor. Decisión en Paso 3 con el código
   delante.
2. **Doble cierre concurrente.** Dos hijas terminando a la vez en
   procesos distintos. Mitigación: SQLite serializa writes + la
   lógica re-lee el status del padre dentro de la transacción.
   Tests: no hay cómo reproducir concurrencia real con SQLite
   en-memoria; se documenta el invariante y se deja.
3. **Tareas "hechas" ya cerradas con el padre `bloqueada` legacy.**
   Instalaciones que migraron desde antes de B4a podrían tener
   padres bloqueados con hijas ya hechas. El helper es idempotente y
   se evaluará en el próximo cambio de estado de cualquier hija.
   Scope creep a evitar: **NO** correr un sweep retroactivo ahora.
4. **Subqueries correladas en `fetch_tasks`.** SQLite las ejecuta por
   fila. Con LIMIT 500 y tablas pequeñas no es un problema, pero
   conviene verificar con `EXPLAIN QUERY PLAN`. Si aparece regresión
   notable en un test de performance existente, cambiar a `LEFT
   JOIN` con agregación.

## Notas para Claude Code

- Tests rojos primero, luego implementación. Commits pequeños
  imperativos en inglés (`test: failing cases for parent closure`,
  `feat: close planner parent when children finish`, `feat:
  expose child counters in task list`, `feat(ui): decompose
  checkbox + children badge`).
- Si durante la implementación (Paso 3) se descubre que el import
  de `tasks_helpers` desde el executor arrastra basura, documentar
  la decisión de duplicar el helper y seguir. No mezclar esa
  refactorización con este PR.
- Invocar `codex-reviewer` sobre el diff antes de abrir el PR.
- En el body del PR: declarar explícitamente que es **B4b de B4
  split** y cerrar el riesgo que B4a dejó abierto.
