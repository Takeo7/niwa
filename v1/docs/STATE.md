# Niwa v1 — Orchestrator state

Estado operativo del orquestador v1. Cada entrada se añade tras el
merge de un PR. El campo `next_pr` indica el PR que debe arrancar la
siguiente sesión del orquestador.

```
pr_merged: PR-V1-21
date: 2026-04-22
week: 6
next_pr: PR-V1-22
week_status: week-6-partial-awaiting-smoke-validation
blockers: []
```

## Historial

- **2026-04-22** — PR-V1-21 (Verification: detect open question
  with real CLI stream) mergeado en `v1` vía squash (#129).
  Backend **133 passed** (+3 nuevos: result-after-assistant,
  answer-after-assistant, plumbing-only; +1 test 3 renombrado
  con nueva semántica). **101 LOC netas** código+tests+fixture
  bajo cap 250. Cierra el bug-corazón detectado en smoke real
  2026-04-22 (task 6, "fallar"): `check_stream_termination`
  tomaba el último evento semántico, pero el CLI real SIEMPRE
  emite `result` final independiente del contenido → la rama de
  detección de `?` final nunca se ejecutaba, riesgo de
  false-positive `done`. Rewrite: walk-back al último
  `assistant` ignorando `result`/`user`/`tool_use`/`system`
  trailing. Nueva fixture `stream_real_question.json` como
  regression guardrail. **Opción X aplicada**: 10 tests del
  baseline cuyos fixtures sintéticos no eran realistas (no
  emitían `assistant` antes del `result`, o usaban `content:
  "hi"` string en vez de array) actualizados para reflejar el
  formato real del CLI — parte del mismo bug-corazón. Codex:
  LGTM. **Manual smoke pending**: humano reencola task 6 tras
  merge para validar `task.status=waiting_input` +
  `run.outcome=needs_input`.
- **2026-04-22** — PR-V1-20 (Adapter: pass
  `--dangerously-skip-permissions` always) mergeado en `v1` vía
  squash (#128). Backend **130 passed** (+2). **97 LOC netas**
  código+tests bajo cap 150. FIX crítico descubierto en smoke
  real 2026-04-22: sin el flag, Claude CLI rechazaba tool_use
  para Write/Edit/Bash porque no hay canal de aprobación en
  stream-json → 6/6 tasks acabaron con `no_artifacts`. Decisión
  de producto: flag siempre activo independiente de
  `autonomy_mode` porque la safety vive en la rama aislada
  (`niwa/task-N-<slug>`) + tree limpio (PR-V1-08 guard) + merge
  gate (finalize `autonomy_mode`). `triage.py` hereda el flag
  automáticamente por importar `ClaudeCodeAdapter` por
  referencia. HANDBOOK sección "Permissions model" añadida.
  Codex: LGTM + 1 minor (test de triage con identity check vs
  Popen capture — follow-up).
- **2026-04-21** — PR-V1-19 (Clarification round-trip:
  waiting_input + respond) mergeado en `v1` vía squash (#127).
  Backend **128 passed** (+4). Frontend **12 passed** (+2).
  **391 LOC netas** código+tests bajo cap 400. Cierra Semana 5
  del SPEC §9 (clarification). `VerificationResult` +
  `pending_question`; `check_stream_termination` cambia firma a
  tuple `(error_code, pending_question)`; outcome nuevo
  `needs_input` que `_finalize` mapea a run `failed` + task
  `waiting_input` + `task.pending_question` populado. Endpoint
  nuevo `POST /api/tasks/{id}/respond` con validación 404/409/422
  atómica. UI: `TaskDetail.tsx` banner Alert yellow + Textarea
  + Button "Responder". **Known limitation documentada**: next
  adapter run usa prompt fresco (no composite, no session_handle
  — follow-up). Codex: LGTM.
- **2026-04-21** — PR-V1-18 (Readiness endpoint + /system page)
  mergeado en `v1` vía squash (#126). Backend **124 passed**.
  Frontend 10 passed. **421 LOC netas** tras fix-up (400 inicial
  + 21 blocker). `/api/readiness` devuelve 4 booleanos + details
  (db/claude_cli/git/gh). Codex primera pasada: 1 blocker
  (`load_settings` bypassed `get_session` override en tests;
  tocaba fichero sqlite real). Cerrado con `check_db_via_session`.
- **2026-04-21** — PR-V1-17 (Deploy local: static handler)
  mergeado en `v1` vía squash (#125). Backend **118 passed**.
  **188 LOC netas** bajo cap. `GET /api/deploy/{slug}/{path}`
  sirve `dist/*` con traversal guard. Codex: LGTM.
- **2026-04-21** — FIX-20260421 (Config alignment templates ↔
  config.py) mergeado (#124). Backend **113 passed**. **192 LOC
  netas**. Codex: LGTM.
- **2026-04-21** — PR-V1-16 (Dangerous mode: auto-merge + UI
  banner) mergeado (#123). Backend 107, Frontend 8 passed. **222
  LOC netas** tras fix-up. Cierra Semana 4.
- **2026-04-21** — PR-V1-15 (Executor launcher +
  `niwa-executor` CLI) mergeado (#122). Backend 104 passed. **377
  LOC netas**. Codex: LGTM.
- **2026-04-21** — PR-V1-14 (Bootstrap.sh reproducible) mergeado
  (#121). Backend 94 passed. **306 LOC netas**. Codex: LGTM.
- **2026-04-21** — PR-V1-13 (Safe mode) mergeado (#120). Backend
  89 passed. **400 LOC netas exactos en cap**. Cierra Semana 3.
- **2026-04-21** — PR-V1-12b (Triage executor integration)
  mergeado (#119). Backend 83. **299 LOC**. Codex: LGTM.
- **2026-04-21** — PR-V1-12a (Triage module puro) mergeado (#118).
  Backend 81. **392 LOC**. Codex: LGTM.
- **2026-04-21** — PR-V1-12 original marcado **superseded** por
  12a+12b.
- **2026-04-21** — PR-V1-11c (Verification E5) mergeado (#116).
  77 passed. **380 LOC netas** tras fix-up.
- **2026-04-21** — PR-V1-11b (Verification E3+E4) mergeado (#115).
  72 passed. **499 LOC netas** tras fix-up (blocker E4 ciego a
  tool_use embebido).
- **2026-04-21** — PR-V1-11a (Verification E1+E2 + skeleton)
  mergeado (#114). 65 passed. **387 LOC netas**. Codex: LGTM.
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
