# PR-B4a — Planner tier crea subtareas reales en DB

**Hito:** B
**Esfuerzo:** M (split de PR-B4 original L; estimado ~350 LOC)
**Depende de:** PR-B1 (merged), PR-B2 (merged)
**Bloquea a:** PR-B4b (scheduler cierra padre + UI), PR-D1

## Contexto del split

PR-B4 original (L, ~500 LOC) se divide en:
- **PR-B4a (este PR):** trigger del planner + parseo del output +
  creación de hijas en DB con `parent_task_id` + padre pasa a
  `bloqueada`. Backend mínimo.
- **PR-B4b (siguiente):** scheduler desbloquea/cierra padre cuando
  todas las hijas están `hecha`, badge `↳ N/M hijas` en UI,
  checkbox `decompose` en `TaskForm`.

**Consecuencia operativa de mergear B4a sin B4b:** una tarea que
pasa por el planner queda con el padre `bloqueada` indefinidamente
hasta que B4b mergee (o hasta que el humano lo cierre a mano).
Aceptable para una sesión de transición; no aceptable como estado
final de v1.

## Qué

Cuando una tarea cumple un criterio de "compleja", el executor
invoca al planner con un prompt que pide output **estructurado**
(JSON entre marcadores). Niwa parsea el output, inserta N filas
nuevas en `tasks` con `parent_task_id` apuntando a la tarea original,
y marca al padre como `bloqueada`. Si el output no parsea, fallback
silencioso al executor directo.

## Por qué

Cierra el bullet 4 del happy path (`docs/MVP-ROADMAP.md §1`) por la
parte "tarea compleja se desgrana". El cierre del padre + UI van en
B4b.

## Estado actual del terreno [Hecho — leído]

- `bin/task-executor.py:1855-1913` — planner tier existe **solo en
  legacy**, sin parseo, confía en MCP `task_create` del modelo, no
  garantiza `parent_task_id`.
- `bin/task-executor.py:1073-1139` — `_build_planner_prompt` actual
  pide `SPLIT_INTO_SUBTASKS` como sentinel de texto.
- `bin/task-executor.py:185-189` — `LLM_COMMAND_PLANNER` y
  `PLANNER_TIMEOUT` ya parseados.
- `niwa-app/db/migrations/013_task_parent.sql` — `parent_task_id`
  TEXT nullable + índice. Sin FK.
- `niwa-app/backend/tasks_service.py:154-180` — `create_task` y
  `update_task` ya aceptan `parent_task_id`.
- Última migration aplicada: 016 (PR-C3). La nueva será **017**.

## Decisiones aprobadas (de PR-B4 original)

1. **División:** B4a + B4b (este PR es B4a).
2. **Trigger:** `task.decompose == 1` **OR**
   `len(task.description or "") > NIWA_PLANNER_DESCRIPTION_THRESHOLD`
   (default 400). Ambos triggers además requieren
   `LLM_COMMAND_PLANNER` configurado.
3. **Output del planner:** JSON estructurado entre marcadores
   `<SUBTASKS>...</SUBTASKS>` (no MCP).
4. **Estado del padre tras hijas (B4b):** padre → `hecha`
   automáticamente con resumen. Fuera de B4a.
5. **UI (B4b):** solo badge inline, sin vista standalone. Fuera de
   B4a.
6. **Wiring v0.2 vs legacy:** trigger del planner se evalúa en
   `_execute_task` (entry común) **antes** de elegir pipeline.

## Scope — archivos que toca (B4a)

- `niwa-app/db/migrations/017_task_decompose.sql` (nuevo): añadir
  `decompose INTEGER NOT NULL DEFAULT 0` a `tasks`.
- `niwa-app/db/schema.sql`: misma columna en la definición fresca de
  `tasks` (para installs nuevos).
- `bin/task-executor.py`:
  - Reescribir `_build_planner_prompt` para pedir output JSON entre
    marcadores `<SUBTASKS>` / `</SUBTASKS>`. Cada item:
    `{"title": str, "description": str, "priority": str?}`.
  - Nuevo helper `_parse_planner_output(text) -> list[dict] | None`.
    Tolerante: busca el primer bloque entre marcadores, valida
    schema mínimo, devuelve `None` si malformado.
  - Nuevo helper `_create_subtasks(parent_task, subtasks) -> int`.
    Inserta N filas en `tasks` y marca padre `bloqueada` con notes
    "Split into N subtasks by planner". Devuelve N.
  - Nuevo helper `_should_run_planner(task) -> bool` que aplica el
    trigger (decompose flag OR threshold).
  - Mover el bloque `if LLM_COMMAND_PLANNER and not retry_prompt
    and not WORKER_MODE:` a `_execute_task`, gobernado por
    `_should_run_planner`. El path legacy/v0.2 se elige
    **después** del planner (cuando el planner devuelve "ejecuta
    directo" o falla, o cuando el trigger no aplica).
  - Si planner devuelve `EXECUTE_DIRECTLY` (mantener ese sentinel
    para casos en los que el modelo decide no dividir), continuar
    al pipeline normal.
  - Si planner devuelve subtareas válidas: insertarlas, marcar
    padre `bloqueada`, devolver `(True, "[planner] Split into N
    subtasks")`.
- `niwa-app/backend/init_db.py` o equivalente: si maneja
  migrations explícitamente, registrar 017. Verificar al empezar
  cómo se aplican las migrations (si es discovery automático del
  directorio, no hace falta tocar).

## Fuera de scope (explícito, ahora más estricto)

- Scheduler / cierre automático del padre → **B4b**.
- UI (badge, checkbox) → **B4b**.
- Re-prompt del padre tras hijas → fuera de MVP.
- Decomposición recursiva (hijas de hijas) → fuera de MVP.
- Cambiar el MCP `task_create` actual → no se toca.
- Approvals, hosting, adapters → no se tocan.
- Helpers `list_children` / `count_children_by_status` → B4b
  (no los necesita B4a).

## Tests nuevos

- `tests/test_planner_split_creates_children.py`:
  - Stub de `_run_with_heartbeat` que devuelve un output con
    `<SUBTASKS>` válido (3 items).
  - Llamar a `_execute_task` sobre una tarea con `decompose=1`.
  - Aserciones: 3 filas nuevas en DB con `parent_task_id` correcto
    y `project_id` heredado; padre con `status='bloqueada'`.
- `tests/test_planner_threshold_trigger.py`:
  - Tarea con `description` corta (<400) y `decompose=0` → no se
    invoca al planner (stub no llamado).
  - Tarea con `description` >400 → planner invocado.
  - Tarea con `decompose=1` y description corta → planner invocado.
- `tests/test_planner_malformed_output.py`:
  - Output sin marcadores → `_parse_planner_output` devuelve `None`,
    fallback al executor directo, sin filas nuevas en DB.
  - Output con marcadores pero JSON inválido → idem.

## Tests existentes que deben seguir verdes

- `tests/test_pr55_*` (tocan `parent_task_id`).
- `tests/test_executor_*`, `tests/test_scheduler_*`.
- Suite completa: baseline 1033 pass.

## Baseline esperada tras el PR

`≥1033 pass / ≤60 failed / ≤104 errors / ≥87 subtests pass`.
Los 3 tests nuevos suman al `pass`.

## Criterio de hecho

- [ ] Migration 017 aplica idempotente (re-run no falla).
- [ ] Tarea con `decompose=1` invoca planner; tarea normal con
      description corta no.
- [ ] Planner con output JSON válido inserta N hijas con
      `parent_task_id` correcto y padre pasa a `bloqueada`.
- [ ] Output malformado → ejecutor directo, sin filas nuevas, sin
      crash.
- [ ] `python3 -m pytest -q` sin regresiones vs baseline 1033 pass.
- [ ] Codex review resuelto (PR es M tras split → Codex es opcional
      pero lo invoco igualmente, dado que el código toca el
      executor monolítico).

## Riesgos conocidos

1. **Padre queda `bloqueada` sin scheduler que lo cierre.** Por
   diseño de B4a. B4b lo resuelve. Mientras tanto, una tarea
   desgranada en producción se queda visible como bloqueada y
   requiere intervención manual (cerrar a `hecha` desde la UI).
2. **Output no-determinista del planner.** Mitigado por parser
   tolerante y fallback claro.
3. **Migration 017 sobre DB con datos existentes.** Test
   idempotente; tasks viejas heredan `decompose=0` por DEFAULT.
4. **Concurrencia.** B4a no introduce concurrencia nueva: la
   inserción de hijas y el update del padre van en la misma
   conexión (verificar al implementar). El read-modify-write del
   padre es seguro porque el padre solo lo toca el executor de su
   propia tarea.

## Notas para Claude Code

- Tests primero rojos, luego implementación.
- Commits pequeños imperativos en inglés.
- Codex review antes de abrir PR.
- En el PR body: declarar explícitamente que es **B4a de B4 split**
  y dejar el riesgo "padre queda bloqueada hasta B4b" visible para
  el reviewer.
