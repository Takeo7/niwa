# Niwa v1 — Orchestrator state

Estado operativo del orquestador v1. Cada entrada se añade tras el
merge de un PR. El campo `next_pr` indica el PR que debe arrancar la
siguiente sesión del orquestador.

```
pr_merged: PR-V1-21b
date: 2026-04-22
week: 6
next_pr: PR-V1-22
week_status: week-6-partial-awaiting-smoke-revalidation
blockers: []
```

## Historial

- **2026-04-22** — PR-V1-21b (Verification: structural needs_input
  detection) mergeado en `v1` vía squash (#130). Backend **138
  passed** (+5). **183 LOC netas** código+tests+fixtures bajo cap
  250. Cierra los 2 gaps del detector descubiertos en smoke
  post-PR-V1-21:
  - Task 11 (subtask "Add CI workflow"): texto final en imperativo
    "Let me know which direction you'd like." con `?` en párrafo
    previo — heurística `endswith("?")` lo perdía.
  - Task 12 (pregunta-forzada): Claude invocó `AskUserQuestion`
    tool_use con 3 opciones estructuradas; CLI denegó por
    non-interactive y emitió `permission_denials` en el
    `result` final.
  Fix introduce **3 señales en orden de prioridad**:
  1. **Primaria** — `AskUserQuestion` tool_use en `assistant`
     (top-level o embebido en `content[]`). Si match, devuelve
     `(needs_input, question)` + popula
     `evidence["ask_user_question_options"]` con las opciones
     del tool_input.
  2. **Secundaria** — `result.permission_denials` con
     `tool_name=="AskUserQuestion"`.
  3. **Fallback** — heurística mejorada: split por `\n\n`,
     cualquier párrafo acabando en `?` o `？` (fullwidth/español)
     → needs_input.
  `check_stream_termination` ahora acepta `evidence: dict | None`
  como kwarg; firma `tuple[str|None, str|None]` preservada.
  `verify_run` pasa `evidence=` (cambio mínimo 1 línea).
  Fixtures `stream_ask_user_question.json` +
  `stream_question_with_imperative.json` sintéticas basadas en
  payloads literales del brief (sandbox sin acceso a DB del
  smoke). Codex: LGTM. **Smoke pending** re-validación: task 11
  + task 12 deben terminar `waiting_input` con
  `pending_question` populada.
- **2026-04-22** — PR-V1-21 (Verification: detect open question
  with real CLI stream) mergeado en `v1` vía squash (#129).
  Backend **133 passed** (+3 nuevos; test 3 renombrado con nueva
  semántica `tool_use_incomplete`). **101 LOC netas**. Cierra el
  bug-corazón de task 6 del smoke: walk-back al último `assistant`
  ignorando `result` trailing. **Opción X aplicada**: 10 tests del
  baseline con fixtures sintéticos no-realistas actualizados.
  Codex: LGTM.
- **2026-04-22** — PR-V1-20 (Adapter: pass
  `--dangerously-skip-permissions` always) mergeado en `v1` vía
  squash (#128). Backend **130 passed** (+2). **97 LOC netas**
  bajo cap 150. FIX crítico: sin el flag, Claude CLI rechazaba
  tool_use para Write/Edit/Bash → 6/6 tasks con `no_artifacts`.
  Decisión de producto: flag siempre activo (safety en rama
  aislada + merge gate, no en adapter). `autonomy_mode` sigue
  controlando solo auto-merge post-finalize. Codex: LGTM + 1
  minor follow-up.
- **2026-04-21** — PR-V1-19 (Clarification round-trip:
  waiting_input + respond) mergeado en `v1` vía squash (#127).
  Backend **128 passed** (+4). Frontend **12 passed** (+2).
  **391 LOC netas** bajo cap. Cierra Semana 5 del SPEC §9.
  Codex: LGTM.
- **2026-04-21** — PR-V1-18 (Readiness endpoint + /system page)
  mergeado en `v1` vía squash (#126). Backend **124 passed**.
  Frontend 10 passed. **421 LOC netas** tras fix-up. Codex
  primera pasada: 1 blocker cerrado con
  `check_db_via_session`.
- **2026-04-21** — PR-V1-17 (Deploy local: static handler)
  mergeado (#125). Backend **118 passed**. **188 LOC netas**.
  Codex: LGTM.
- **2026-04-21** — FIX-20260421 (Config alignment templates ↔
  config.py) mergeado (#124). Backend **113 passed**. **192 LOC**.
  Codex: LGTM.
- **2026-04-21** — PR-V1-16 (Dangerous mode: auto-merge + UI
  banner) mergeado (#123). Backend 107, Frontend 8. **222 LOC**.
  Cierra Semana 4.
- **2026-04-21** — PR-V1-15 (Executor launcher +
  `niwa-executor` CLI) mergeado (#122). Backend 104. **377 LOC**.
  Codex: LGTM.
- **2026-04-21** — PR-V1-14 (Bootstrap.sh reproducible) mergeado
  (#121). Backend 94. **306 LOC**. Codex: LGTM.
- **2026-04-21** — PR-V1-13 (Safe mode) mergeado (#120). Backend
  89. **400 LOC exactos en cap**. Cierra Semana 3.
- **2026-04-21** — PR-V1-12b (Triage executor integration)
  mergeado (#119). Backend 83. **299 LOC**. Codex: LGTM.
- **2026-04-21** — PR-V1-12a (Triage module puro) mergeado (#118).
  Backend 81. **392 LOC**. Codex: LGTM.
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
  (#113). Frontend 6. **506 LOC**. Cierra Semana 2. Codex: LGTM.
- **2026-04-20** — PR-V1-09 (SSE endpoint) mergeado (#112).
  Backend 59. **541 LOC**. Codex: LGTM.
- **2026-04-20** — PR-V1-08 (Git workspace) mergeado (#111).
  Backend 56. **381 LOC**. Codex: LGTM.
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
