# Base de datos inicial de Desk

## Elección

Primera versión con SQLite local en el VPS.

Motivos:
- simple
- robusta
- fácil de backup
- suficiente para un MVP personal

## Tablas clave

- `projects`
- `tasks`
- `task_labels`
- `task_events`
- `day_focus`
- `day_focus_tasks`
- `calendar_events`
- `task_calendar_links`
- `inbox_items`

## Decisiones

- las tareas viven en una sola tabla con `area` y `project_id`
- `My Day` no duplica tareas: selecciona tareas del día en `day_focus_tasks`
- calendario y tareas se enlazan sin mezclarlos en la misma tabla
- el inbox sirve para capturas rápidas y material aún no triado

## Evolución futura

Más adelante se puede migrar a PostgreSQL si Desk crece mucho, pero para la primera fase SQLite tiene más sentido.
