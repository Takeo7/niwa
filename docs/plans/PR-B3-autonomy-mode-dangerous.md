# PR-B3 — flag `autonomy_mode=dangerous` por proyecto

**Hito:** B
**Esfuerzo:** S-M
**Depende de:** ninguna
**Bloquea a:** PR-B4 (planner tier se apoya en ejecución sin
approvals para la tarea "hello world"), PR-D1 (smoke E2E lo asume
encendido).

## Qué

Añade un flag tri-valor opcional `autonomy_mode ∈ {normal, dangerous}`
a cada proyecto. Cuando vale `dangerous`, la capability-service
cortocircuita ambas evaluaciones (pre-ejecución y runtime) y
devuelve `allowed=True`, de modo que ningún approval se crea para
tareas de ese proyecto — el adapter continúa ejecutando sin
transicionar a `waiting_approval`. Se expone por API y la UI
(`ProjectDetail.tsx`) muestra un switch y un banner rojo
persistente cuando está encendido.

Por defecto `normal`. El flag vive en `projects`, no en
`project_capability_profiles`, porque es una propiedad del
proyecto (decisión del operador sobre autonomía), no un parámetro
técnico del perfil de capabilities.

## Por qué

Cierra el criterio del §1.4 del `MVP-ROADMAP` ("ejecuta sin pedir
interacción, dangerous mode por defecto en MVP") y pre-condiciona
PR-B4 / PR-D1, que necesitan correr `hello world` end-to-end sin
aprobaciones manuales.

## [Hecho] sobre el flujo actual

- `get_effective_profile(project_id, conn)` en
  `capability_service.py:115-129` es el único chokepoint que
  consume el perfil; `task-executor.py:1742` y
  `routing_service.py:252` son sus dos llamadores.
- `evaluate()` (pre-exec) y `evaluate_runtime_event()` son los dos
  puntos donde los adapters (`claude_code.py:1019`, `codex.py:697`,
  `claude_code.py:158`, `codex.py:59`) deciden disparar un approval.
- `--dangerously-skip-permissions` del CLI de Claude (PR-34) es
  **otro** mecanismo — permisos del SO — y sigue siempre activo.
  `autonomy_mode` es ortogonal y afecta solo al approval gate
  interno de Niwa.
- Última migración existente: `014_task_retry_marker.sql`.
  La próxima libre es `015`. `docs/MVP-ROADMAP.md §4` reservaba
  `015` a PR-C3 pero PR-B3 va antes en §6; PR-C3 pasará a `016`.

## [Supuesto] sobre el scope

- `approval_service.py` **no se toca**. El roadmap lo listaba
  entre los archivos afectados, pero la ruta limpia es
  cortocircuitar en `capability_service` (antes de que nada en
  `approval_service` se invoque). Si esta interpretación no vale,
  paro y se replantea.
- No se migran approvals ya pendientes al activar `dangerous`. El
  operador puede resolverlos manualmente. Resolver pendings al
  flip del flag es otro PR.

## Scope — archivos que toca

- `niwa-app/db/migrations/015_autonomy_mode.sql` (nuevo):
  `ALTER TABLE projects ADD COLUMN autonomy_mode TEXT NOT NULL
  DEFAULT 'normal'`. Sin `CHECK` (SQLite no soporta añadir
  constraint en `ALTER`); la validación se hace en capa HTTP.
- `niwa-app/db/schema.sql` (proyectos): añade la columna con su
  `CHECK (autonomy_mode IN ('normal','dangerous'))` para fresh
  installs.
- `niwa-app/backend/capability_service.py`:
  - `get_effective_profile()` carga `projects.autonomy_mode` y lo
    mergea en el dict devuelto (clave `autonomy_mode`, default
    `'normal'` si no hay project_id).
  - `evaluate()` y `evaluate_runtime_event()`: primer chequeo
    `if capability_profile.get("autonomy_mode") == "dangerous":
    return {"allowed": True, "reason": "autonomy_mode=dangerous",
    "approval_required": False, "triggers": []}`.
- `niwa-app/backend/app.py`:
  - `PATCH /api/projects/<slug>`: añade `autonomy_mode` al set
    `allowed` (línea 4732), validando `value ∈ {"normal",
    "dangerous"}`. Devuelve 400 con `invalid_autonomy_mode` si no.
  - `GET /api/projects` y `GET /api/projects/<slug>`: incluye
    `autonomy_mode` en la respuesta JSON (coger de la fila, sin
    derivación).
- `niwa-app/frontend/src/shared/types/index.ts`: añade
  `autonomy_mode: 'normal' | 'dangerous'` al tipo `Project`.
- `niwa-app/frontend/src/features/projects/components/ProjectDetail.tsx`:
  - Banner rojo persistente encima del header cuando
    `project.autonomy_mode === 'dangerous'` con texto "Modo
    autónomo activo — approvals desactivados. Revisa el riesgo
    antes de disparar tareas."
  - Switch "Modo autónomo" dentro de la pestaña de configuración
    del proyecto o en el header; PATCH a `/api/projects/<slug>`
    con confirmación modal al pasar a `dangerous` ("¿Seguro? Las
    tareas escribirán sin pedir aprobación").
- `docs/DECISIONS-LOG.md`: 3 líneas con la decisión (flag vive en
  `projects`, no en `project_capability_profiles`; bypass en
  `capability_service`, no en adapters).

## Fuera de scope (explícito)

- No se migra PR-C3 a migración `016` en este PR (lo hará su
  propio brief). Solo se menciona.
- No se auto-resuelven approvals ya pendientes al flip del flag.
- No se expone `autonomy_mode` en la pantalla global
  `/projects` (lista) — solo en `ProjectDetail`. Si la lista lo
  necesita para badge, otro PR.
- No se cambia el comportamiento de
  `--dangerously-skip-permissions` (sigue siempre on).
- No se añade historial de cambios del flag.

## Tests

- **Nuevos:** `tests/test_capability_service_autonomy.py` con
  casos:
  - `evaluate()` con `autonomy_mode='dangerous'` y trigger
    `quota_risk=critical` → `allowed=True`.
  - `evaluate_runtime_event()` tool_use Bash con comando fuera
    del whitelist y `autonomy_mode='dangerous'` → `allowed=True,
    triggers=[]`.
  - `evaluate_runtime_event()` con `autonomy_mode='normal'` y
    mismo evento → `allowed=False` (comportamiento previo
    intacto).
  - `get_effective_profile(project_id, conn)` lee
    `autonomy_mode` de la row y la mergea. Default `'normal'`
    cuando `project_id=None`.
- **Nuevos:** `tests/test_projects_endpoints_autonomy.py`:
  - `PATCH /api/projects/<slug>` con
    `{"autonomy_mode":"dangerous"}` persiste y aparece en `GET`.
  - `PATCH` con `{"autonomy_mode":"yolo"}` → 400
    `invalid_autonomy_mode`.
- **Existentes que deben seguir verdes:**
  `tests/test_capability_service.py` (≥70 casos),
  `tests/test_claude_adapter_start.py`,
  `tests/test_codex_adapter_start.py`,
  `tests/test_approval_service.py`,
  `tests/test_approvals_endpoints.py`.
- **Baseline esperada tras el PR:** ≥ baseline actual
  (`1033 pass / 60 failed / 104 errors` después de PR-C2).
  Los ≥4 tests nuevos de arriba deberían sumar al `pass`.

## Criterio de hecho

- [ ] `curl -X PATCH /api/projects/<slug> -d
  '{"autonomy_mode":"dangerous"}'` persiste y `GET
  /api/projects/<slug>` lo devuelve.
- [ ] Con `autonomy_mode='dangerous'` en un proyecto, una tarea
  con `quota_risk='high'` arranca sin crear approval (verificar
  en tabla `approvals`: 0 rows nuevas).
- [ ] Con `autonomy_mode='normal'` en el mismo proyecto, la misma
  tarea crea approval (regresión cero respecto a v0.2).
- [ ] `ProjectDetail.tsx` en modo `dangerous` muestra banner rojo.
- [ ] Toggle del switch dispara modal de confirmación solo al ir
  de `normal` → `dangerous` (no al revés).
- [ ] `pytest -q` sin regresiones respecto al baseline de PR-C2.
- [ ] Review Codex resuelto o LGTM.

## Riesgos conocidos

- **Migración en instalaciones existentes:** `ALTER TABLE
  projects ADD COLUMN ... NOT NULL DEFAULT 'normal'` es seguro en
  SQLite (crea la columna con default en todas las filas
  existentes). Mitigación: verificar el `_apply_sql_idempotent` de
  `setup.py` tras el PR-19 maneja bien DEFAULT values.
- **Adapters que no llaman a `get_effective_profile`:** si algún
  path de ejecución construye su propio `capability_profile` dict
  sin pasar por esa función, el bypass no aplica. Mitigación:
  revisar callers de `evaluate_runtime_event` (hoy son solo
  `claude_code.py` y `codex.py`) y dejar un comentario en
  `capability_service.py` marcando que **el único** sitio que
  mergea `autonomy_mode` es `get_effective_profile`.
- **Front: botón destructivo sin doble confirmación** — el modal
  de Mantine ya es suficiente, no se añade captcha ni password
  prompt.

## Notas para Claude Code

- LOC estimado: ~180 (migración 15, schema 5, capability_service
  40, app.py 25, types 2, ProjectDetail 60, tests 80, decisions
  3). Cae en S-M.
- Empezar por la migración + schema + get_effective_profile +
  tests (TDD). Luego adaptarlos endpoints y la UI al final.
- Commits pequeños: `feat: autonomy_mode migration and schema`,
  `feat: bypass approval gate in capability_service`,
  `feat: expose autonomy_mode via PATCH/GET projects`,
  `feat: ProjectDetail banner + switch for autonomy_mode`,
  `test: autonomy_mode coverage`,
  `docs: log autonomy_mode decision`.
- Invocar `codex-reviewer` al final sobre
  `git diff origin/v0.2...HEAD`.
