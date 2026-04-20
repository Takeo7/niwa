# Niwa v1 — Orchestrator state

Estado operativo del orquestador v1. Cada entrada se añade tras el
merge de un PR. El campo `next_pr` indica el PR que debe arrancar la
siguiente sesión del orquestador.

```
pr_merged: PR-V1-01
date: 2026-04-20
week: 1
next_pr: PR-V1-02
blockers: []
```

## Historial

- **2026-04-20** — PR-V1-01 (Skeleton FastAPI + React + SQLite)
  mergeado en `v1` vía squash (#103). Backend `pytest -q` → 1 passed.
  Frontend `vitest --run` → 0 tests collected. 585 LOC (sin lockfile)
  sobre el soft-limit de 400 LOC; aceptado por ser scaffolding puro
  declarativo explícitamente marcado S en el brief.
