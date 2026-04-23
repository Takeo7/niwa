# Niwa — Orchestrator state

Estado operativo final del MVP Niwa. Tras el rename de ramas
(`v1 → main`, antiguo `main → legacy`), `main` es la rama oficial
del MVP.

```
pr_merged: PR-V1-26
date: 2026-04-23
week: 6
next_pr: (none)
week_status: MVP-COMPLETE-POLISHED
blockers: []
```

## Historial

- **2026-04-23** — PR-V1-26 (Onboarding polish for fresh install)
  mergeado en `main` vía squash (#135). Backend **152 passed**
  (+1 regression). Frontend 12 sin cambios. **127 LOC netas
  código+tests** + 139 LOC de docs bajo cap 200. Cierra los 5
  bloqueadores duros del smoke de install fresca 2026-04-22:
  (1) `bootstrap.sh` ahora prefiere `python3.11` sobre `python3`
  (brew macOS); (2) mensaje final del bootstrap accionable con
  `source venv + niwa-executor start + make dev`, sin
  referencias internas a PR-V1-15 ni paths absolutos; (3-5)
  README reescrito con prereqs enumerados con comandos literales
  (brew/apt/npm), sección "First project" con 4 pasos E2E,
  "Known limitations (v1.0)". Nuevo
  `docs/plans/FOUND-20260422-onboarding.md` con 4 fricciones
  diferidas a v1.1 (7, 8, 9, 10: stop-no-kills-make-dev,
  per-clone isolation, plist huérfano, make dev-daemon). Test
  `test_bootstrap_prefers_python311` regression. Codex primera
  pasada: 1 major (test con env curado sin heredar
  SSL/certs/proxies) — cerrado con `env = os.environ.copy()` en
  fix-up. MVP ahora listo para install fresca sin fricción.
- **2026-04-22** — Rename de ramas ejecutado por el humano:
  `v1 → main` (default), antiguo `main → legacy`, `v0.2`
  preservada. Fase 4 del PR-V1-25 completada.
- **2026-04-22** — PR-V1-25 (Promote v1 to root + cleanup legacy
  + branch switch) mergeado en `v1` vía squash (#134). PR de
  release final. 508 ficheros tocados: +157 / −102,200. Movió
  `v1/*` a raíz con `git mv`, borró v0.2 legacy (`niwa-app/`,
  `bin/`, `servers/`, `setup.py`, etc). Tests post-promoción:
  151 backend + 12 frontend. Codex: 4 blockers + 2 majors
  cerrados con fix-up (bootstrap REPO_DIR, templates v1/backend
  hardcoded, CLAUDE.md raíz con rutas rotas, test sin assert,
  niwa_cli error message, docstrings).
- **2026-04-22** — PR-V1-23 (Parent task semantics: promote on
  subtasks terminal) mergeado (#133). Backend **151 passed**.
  **262 LOC netas**. Madre de split queda `running`;
  `_maybe_promote_parent` agrega cuando todas las hijas
  terminales. Hook en `_finalize` Y `_finalize_triage_failure`.
- **2026-04-22** — PR-V1-22 (Resume via session_handle + user
  response prompt) mergeado (#132). Backend **147 passed**.
  **290 LOC netas**. Adapter expone `session_id`; executor
  detecta resume path; spawnea adapter con `--resume <handle>` +
  prompt=respuesta del usuario. Fix-up codex: dead code
  `had_pending_question`.
- **2026-04-22** — PR-V1-24 (Git workspace: branch from default,
  not current HEAD) mergeado (#131). Backend **142 passed**.
  Rama nace desde default branch, no HEAD actual.
- **2026-04-22** — PR-V1-21b (Verification: structural
  needs_input detection) mergeado (#130). Backend **138 passed**.
  3 señales: AskUserQuestion tool_use → permission_denials →
  paragraph scan.
- **2026-04-22** — PR-V1-21 (Verification: detect open question
  with real CLI stream) mergeado (#129). Backend **133 passed**.
  Walk-back al último assistant ignorando result trailing.
- **2026-04-22** — PR-V1-20 (Adapter: always pass
  `--dangerously-skip-permissions`) mergeado (#128). Backend
  **130 passed**. Safety en rama aislada + merge gate.
- **2026-04-21** — PR-V1-19 (Clarification round-trip:
  waiting_input + respond) mergeado (#127). Backend **128**,
  Frontend **12 passed**. Cierra Semana 5.
- **2026-04-21** — PR-V1-18 (Readiness endpoint + /system page)
  mergeado (#126).
- **2026-04-21** — PR-V1-17 (Deploy local static handler)
  mergeado (#125).
- **2026-04-21** — FIX-20260421 (Config alignment templates ↔
  config.py) mergeado (#124).
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
- **2026-04-21** — PR-V1-11c (Verification E5 project tests
  runner) mergeado (#116).
- **2026-04-21** — PR-V1-11b (Verification E3+E4 artifact
  scanning) mergeado (#115).
- **2026-04-21** — PR-V1-11a (Verification E1+E2 + skeleton)
  mergeado (#114).
- **2026-04-21** — PR-V1-11 original marcado **superseded** por
  11a+11b+11c.
- **2026-04-20** — PR-V1-10 (UI task detail con stream) mergeado
  (#113). Cierra Semana 2.
- **2026-04-20** — PR-V1-09 (SSE endpoint para run events)
  mergeado (#112).
- **2026-04-20** — PR-V1-08 (Git workspace: branch per task)
  mergeado (#111).
- **2026-04-20** — PR-V1-07 (Claude Code adapter stream-json)
  mergeado (#110).
- **2026-04-20** — PR-V1-06b (UI tasks list + create + delete +
  polling) mergeado (#109).
- **2026-04-20** — PR-V1-06a (UI shell + routing + projects CRUD)
  mergeado (#108).
- **2026-04-20** — PR-V1-06 original marcado **superseded** por
  06a+06b.
- **2026-04-20** — PR-V1-05 (Executor echo daemon) mergeado
  (#107). Cierra Semana 1.
- **2026-04-20** — PR-V1-04 (Tasks CRUD API) mergeado (#106).
- **2026-04-20** — PR-V1-03 (Projects CRUD API) mergeado (#105).
- **2026-04-20** — PR-V1-02 (Data models + initial Alembic
  migration) mergeado (#104). Codex 3 majors + 1 minor resueltos
  en fix-up.
- **2026-04-20** — PR-V1-01 (Skeleton FastAPI + React + SQLite)
  mergeado (#103). 585 LOC scaffolding.
