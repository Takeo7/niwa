# DOCS-20260419 — Handbook único de arquitectura, módulos y recetas

**Tipo:** DOCS (fuera del MVP-ROADMAP, post-MVP)
**Esfuerzo:** M-L (muchos ficheros que leer; texto fluye cuando hay mapa)
**Depende de:** ninguna
**Bloquea a:** ninguno — pero habilita que devs y LLMs nuevos
contribuyan sin tener que reconstruir el codebase a ojo

## Qué

Escribir un único `docs/HANDBOOK.md` (~600-900 líneas) que sea el punto
de entrada canónico para entender Niwa a nivel código, arquitectura y
extensiones. NO reemplaza los docs existentes; los indexa y complementa
con lo que falta: un mapa de módulos y recetas accionables para "cómo
añado X".

## Por qué

Hoy un humano o LLM nuevo que quiera contribuir tiene que:
- Leer `ARCHITECTURE.md` (diagrama containers, alto nivel, sin detalle de código).
- Leer `SPEC-v0.2.md` (qué hay congelado, pero no "dónde está cada cosa").
- Leer `state-machines.md` (contratos, sin implementación).
- Explorar `niwa-app/backend/*.py` (20 módulos) y
  `frontend/src/features/*` (12 features) fichero por fichero.
- Adivinar cómo se extiende algo (añadir backend nuevo, routine nueva,
  migration) sin referencia.

Resultado: onboarding de horas, contribuciones con scope mal definido,
LLMs que reinventan convenciones porque no las encuentran.

## Scope — fichero a crear

**Único fichero nuevo:** `docs/HANDBOOK.md`.

Estructura obligatoria (por secciones; el contenido exacto es juicio
del autor dentro de lo especificado):

### § 1 — Qué es Niwa (3 párrafos max)
Producto, no tecnología. Para qué sirve, para quién, qué NO es. Un
usuario no técnico debería poder leerlo.

### § 2 — Big picture
- Diagrama (reusar `docs/ARCHITECTURE.md §1`, extender si hace falta).
- Request flow end-to-end de los 3 caminos críticos:
  - **Tarea**: UI → `POST /api/tasks` → executor polling → routing →
    adapter → `backend_runs` + artifacts → auto-deploy → UI.
  - **Healthcheck**: scheduler tick → `product_healthcheck` routine →
    HTTP probe → strikes → tarea hija si 3 fallos.
  - **Rutina improve**: scheduler tick → `_exec_improve` → prompt
    templated → tarea hija con parent_task_id.

### § 3 — Data model
Tabla por tabla (solo las críticas, no las 30): `tasks`, `runs`,
`backend_runs`, `backend_run_events`, `routing_decisions`, `approvals`,
`artifacts`, `projects`, `deployments`, `oauth_tokens`, `routines`,
`backend_profiles`, `project_capability_profiles`.

Para cada una: propósito (1 línea), columnas clave (no todas), qué
invariante protege, migración de origen.

### § 4 — Backend module tour
Una línea por fichero de `niwa-app/backend/*.py`. Un párrafo extra
(3-5 líneas) para los 4 críticos: `app.py`, `tasks_service.py`,
`routing_service.py`, `scheduler.py`.

Mencionar los adapters de `niwa-app/backend/backend_adapters/`.

### § 5 — Frontend feature tour
Una línea por carpeta de `frontend/src/features/*` (approvals, chat,
dashboard, history, kanban, metrics, notes, projects, runs, settings,
system, tasks). Nombrar los componentes importantes.

### § 6 — Binarios del host
`bin/task-executor.py` (2164 LOC), `bin/hosting-server.py`,
`bin/update_engine.py`, `bin/niwa-mcp-smoke`. Una sección por cada uno:
qué hace, dónde se lanza, qué variables de entorno consume.

### § 7 — Installer (`setup.py`)
4069 LOC monolito. Mapa de las funciones principales (init, quick
install, migrations, systemd setup, smoke post-install, OpenClaw
integration) con anchor al rango de líneas. No transcribir — anchors
+ 1 línea cada una.

### § 8 — State machines
Resumen de 1 párrafo + link a `state-machines.md`. Incluir diagrama
ASCII simple de `tasks.status` transitions.

### § 9 — Extension recipes (la parte más valiosa)

Para cada receta: pasos numerados, ficheros a tocar con anchors,
invariantes a respetar, tests a añadir.

1. **Añadir un backend nuevo** (ej. Gemini).
   - Nuevo adapter en `backend_adapters/`.
   - Seed en `backend_registry.py`.
   - Capability descriptor.
   - Tests espejo a `test_claude_adapter_*`.
2. **Añadir una rutina con nuevo action_type**.
   - Migración para CHECK constraint.
   - Handler en `scheduler.py::_execute_routine`.
   - Schema en `RoutinesPanel.tsx`.
3. **Añadir una herramienta MCP al contrato**.
   - Definir en `config/mcp-contract/*.json`.
   - Implementar `_tool_*` en `assistant_service.py`.
   - Exponer en `app.py` bajo `/api/assistant/tools/*`.
   - Registrar en `servers/tasks-mcp/server.py`.
4. **Añadir una migración de schema**.
   - Regla: `schema.sql` = estado post-migración de fresh install.
   - Migración idempotente vía `_apply_sql_idempotent`.
   - Test en `tests/test_migration_NNN.py`.
5. **Añadir un endpoint API**.
   - Handler en `app.py` `handle_request()`.
   - Auth via `_require_auth` (cookie) o bearer s2s.
   - Test HTTP en `tests/test_*_endpoints.py`.
6. **Añadir una feature de UI**.
   - Carpeta en `frontend/src/features/*` con `components/` y `hooks/`.
   - Router en `src/app/Router.tsx`.
   - React Query hook contra endpoint API.
7. **Añadir un sub-tipo de `improve` (funcional/stability/security
   existen; ejemplo nuevo: `performance`)**.
   - Ampliar migración 016 CHECK.
   - Prompt templated en `scheduler.py::_exec_improve`.
   - Label en `RoutinesPanel.tsx`.
8. **Añadir un fake CLI fixture**.
   - Modelo: `tests/fixtures/fake_claude.py`,
     `tests/fixtures/fake_codex.py`.

### § 10 — Operativa
- Dónde viven los logs (systemd journal, `data/executor.log`,
  container logs).
- Comandos útiles: `niwa update`, `niwa install`, `niwa-mcp-smoke`,
  `pytest -q`, build frontend.
- Cómo debugear un executor que no arranca.
- Cómo rehacer el schema desde cero.
- Cómo ver qué routing decisión se tomó para una tarea.
- Cómo resetear solo la DB sin reinstalar todo.

### § 11 — Índice de docs complementarios
Una tabla con nombre + 1 línea de cuándo leer cada uno:
- `MVP-ROADMAP.md`, `ARCHITECTURE.md`, `SPEC-v0.2.md`,
  `state-machines.md`, `BUGS-FOUND.md`, `DECISIONS-LOG.md`,
  `RELEASE-RUNBOOK.md`, `PLAN-AUTH-SUBSCRIPTION.md`,
  ADRs 0001/0002, `archive/`.

## Fuera de scope (explícito)

- No reescribir `ARCHITECTURE.md`. No duplicar contenido — hacer link.
- No generar auto-docs desde código. Es prosa curada.
- No incluir ejemplos de llamadas HTTP o SQL reales — eso vive en los
  tests. El handbook apunta a los tests como ejemplos vivos.
- No reestructurar `docs/` ni mover ficheros.
- No documentar `docs/archive/` más allá de mencionar que existe.
- No documentar código legacy del frontend (`index-legacy.html`, etc).

## Tests

- **Nuevo:** `tests/test_handbook_integrity.py` — 3-5 tests de
  integridad sobre el fichero:
  - Existe `docs/HANDBOOK.md`.
  - Tiene las 11 secciones con sus `##` headers exactos.
  - Cada anchor `path/to/file.py:N` que declara apunta a un fichero
    existente (parsing simple de links, sin verificar la línea N).
  - `README.md` o `CLAUDE.md` linkean a `docs/HANDBOOK.md`.
- **Existentes que deben seguir verdes:** `test_pr00_docs.py` (si hace
  linting de docs) — asegurar que HANDBOOK.md no rompe su parseo.

## Criterio de hecho

- [ ] `docs/HANDBOOK.md` existe con las 11 secciones.
- [ ] Sección § 4 nombra los 20 módulos backend con una línea cada uno.
- [ ] Sección § 9 tiene las 8 recetas con anchors concretos a archivos
  existentes (parseables por el test de integridad).
- [ ] `CLAUDE.md` añade el handbook al índice de "Documentos de
  referencia" y una regla nueva: "Si tu PR añade/quita un módulo
  backend, una feature frontend, una tabla DB, o cambia un flujo
  end-to-end, actualiza `docs/HANDBOOK.md` en el mismo PR."
- [ ] `test_handbook_integrity.py` verde.
- [ ] `pytest -q` sin regresiones (≥1330 pass).
- [ ] Longitud del handbook entre 600 y 900 líneas (guía, no regla
  dura — si es 550 o 950 y está bien redactado, vale).

## Riesgos conocidos

- **Se pudre rápido.** La regla en CLAUDE.md mitiga, pero es
  blandita. A los 6 meses puede estar desfasado. Mitigación adicional:
  añadir al final del handbook una fecha "Última revisión de fondo:
  YYYY-MM-DD" y revisitar cada quarter.
- **Tentación de ser exhaustivo.** No lo seas. Si una sección tira a
  ~200 líneas, recorta. Priorizar "señal alta / 1 línea" sobre
  "exhaustivo / 10 líneas" en los tours de módulos.
- **Diagrama duplicado con ARCHITECTURE.md.** Aceptable: HANDBOOK
  tiene una versión más actual o comprimida; ARCHITECTURE queda como
  profundidad. Link explícito "para el detalle, ver ARCHITECTURE.md §X".
- **El scope crece hacia "añadir tests de X".** No. Los tests viven en
  cada PR, el handbook solo documenta cómo escribir un fake y dónde
  vive.

## Notas para Claude Code

- **Empieza leyendo** (en este orden) antes de escribir una palabra:
  1. `docs/ARCHITECTURE.md` completo.
  2. `docs/SPEC-v0.2.md` completo.
  3. `docs/state-machines.md` completo.
  4. `niwa-app/backend/app.py` (puede ser grande, skimmear).
  5. `niwa-app/backend/tasks_service.py` completo.
  6. `niwa-app/backend/routing_service.py` completo.
  7. `niwa-app/backend/scheduler.py` completo.
  8. `niwa-app/db/schema.sql` completo.
  9. Glob a `niwa-app/backend/*.py` para contar y listar módulos.
  10. Glob a `niwa-app/frontend/src/features/*/` para listar.
- Usa el subagente `Explore` (thoroughness=medium) para los módulos que
  no vas a leer entero — pide "dame 1 línea de qué hace y responsabilidad
  principal por fichero". No los leas todos a fondo tú.
- Este es un PR **sin cambios de código** — solo docs + 1 test + 1
  update a CLAUDE.md. Si te encuentras tentado a refactorizar algo,
  STOP y documéntalo como hallazgo para un FIX aparte.
- Codex reviewer aplica (PR M).
- Commit al abrir PR:
  ```
  docs: add HANDBOOK as single entry point for modules and recipes

  Adds docs/HANDBOOK.md (~700 lines) covering big picture, data model,
  backend/frontend tour, installer/executor map, extension recipes,
  and operational tips. CLAUDE.md gains a maintenance rule.
  test_handbook_integrity.py verifies structure and anchor validity.
  ```
