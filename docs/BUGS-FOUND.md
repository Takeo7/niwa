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

**Descripcion:** `schema.sql` define las tablas `day_focus`, `day_focus_tasks`, `task_labels`, `task_metrics` y `kanban_columns`, pero la migracion `004_cleanup.sql` las elimina con `DROP TABLE IF EXISTS`. El schema.sql no refleja el estado real post-migraciones para estas tablas.
**Ubicacion:** `niwa-app/db/schema.sql` (tablas day_focus, day_focus_tasks, task_labels, task_metrics, kanban_columns) y `niwa-app/db/migrations/004_cleanup.sql`.
**Severidad:** bajo.
**PR futuro donde se arreglara:** pendiente de asignar (limpieza de schema.sql para alinear con estado post-migraciones).
