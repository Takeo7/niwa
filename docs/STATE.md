# Niwa v1 — Orchestrator state

Estado operativo del orquestador v1. Cada entrada se añade tras el
merge de un PR. El campo `next_pr` indica el PR que debe arrancar la
siguiente sesión del orquestador.

```
pr_merged: PR-V1-23
date: 2026-04-22
week: 6
next_pr: PR-V1-25
week_status: week-6-closed-awaiting-final-smoke
blockers: []
```

## Historial

- **2026-04-22** — PR-V1-23 (Parent task semantics: promote on
  subtasks terminal) mergeado en `v1` vía squash (#133). Backend
  **151 passed** (+4). **262 LOC netas** código+tests tras fix-up
  (240 inicial + 22 por blocker codex real). Cierra bug visual
  del smoke: madre de split quedaba `done` tras `_apply_split`
  aunque las hijas no hubiesen terminado. Fix: madre queda
  `running` tras split; `_maybe_promote_parent` agrega estado
  cuando todas las hijas son terminales (`done`/`failed`/
  `cancelled`). Reglas: alguna `failed` → `failed`; todas `done`
  → `done`; alguna `cancelled` sin `failed` → `cancelled`.
  Idempotente (check `parent.status in TERMINAL` antes de
  mutar). Hook en `_finalize` Y `_finalize_triage_failure`
  (fix-up codex major: sin el segundo, hijas que fallaban en
  triage dejaban parent `running` indefinidamente). Codex: LGTM
  tras fix-up. 3 minors resueltos (test assertion, docstring,
  datetime aware).
- **2026-04-22** — PR-V1-22 (Resume via session_handle + user
  response prompt) mergeado en `v1` vía squash (#132). Backend
  **147 passed** (+5). **290 LOC netas** código+tests+fixtures
  bajo cap 300. Cierra el "known limitation" de PR-V1-19:
  - `ClaudeCodeAdapter.__init__` acepta `resume_handle: str |
    None` kwarg; `session_id` propiedad populada del primer
    `system/init` event.
  - `run.session_handle` persistido tras cada run (incluso
    failed, para que siguiente resume encuentre el handle).
  - Executor detecta task queued viniendo de waiting_input via
    helpers `_last_user_response_event` + `_last_run_with_session_handle`.
    Si ambos no-None: spawnea adapter con `resume_handle` +
    `prompt = texto del user_response` (NO title/description).
    Fallback graceful con logger.warning si falta handle previo.
  - Adapter añade `--resume <handle>` a argv cuando kwarg set.
  - Fake CLI extendido con `FAKE_CLAUDE_SESSION_ID`.
  - `respond_to_task` ya estaba normalizado desde PR-V1-19
    (payload `{"event":"user_response","text":...}`).
  Codex: 1 major + 2 minors. Major (dead code
  `had_pending_question` en `_finalize` — `respond_to_task` ya
  limpia pending_question atómicamente) cerrado con eliminación.
  Minors (circuit breaker session expirada + filter
  `_last_user_response_text` por status_changed) documentados
  como follow-up.
- **2026-04-22** — PR-V1-24 (Git workspace: branch from default,
  not current HEAD) mergeado en `v1` vía squash (#131). Backend
  **142 passed** (+4). **148 LOC netas** bajo cap 150 (margen 2).
  Cierra bug del smoke: task 12 heredó commit de LICENSE de
  task 10 porque rama nació desde HEAD actual del checkout
  (task-11-*), no desde master. Fix: `_detect_default_branch`
  con orden `origin/HEAD` → `main` → `master` → primera rama →
  `GitWorkspaceError`. `prepare_task_branch` hace `checkout
  <default>` antes de `checkout -b branch_name` en path de rama
  nueva; path existente intacto (idempotencia preservada). Tests
  usan bare+clone real para verificar `origin/HEAD`. Codex: LGTM.
- **2026-04-22** — PR-V1-21b (Verification: structural
  needs_input detection) mergeado en `v1` vía squash (#130).
  Backend **138 passed** (+5). **183 LOC netas**. 3 señales en
  orden: AskUserQuestion tool_use → permission_denials →
  paragraph scan con `?`/`？`. Cierra gaps detector del smoke
  (tasks 11 + 12). Codex: LGTM.
- **2026-04-22** — PR-V1-21 (Verification: detect open question
  with real CLI stream) mergeado (#129). Backend **133 passed**.
  **101 LOC netas**. Walk-back al último assistant ignorando
  result trailing. **Opción X aplicada**: 10 tests baseline con
  fixtures sintéticos no-realistas actualizados.
- **2026-04-22** — PR-V1-20 (Adapter: pass
  `--dangerously-skip-permissions` always) mergeado (#128).
  Backend **130 passed**. **97 LOC netas** bajo cap 150. FIX
  crítico smoke: flag siempre activo (safety en rama aislada +
  merge gate, no en adapter).
- **2026-04-21** — PR-V1-19 (Clarification round-trip:
  waiting_input + respond) mergeado (#127). Backend **128**,
  Frontend **12 passed**. **391 LOC**. Cierra Semana 5.
- **2026-04-21** — PR-V1-18 (Readiness endpoint + /system page)
  mergeado (#126). Backend **124**, Frontend 10. **421 LOC** tras
  fix-up blocker.
- **2026-04-21** — PR-V1-17 (Deploy local static handler)
  mergeado (#125). Backend **118**. **188 LOC**. Codex: LGTM.
- **2026-04-21** — FIX-20260421 (Config alignment) mergeado
  (#124). Backend **113**. **192 LOC**.
- **2026-04-21** — PR-V1-16 (Dangerous mode auto-merge) mergeado
  (#123). Backend 107, Frontend 8. **222 LOC**. Cierra Semana 4.
- **2026-04-21** — PR-V1-15 (Executor launcher CLI) mergeado
  (#122). Backend 104. **377 LOC**.
- **2026-04-21** — PR-V1-14 (Bootstrap.sh reproducible) mergeado
  (#121). Backend 94. **306 LOC**.
- **2026-04-21** — PR-V1-13 (Safe mode) mergeado (#120). Backend
  89. **400 LOC**. Cierra Semana 3.
- **2026-04-21** — PR-V1-12b (Triage executor integration)
  mergeado (#119). Backend 83. **299 LOC**.
- **2026-04-21** — PR-V1-12a (Triage module puro) mergeado (#118).
  Backend 81. **392 LOC**.
- **2026-04-21** — PR-V1-12 original marcado **superseded** por
  12a+12b.
- **2026-04-21** — PR-V1-11c (Verification E5) mergeado (#116).
  77. **380 LOC** tras fix-up.
- **2026-04-21** — PR-V1-11b (Verification E3+E4) mergeado (#115).
  72. **499 LOC** tras fix-up (blocker E4 embedded tool_use).
- **2026-04-21** — PR-V1-11a (Verification E1+E2 + skeleton)
  mergeado (#114). 65. **387 LOC**. Codex: LGTM.
- **2026-04-21** — PR-V1-11 original marcado **superseded** por
  11a+11b+11c.
- **2026-04-20** — PR-V1-10 (UI task detail con stream) mergeado
  (#113). Frontend 6. **506 LOC**. Cierra Semana 2.
- **2026-04-20** — PR-V1-09 (SSE endpoint) mergeado (#112).
  Backend 59. **541 LOC**.
- **2026-04-20** — PR-V1-08 (Git workspace) mergeado (#111).
  Backend 56. **381 LOC**.
- **2026-04-20** — PR-V1-07 (Claude Code adapter) mergeado
  (#110). Backend 50. **925 LOC** (opción A por brief
  inconsistente).
- **2026-04-20** — PR-V1-06b (UI tasks) mergeado (#109). Frontend
  4. 571 LOC.
- **2026-04-20** — PR-V1-06a (UI shell + projects) mergeado
  (#108). Frontend 2. 524 LOC.
- **2026-04-20** — PR-V1-06 original marcado **superseded** por
  06a+06b.
- **2026-04-20** — PR-V1-05 (Executor echo daemon) mergeado
  (#107). Backend 44. Cierra Semana 1.
- **2026-04-20** — PR-V1-04 (Tasks CRUD API) mergeado (#106).
  Backend 34.
- **2026-04-20** — PR-V1-03 (Projects CRUD API) mergeado (#105).
  Backend 22.
- **2026-04-20** — PR-V1-02 (Data models + Alembic) mergeado
  (#104). Backend 11. Codex 3 majors + 1 minor resueltos en
  fix-up.
- **2026-04-20** — PR-V1-01 (Skeleton) mergeado (#103). Backend 1.
  585 LOC scaffolding.
