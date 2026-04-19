# PR-C1 — Auto-deploy cuando una tarea marca `status='hecha'`

**Hito:** C
**Esfuerzo:** S-M
**Depende de:** PR-B2 (merged)
**Bloquea a:** PR-C3 (healthcheck consume `deployments`), criterio hito C

## Qué

Cuando una tarea transiciona a `status='hecha'` y tiene `project_id` no
nulo, disparar `hosting.deploy_project(project_id)` como side-effect
dentro de `tasks_service.update_task()`. La URL resultante
(`projects.url`, ya lo rellena `deploy_project`) se expone en el
endpoint `GET /api/tasks/:id` como campo nuevo `deployment_url` y se
renderiza en `TaskDetailsTab.tsx` debajo del "Resultado" cuando la
tarea está en estado terminal.

El disparo se puede desactivar globalmente con env var
`NIWA_DEPLOY_ON_TASK_SUCCESS=0` (default `1`).

## Por qué

Cierra el happy-path §1.5 del MVP-ROADMAP: "Al completar, Niwa
despliega al subdominio configurado — o a `localhost:port/<slug>/`
si no hay DNS — sin que el usuario toque nada." Hoy el deploy existe
(`POST /api/projects/:id/deploy`) pero es **manual**; nadie lo
llama al cerrar una tarea.

## Scope — archivos que toca

- `niwa-app/backend/tasks_service.py` — tras el commit del status
  a `'hecha'` (L211), si `project_id` existe y el flag env está on,
  invocar `hosting.deploy_project(project_id)` dentro de
  `try/except`: log exception + `record_task_event(type='alerted')`,
  **no** re-raise (el deploy no debe abortar la transición de
  estado — ya está commiteada). Nuevo helper interno
  `_maybe_autodeploy(task_id, project_id) -> Optional[dict]`.
- `niwa-app/backend/app.py` — en el handler de `GET /api/tasks/:id`
  (serializer único usado por `TaskDetailsTab`), añadir
  `deployment_url` derivado de `projects.url` via JOIN o fetch por
  `project_id`. Solo se incluye si `project_id` no es null.
- `niwa-app/frontend/src/shared/types/index.ts` — añadir
  `deployment_url?: string | null;` a `Task` (solo presente en
  detail, como `executor_output` y `last_run`).
- `niwa-app/frontend/src/features/tasks/components/TaskDetailsTab.tsx`
  — nuevo bloque `<Paper>` bajo "Resultado" que muestra `Desplegado
  en: <a>{deployment_url}</a>` cuando `task.status === 'hecha' &&
  task.deployment_url`. Sin emoji. Copy en castellano.
- `tests/test_task_autodeploy_on_success.py` (nuevo) — ver sección
  Tests.
- `niwa-app/frontend/src/features/tasks/components/TaskDetailsTab.test.tsx`
  — 1 caso nuevo: renderiza link si hay `deployment_url`.

## Fuera de scope (explícito)

- No migración de schema. El flag vive en env var, no en
  `projects` ni en `tasks`. Una columna per-project llegaría en
  otro PR si se pide.
- No reintento automático si `deploy_project` falla. Queda
  manual (`POST /api/projects/:id/deploy`).
- No validación de `artifacts dentro de project_directory` — eso
  es el fix de PR-B2; si PR-B2 resolvió a `waiting_input`, la
  tarea no llega a `'hecha'` y este hook no se dispara (feature,
  no bug).
- No MCP tool nueva. El hook es server-side puro.
- No undeploy automático en `archivada`. Fuera de alcance de
  hito C según roadmap §4.
- No cambios en `tasks_service.create_task`.
- No tocar `force_reject_task` (ya bypasea state machine, no
  pasa por `update_task`).

## Tests

- **Nuevos** (`tests/test_task_autodeploy_on_success.py`):
  - `test_update_task_to_hecha_triggers_deploy_when_project_id`:
    monkeypatch `hosting.deploy_project`, verificar que se llama
    con `(project_id,)`.
  - `test_update_task_to_hecha_skips_when_no_project_id`:
    `hosting.deploy_project` **no** se llama.
  - `test_update_task_to_hecha_skips_when_env_flag_off`:
    `NIWA_DEPLOY_ON_TASK_SUCCESS=0` → no llama.
  - `test_update_task_to_other_status_does_not_trigger`:
    transición a `revision` no dispara.
  - `test_deploy_failure_does_not_break_status_transition`:
    monkeypatch para que `deploy_project` lance `ValueError`; la
    tarea queda `'hecha'`, se registra un `task_event` de tipo
    `alerted` con el error, y el endpoint devuelve 200.
- **Frontend** (`TaskDetailsTab.test.tsx`): caso nuevo
  "renders deployment link when task is hecha and has
  deployment_url".
- **Existentes que deben seguir verdes:**
  - `tests/test_tasks_endpoints*.py`
  - `tests/test_deployments_endpoints.py`
  - `tests/test_task_events*.py` si existe
  - Todo `TaskDetailsTab.test.tsx` previo.
- **Baseline esperada tras el PR:** `≥1033 pass / ≤60 failed /
  ≤104 errors` + los 5 nuevos tests pass ⇒ `≥1038 pass`.

## Criterio de hecho

- [ ] `update_task(task_id, {status:'hecha'})` con task que tiene
  `project_id` llama a `hosting.deploy_project` una vez.
- [ ] `GET /api/tasks/:id` para esa tarea devuelve
  `deployment_url: "http://..."` (string no vacío).
- [ ] Con `NIWA_DEPLOY_ON_TASK_SUCCESS=0` en el entorno del
  backend, ningún deploy se dispara automáticamente.
- [ ] Si `deploy_project` lanza, la tarea sigue `'hecha'` y el
  timeline de la tarea muestra un evento con el error.
- [ ] En el UI, un task `'hecha'` con `deployment_url` muestra un
  bloque "Desplegado en: <URL>" con link abribable en nueva
  pestaña.
- [ ] `pytest -q` sin regresiones respecto a baseline.
- [ ] `npm test` (vitest, frontend) sin regresiones.
- [ ] Review Codex resuelto (o `LGTM`).

## Riesgos conocidos

- **Humano marca `'hecha'` manualmente sin artefactos reales** →
  dispara deploy que puede fallar con "Directory not found" si el
  proyecto no tiene `directory`. Mitigación: el propio
  `deploy_project` ya levanta `ValueError` y lo capturamos; queda
  reflejado en el timeline. Para el usuario final, el UI no muestra
  ningún `deployment_url` (porque `projects.url` no se escribió) y
  el link no aparece. No se degrada la UX.
- **Race con otro update concurrente** — `update_task` hace un solo
  commit, el hook corre después del commit. Si dos updates llegan
  en paralelo, el segundo ya verá `'hecha'` como current y la
  state-machine rechazará la transición. Sin riesgo adicional.
- **Regresión de tests de deployments endpoint** — baja: solo
  añadimos un call site a una función ya testada.
- **Leak de env var en tests existentes** — mitigación: el fixture
  del test nuevo setea explícitamente el env var con monkeypatch
  para aislarse.

## Trade-offs presentados

Dos caminos reales para el flag on/off:

1. **Env var global (elegido).** LOC mínimo, reversible con
   reinicio. Pierde granularidad per-project.
2. **Columna `deploy_on_success INTEGER` en `projects`.** Migración
   014, UI en ProjectSettings, default 1. Mayor UX, +150 LOC
   incluyendo migración y tests. Queda para PR aparte si se pide.

Voto por (1) porque el criterio del hito C es "funciona E2E en v1";
per-project configurability se puede encolar sin bloquear B→C→D.

## Notas para Claude Code

- Commits previstos (imperativo, inglés):
  1. `test: failing cases for auto-deploy on task completion`
  2. `feat(tasks): auto-deploy project when task marks hecha`
  3. `feat(api): expose deployment_url in GET /api/tasks/:id`
  4. `feat(ui): show deployment link in TaskDetailsTab`
- Si al implementar el scope crece (p.ej. falta exponer
  `deployment_url` sin tocar queries existentes, o el UI requiere
  nuevo hook de React Query), **paro y reabro brief**.
- Codex reviewer: obligatorio (esfuerzo S-M, no S).
- `pytest -q` completo antes de abrir PR. Pegar diff vs baseline
  1033/60/104 en el body.
