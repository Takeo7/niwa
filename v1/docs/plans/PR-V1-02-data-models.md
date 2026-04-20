# PR-V1-02 — Data models + initial Alembic migration

**Semana:** 1
**Esfuerzo:** M
**Depende de:** PR-V1-01

## Qué

Declarar los 5 modelos SQLAlchemy 2.x del SPEC §3 (`projects`,
`tasks`, `task_events`, `runs`, `run_events`) y generar la migración
Alembic inicial que cree todas las tablas con sus FKs, índices y
CHECK constraints de estado. Cero endpoints, cero lógica: solo schema
y tests de integridad.

## Por qué

SPEC §9 Semana 1 pide "DB + CRUD proyectos/tareas". Los PRs
siguientes (CRUD de proyectos, CRUD de tareas, executor) necesitan
tablas reales donde escribir. Este PR pone la base declarativa sin
mezclarla con rutas HTTP.

## Scope — archivos que toca

- `v1/backend/app/models/__init__.py` (nuevo, re-exporta `Base` y
  modelos)
- `v1/backend/app/models/project.py` (`Project`)
- `v1/backend/app/models/task.py` (`Task`, con `parent_task_id`
  self-FK nullable)
- `v1/backend/app/models/task_event.py` (`TaskEvent`)
- `v1/backend/app/models/run.py` (`Run`)
- `v1/backend/app/models/run_event.py` (`RunEvent`)
- `v1/backend/app/db.py` (importa los modelos para registrarlos en
  `Base.metadata`; activa `PRAGMA foreign_keys=ON` en SQLite)
- `v1/backend/migrations/env.py` (importa `Base.metadata` para
  autogenerate)
- `v1/backend/migrations/versions/<timestamp>_initial_schema.py`
  (migración revisada a mano tras autogenerate)
- `v1/backend/tests/test_models.py` (nuevo; ver §Tests)
- `v1/docs/HANDBOOK.md` (sección "Data model" añadida)

## Fuera de scope (explícito)

- No hay endpoints REST. `projects` llega en PR-V1-03, `tasks` en
  PR-V1-04.
- No hay executor. PR-V1-05.
- No hay máquina de estados. Los estados se declaran como CHECK
  constraint de columna; las transiciones las valida el servicio
  que las escribe, en PR posterior.
- No hay fixtures ni seed data.
- `payload_json` y `verification_json` son `TEXT` con JSON serializado
  por el caller. Sin tipo JSON nativo (SQLite no lo necesita).

## Dependencias nuevas

- Python: ninguna (sqlalchemy>=2 y alembic ya en `pyproject.toml`).
- npm: ninguna.

## Tests

- **Nuevos:** `v1/backend/tests/test_models.py`:
  1. `test_project_defaults` — crear un `Project` sin pasar
     `autonomy_mode`; debe ser `"safe"`.
  2. `test_task_fk_project` — borrar el `Project` borra sus `Task`s
     (ondelete CASCADE).
  3. `test_task_self_fk` — `Task` con `parent_task_id` apuntando a
     otra `Task` existente se crea; FK inválida falla.
  4. `test_task_status_check` — `Task.status` fuera del conjunto
     SPEC §3 falla con `IntegrityError`.
  5. `test_task_event_fk` — `TaskEvent` con `task_id` válido OK,
     inválido falla.
  6. `test_run_status_default` — `Run.status` sin pasar valor es
     `"queued"`.
  7. `test_run_event_fk` — `RunEvent` con `run_id` válido OK.
  8. `test_alembic_upgrade_creates_tables` — tras
     `alembic upgrade head` en SQLite temporal, `Base.metadata`
     refleja las 5 tablas esperadas por nombre.
- **Frontend:** ninguno.
- **Baseline tras PR:** backend 1 (PR-V1-01) + 8 nuevos = **9
  passed**.

## Criterio de hecho

- [ ] `cd v1/backend && alembic upgrade head` aplica la migración
  sin error sobre `data/niwa-v1.sqlite3`.
- [ ] `alembic downgrade base` deja la DB vacía.
- [ ] `alembic current` reporta el revision id esperado.
- [ ] `pytest -q` en `v1/backend/` → 9 passed.
- [ ] `sqlite3 data/niwa-v1.sqlite3 '.schema projects'` muestra
  columnas y CHECK de `autonomy_mode`.
- [ ] `v1/docs/HANDBOOK.md` documenta las 5 tablas con 1-2 líneas
  cada una.

## Riesgos conocidos

- **SQLite + FK.** Hay que emitir `PRAGMA foreign_keys=ON` por
  conexión (event listener en `db.py`), si no las CASCADE/RESTRICT
  se ignoran silenciosamente.
- **CHECK constraints con SQLAlchemy.** Usar `sa.CheckConstraint`
  explícito en `__table_args__`, no `sa.Enum` (SQLite no lo soporta
  como ENUM nativo y rompe el autogenerate).
- **Alembic autogenerate con SQLite.** El `env.py` ya lleva
  `render_as_batch=True` desde PR-V1-01; verificarlo.

## Notas para Claude Code

- Un commit por modelo más uno para la migración y otro para los
  tests: `feat(v1): project model`, `feat(v1): task model`, …,
  `feat(v1): initial alembic migration`, `test(v1): data model
  integrity`.
- Revisa la migración autogenerada a mano — suele incluir ruido
  (comentarios, orden de columnas). Límpiala antes de commitear.
- `Task.parent_task_id` self-FK: usa `ondelete='CASCADE'`. Al borrar
  una tarea raíz, sus subtareas se van con ella (consistente con el
  SPEC §4 donde el split genera subtareas que solo tienen sentido
  dentro del padre).
- `created_at` y `updated_at` con `server_default=func.now()`.
  `updated_at` con `onupdate=func.now()`.
- No crees `__repr__` ni helpers; los modelos son datos, no
  comportamiento.
- Esfuerzo M → el orquestador correrá `codex-reviewer` antes de
  mergear.
