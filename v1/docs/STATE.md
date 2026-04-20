# Niwa v1 — Orchestrator state

Estado operativo del orquestador v1. Cada entrada se añade tras el
merge de un PR. El campo `next_pr` indica el PR que debe arrancar la
siguiente sesión del orquestador.

```
pr_merged: PR-V1-04
date: 2026-04-20
week: 1
next_pr: PR-V1-05
blockers: []
```

## Historial

- **2026-04-20** — PR-V1-04 (Tasks CRUD API) mergeado en `v1` vía
  squash (#106). Backend `pytest -q` → 34 passed (+12 nuevos). 4
  endpoints REST (`GET/POST /api/projects/{slug}/tasks`,
  `GET/DELETE /api/tasks/{id}`); `POST` crea con `status=queued` y
  escribe 2 `task_events` (`created`, `status_changed null→queued`)
  en la misma transacción; `DELETE` bloquea estados activos con
  `409` y cascadea `task_events`. Codex: sin blockers/majors; nota
  menor sobre nullability de `description` (DB es NOT NULL, schema
  acepta None → se normaliza a `""`). Aceptado.
- **2026-04-20** — PR-V1-03 (Projects CRUD API) mergeado en `v1` vía
  squash (#105). Backend `pytest -q` → 22 passed (+11 nuevos). 5
  endpoints REST bajo `/api/projects`, schemas Pydantic v2 con
  validación de `slug`/`deploy_port`, service layer thin, `409` en
  slug duplicado, fixture con engine in-memory aislado por test.
  Codex: 1 `minor` (resolución de `updated_at` en `test_patch_project`,
  1 s de granularidad hace el assert `>=` trivial); no-blocker,
  follow-up si regresa.
- **2026-04-20** — PR-V1-02 (Data models + initial Alembic migration)
  mergeado en `v1` vía squash (#104). Backend `pytest -q` → 11 passed
  (1 health + 10 modelos). Codex-reviewer marcó 3 `major` + 1 `minor`
  en primera pasada: test de migración con false-green, mutación de
  la dev DB, e índices de FK faltantes. Fix-up sobre la misma rama
  resolvió los 4 hallazgos antes del merge (env.py lee `-x db_url`,
  tests usan `tmp_path`, 5 índices `ix_*` añadidos con reversibilidad
  y test de presencia).
- **2026-04-20** — PR-V1-01 (Skeleton FastAPI + React + SQLite)
  mergeado en `v1` vía squash (#103). Backend `pytest -q` → 1 passed.
  Frontend `vitest --run` → 0 tests collected. 585 LOC (sin lockfile)
  sobre el soft-limit de 400 LOC; aceptado por ser scaffolding puro
  declarativo explícitamente marcado S en el brief.
