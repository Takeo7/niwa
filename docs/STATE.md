# Niwa — Orchestrator state

Estado operativo de Niwa post-MVP. `main` es la rama oficial.
Ciclo v1.1 en curso (Tier 1 fricciones de uso real).

```
pr_merged: PR-V1-29
date: 2026-04-25
week: v1.1
next_pr: PR-V1-30
week_status: v1.1-tier-1-in-flight
blockers: []
```

## Historial

- **2026-04-25** — PR-V1-29 (Actionable error when no default
  branch detected) mergeado en `main` vía squash (#138). Backend
  **153 passed** (+1 nuevo). **22 LOC** ≤ cap S 50. Cambia el
  mensaje de `_detect_default_branch` cuando no hay default
  detectada: ahora incluye `git remote set-head origin -a`
  (clone) y `git commit -m init` (repo nuevo) como sugerencias
  accionables. Cierra fricción del smoke 2026-04-25 con la
  pareja del autor (recibió `git_setup_failed: no default
  branch detected` y no supo qué hacer). Codex: LGTM.
- **2026-04-25** — PR-V1-28 (In-app help + first-project
  guidance) mergeado en `main` vía squash (#137). Frontend **14
  passed**. Backend 152 sin cambios. **85 LOC código+tests** sin
  contenido estático del help. Empty state + página /help +
  helper text bajo local_path. Codex: LGTM.
- **2026-04-23** — PR-V1-27 (docs: clarify Python install on
  Ubuntu 24.04+ python3-venv) mergeado (#136) directo por el
  humano. Pequeño doc fix.
- **2026-04-23** — PR-V1-26 (Onboarding polish for fresh install)
  mergeado en `main` vía squash (#135). Backend **152 passed**.
  Cierra los 5 bloqueadores duros del smoke de install fresca
  2026-04-22. Codex: 1 major (env curado en test) cerrado en
  fix-up.
- **2026-04-22** — Rename de ramas ejecutado por el humano:
  `v1 → main` (default), antiguo `main → legacy`, `v0.2`
  preservada. Fase 4 del PR-V1-25 completada.
- **2026-04-22** — PR-V1-25 (Promote v1 to root + cleanup legacy
  + branch switch) mergeado en `v1` vía squash (#134). PR de
  release final. Codex: 4 blockers + 2 majors cerrados en
  fix-up.
- **2026-04-22** — PR-V1-23 (Parent task semantics) mergeado
  (#133). Backend **151 passed**.
- **2026-04-22** — PR-V1-22 (Resume via session_handle) mergeado
  (#132). Backend **147 passed**.
- **2026-04-22** — PR-V1-24 (Git workspace: branch from default)
  mergeado (#131). Backend **142 passed**.
- **2026-04-22** — PR-V1-21b (Verification: structural
  needs_input) mergeado (#130). Backend **138 passed**.
- **2026-04-22** — PR-V1-21 (Verification: open question real
  CLI stream) mergeado (#129). Backend **133 passed**.
- **2026-04-22** — PR-V1-20 (Adapter:
  --dangerously-skip-permissions) mergeado (#128). Backend
  **130 passed**.
- **2026-04-21** — PR-V1-19 (Clarification round-trip) mergeado
  (#127). Backend **128**, Frontend **12 passed**. Cierra
  Semana 5.
- **2026-04-21** — PR-V1-18 (Readiness endpoint + /system page)
  mergeado (#126).
- **2026-04-21** — PR-V1-17 (Deploy local static handler)
  mergeado (#125).
- **2026-04-21** — FIX-20260421 (Config alignment) mergeado
  (#124).
- **2026-04-21** — PR-V1-16 (Dangerous mode auto-merge) mergeado
  (#123). Cierra Semana 4.
- **2026-04-21** — PR-V1-15 (Executor launcher `niwa-executor`
  CLI) mergeado (#122).
- **2026-04-21** — PR-V1-14 (Bootstrap.sh reproducible) mergeado
  (#121).
- **2026-04-21** — PR-V1-13 (Safe mode: commit+push+gh pr create)
  mergeado (#120). Cierra Semana 3.
- **2026-04-21** — PR-V1-12b (Triage executor integration)
  mergeado (#119).
- **2026-04-21** — PR-V1-12a (Triage module puro) mergeado (#118).
- **2026-04-21** — PR-V1-12 original marcado **superseded** por
  12a+12b.
- **2026-04-21** — PR-V1-11c (Verification E5) mergeado (#116).
- **2026-04-21** — PR-V1-11b (Verification E3+E4) mergeado
  (#115).
- **2026-04-21** — PR-V1-11a (Verification E1+E2 + skeleton)
  mergeado (#114).
- **2026-04-21** — PR-V1-11 original marcado **superseded** por
  11a+11b+11c.
- **2026-04-20** — PR-V1-10 (UI task detail con stream) mergeado
  (#113). Cierra Semana 2.
- **2026-04-20** — PR-V1-09 (SSE endpoint) mergeado (#112).
- **2026-04-20** — PR-V1-08 (Git workspace) mergeado (#111).
- **2026-04-20** — PR-V1-07 (Claude Code adapter stream-json)
  mergeado (#110).
- **2026-04-20** — PR-V1-06b (UI tasks list) mergeado (#109).
- **2026-04-20** — PR-V1-06a (UI shell + projects) mergeado
  (#108).
- **2026-04-20** — PR-V1-06 original marcado **superseded** por
  06a+06b.
- **2026-04-20** — PR-V1-05 (Executor echo daemon) mergeado
  (#107). Cierra Semana 1.
- **2026-04-20** — PR-V1-04 (Tasks CRUD API) mergeado (#106).
- **2026-04-20** — PR-V1-03 (Projects CRUD API) mergeado (#105).
- **2026-04-20** — PR-V1-02 (Data models + initial Alembic
  migration) mergeado (#104). Codex 3 majors + 1 minor en
  fix-up.
- **2026-04-20** — PR-V1-01 (Skeleton) mergeado (#103). 585 LOC
  scaffolding.
