# Bugs preexistentes encontrados fuera del scope de cada PR

Cada entrada: fecha, PR donde se encontró, descripción, ubicación, severidad.

Formato sugerido:

```
## YYYY-MM-DD — encontrado durante PR-XX

**Descripción:** qué está mal.
**Ubicación:** archivo:línea o componente.
**Severidad:** crítico | alto | medio | bajo.
**PR futuro donde se arreglará:** PR-XX o "pendiente de asignar".
```

---

## 2026-04-12 — encontrado durante PR-01

### Bug 1: Migración 004 viola invariante — borra tablas que schema.sql define

**Descripción:** `schema.sql` define las tablas `day_focus`, `day_focus_tasks`, `task_labels`, `task_metrics` y `kanban_columns`, pero la migración `004_cleanup.sql` las elimina con `DROP TABLE IF EXISTS`. `schema.sql` no refleja el estado real post-migraciones para estas tablas. Viola la invariante adoptada: "schema.sql representa el estado post-migración de un fresh install."
**Ubicación:** `niwa-app/db/schema.sql` (tablas day_focus, day_focus_tasks, task_labels, task_metrics, kanban_columns) y `niwa-app/db/migrations/004_cleanup.sql`.
**Severidad:** media.
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de schema.sql).

### Bug 2: Migración 003 viola invariante — deployments no está en schema.sql

**Descripción:** La migración `003_deployments.sql` crea la tabla `deployments`, pero `schema.sql` no la incluye. Un fresh install que solo aplique `schema.sql` no tendrá esta tabla. Viola la invariante: las migraciones que añaden tablas deben reflejarse en schema.sql.
**Ubicación:** `niwa-app/db/migrations/003_deployments.sql` define `deployments`; `niwa-app/db/schema.sql` no la incluye.
**Severidad:** media.
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de schema.sql).

### Bug 3: Migración 005 viola invariante — idx_settings_key no está en schema.sql

**Descripción:** La migración `005_services_and_settings_unify.sql` crea el índice `idx_settings_key`, pero `schema.sql` no lo incluye. Viola la invariante: las migraciones que añaden índices deben reflejarse en schema.sql.
**Ubicación:** `niwa-app/db/migrations/005_services_and_settings_unify.sql` define `idx_settings_key`; `niwa-app/db/schema.sql` no lo incluye.
**Severidad:** media.
**PR futuro donde se arreglará:** pendiente de asignar (PR de limpieza de schema.sql).

## 2026-04-13 — encontrado durante PR-02

### Bug 4: Datos preexistentes con `status='revision'` que semánticamente deberían ser `waiting_input`

**Descripción:** Antes de PR-02, `task_request_input` (MCP tool) escribía `status='revision'` cuando el agente necesitaba input humano. El status correcto es `waiting_input` (corregido en PR-02). Cualquier base de datos de producción creada antes de PR-02 puede tener tareas con `status='revision'` que semánticamente representan solicitudes de input, no revisiones de deliverables.
**Ubicación:** Tabla `tasks`, filas donde `status='revision'` y la timeline contiene un evento `type='alerted'` con `author='claude'`.
**Severidad:** baja (no hay instancias de producción con datos afectados al momento de PR-02).
**PR futuro donde se arreglará:** pendiente de asignar — cleanup operacional manual, no migración automática.

## 2026-04-13 — encontrado durante PR-04

### Bug 5: test_e2e.py::test_executor falla porque asume BD runtime disponible

**Descripción:** `tests/test_e2e.py::test_executor` intenta abrir la base de datos de la aplicación (`/instance/niwa-app/data/niwa.sqlite3`) directamente. Ese path no existe en entornos de CI/test. El test fue diseñado para correr contra una instancia viva, no en un entorno aislado. Confirmado preexistente en commit `8130acf` (pre-PR-04).
**Ubicación:** `tests/test_e2e.py:19` — `sqlite3.connect(DB, timeout=10)` donde `DB` apunta a la ruta de producción.
**Severidad:** baja (no afecta funcionalidad, solo la suite de tests en CI).
**PR futuro donde se arreglará:** pendiente de asignar (PR-12 reescribe tests).
