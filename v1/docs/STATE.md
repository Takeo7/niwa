# Niwa v1 — Orchestrator state

Estado operativo del orquestador v1. Cada entrada se añade tras el
merge de un PR. El campo `next_pr` indica el PR que debe arrancar la
siguiente sesión del orquestador.

```
pr_merged: PR-V1-13
date: 2026-04-21
week: 4
next_pr: PR-V1-14
week_status: week-3-complete-awaiting-approval-for-week-4
blockers: []
```

## Historial

- **2026-04-21** — PR-V1-13 (Safe mode: commit + push + open PR)
  mergeado en `v1` vía squash (#120). Backend `pytest -q` → **89
  passed** (+6 nuevos: 5 finalize unit + 1 integration). **400
  LOC netas exactos en el cap**. Cierra Semana 3 del SPEC §9:
  tras `verify_run` pasar, `finalize_task(session, run, task,
  project)` intenta commit → push → `gh pr create` como
  best-effort (nunca lanza al caller). Commit con flags `-c
  user.email`/`-c user.name` inline (sin config global), push si
  `project.git_remote`, PR si `shutil.which("gh")`. URL
  persistida en `task.pr_url`. `autonomy_mode=dangerous`
  (auto-merge) queda para Semana 4. Codex: LGTM sin hallazgos.
  Cero cambios a adapter/triage/verification/frontend/schema,
  cero deps nuevas.
- **2026-04-21** — PR-V1-12b (Triage executor integration)
  mergeado en `v1` vía squash (#119). Backend 83 passed (+2
  integration). **299 LOC netas** bajo cap. Wiring del triage en
  `process_pending`: `claim → triage → dispatch`; `_apply_split`
  crea N subtasks con `parent_task_id` y escribe
  `TaskEvent(kind="message", payload.event="triage_split")`
  (resolución Opción B: SPEC §3 fija el enum a 5 valores;
  `triage_split` va como marker en payload); `_finalize_triage_failure`
  emite Run sintético + TaskEvent verification. Fake CLI con
  keyword-dispatch `"triage agent for Niwa"` + marker consume-once
  para acotar recursión en tests. Codex: LGTM.
- **2026-04-21** — PR-V1-12a (Triage module puro + unit tests)
  mergeado en `v1` vía squash (#118). Backend 81 passed (+4
  nuevos, incluido caso extra de JSON sin fence). **392 LOC netas**
  bajo cap. `triage.py` con `TriageDecision` frozen dataclass,
  `TriageError`, `triage_task(project, task)`; parser fence +
  fallback balanced-match + validación estricta de shape.
  Módulo dead code hasta 12b (confirmed: no importado desde
  executor). Tests mockean adapter vía monkeypatch. Codex: LGTM.
- **2026-04-21** — PR-V1-12 original (Triage planner combinado)
  marcado **superseded** por 12a+12b al cerrar en 494 LOC netas
  (94 sobre cap estricto Semana 3). Split A acordado: módulo
  puro + integración. PR #117 cerrado sin merge.
- **2026-04-21** — PR-V1-11c (Verification E5 project tests
  runner) mergeado en `v1` vía squash (#116). Backend 77 passed
  (+2 nuevos unit + 2 regression fix-up). **380 LOC netas** tras
  fix-up. Cierra §5 del SPEC: `detect_test_runner` con orden
  Makefile → npm → pytest (stdlib `tomllib` 3.11+);
  `run_project_tests` con timeout 300 s, output_tail 4 KB.
  Codex primera pasada: 1 blocker (FileNotFoundError del runner
  escapa → task wedge) + 2 minors (regex Makefile falso positivo
  `test :=`, `python` literal falla en Debian moderno). Los 3
  cerrados con fix-ups + regression tests. Nuevo error_code
  `tests_runner_missing`. Cero deps, cero cambios fuera de
  verification.
- **2026-04-21** — PR-V1-11b (Verification E3+E4 artifact scanning)
  mergeado en `v1` vía squash (#115). Backend 72 passed (+4 unit +
  1 integration + 2 regression fix-up). **499 LOC netas** tras
  fix-up (384 inicial + 115 por blocker codex real + minor
  cwd_missing). E3 `git status --porcelain` + skip graceful si no
  repo git; E4 `_iter_tool_use_payloads` escanea top-level Y
  embebido en `assistant.message.content[]` (blocker v0.2
  FIX-20260420). Codex cerró 1 major (tratado como blocker: E4
  ciego a tool_use embebido, falso negativo sistemático) + 2
  minors (FileNotFoundError ambigüo cwd vs git, test legacy
  duplicado). Multi-task git_project por task (finding #3).
- **2026-04-21** — PR-V1-11a (Verification E1+E2 + skeleton +
  executor integration) mergeado en `v1` vía squash (#114).
  Backend 65 passed (+4 stream unit + 2 integration). **387 LOC
  netas** bajo cap. Skeleton `verification/` con
  `VerificationResult` dataclass + stubs E3/E4/E5 con evidence
  shape estable. E1 mapping `cli_ok→verified`,
  `cli_nonzero_exit→exit_nonzero`, `{cli_not_found,timeout,adapter_exception}→adapter_failure`;
  E2 filtra lifecycle sintéticos, extrae texto multi-bloque
  `content[].text`, 4 rutas: ok / `question_unanswered` /
  `tool_use_incomplete` / `empty_stream`. Bypass del verifier
  cuando adapter falla (preserva outcomes). `_finalize` firma
  extendida con `error_code` opcional. Fake CLI
  `FAKE_CLAUDE_TOUCH` para mid-run artifacts. Outcome rename
  `cli_ok → verified` en asserts de `run.outcome` final. Codex:
  LGTM.
- **2026-04-21** — PR-V1-11 original (Verification contract
  combinado) marcado **superseded** por 11a+11b+11c al cerrar en
  917 LOC netas (2.3× cap 400 estricto Semana 3). Split A
  acordado: E1+E2+skeleton / E3+E4 / E5. PR-V1-11 brief
  internamente inconsistente (test_runs_api brief mismatch,
  adapter target ≤200 irreal). Disciplina estricta aplicada sin
  "opción A".
- **2026-04-20** — PR-V1-10 (UI task detail con stream en vivo)
  mergeado en `v1` vía squash (#113). Frontend `npm test -- --run`
  → **6 passed** (+2 `TaskEventStream.test.tsx`). Backend 59 sin
  cambios. **506 LOC netas** (código puro 314 bajo cap 400; test
  139 + HANDBOOK 53 empujan al total). Cierra Semana 2: la UI
  consume el SSE vía `useEventStream(runId)` hook, timeline con
  `event_type` + timestamp + payload colapsable, `MockEventSource`
  inyectado vía `vi.stubGlobal` por test, navegación desde
  `TaskList.Tr` con `stopPropagation` en el botón delete. Codex:
  LGTM sin hallazgos. Cero deps npm nuevas, cero backend tocado.
- **2026-04-20** — PR-V1-09 (SSE endpoint para run events)
  mergeado en `v1` vía squash (#112). Backend `pytest -q` → 59
  passed (+3 SSE). **541 LOC netas** (462 código+tests + 79 docs);
  aceptado como excepción documentada (precedente 06b/07).
  `GET /api/runs/{id}/events` como `StreamingResponse`; async
  generator con `asyncio.to_thread` para queries SQLAlchemy sync
  (no AsyncSession), `last_emitted_id` monotónico, drain terminal
  antes del `eos`, heartbeat 15 s vía contador (75 × 200 ms),
  `json.loads`+re-dump para `payload` (sin double-escape), 404
  JSON antes de iniciar stream. Tests con `httpx.AsyncClient` +
  timeout 10 s y writer thread sincronizado para run vivo.
  Codex: LGTM. Cero cambios en adapter/executor/frontend, cero
  deps nuevas.
- **2026-04-20** — PR-V1-08 (Git workspace: branch per task)
  mergeado en `v1` vía squash (#111). Backend `pytest -q` → 56
  passed (+5 git_workspace + 1 outcome específico; 7 de executor
  migrados a fixture `git_project`). **381 LOC netas** bajo cap.
  `prepare_task_branch(local_path, task)` antes del adapter spawn:
  validación repo git (`rev-parse --git-dir`) + working tree limpio
  (`status --porcelain`) + create-or-reuse (`show-ref` → `checkout`
  con o sin `-b`). `build_branch_name(task)` puro: `niwa/task-<id>-
  <slug>`, slug truncado a 30 con `strip("-")` post-truncate.
  Outcome `git_setup_failed` → run failed sin invocar adapter,
  `task.branch_name` queda `None`. Codex: LGTM, sin hallazgos.
  Cero deps, cero frontend, cero commit/push de git en runs
  (finalize es futuro).
- **2026-04-20** — PR-V1-07 (Claude Code adapter with stream-json
  parser) mergeado en `v1` vía squash (#110). Backend `pytest -q`
  → **50 passed** (+6 nuevos: 4 adapter + 2 regression close()).
  Frontend 4 sin cambios. **925 LOC netas** — hard-cap 400 superado
  a 700 inicial + 118 de fix-ups tras codex; aceptado vía **opción
  A** por el humano (brief internamente inconsistente: 4 tests
  declarados como pipeline end-to-end obligan a migrar executor +
  test_runs_api en el mismo PR). Arranca Semana 2 del SPEC §9:
  `run_echo` sustituido por `run_adapter` que spawnea `claude -p
  --output-format stream-json --verbose` con `selectors` +
  stderr-drain-thread + `close()` idempotente (terminate → join →
  wait). Fake CLI fixture sin deps nuevas (stdlib puro). Codex
  primera pasada: 2 majors tratados como blockers (adapter sin
  args stream-json, zombies en excepción); ambos resueltos con
  fix commits + regression tests en la misma rama antes del
  merge. 2 minors: docstring sobre stdin bloqueante y dead code
  en `process_pending` limpiados.
- **2026-04-20** — PR-V1-06b (UI tasks list + create + delete +
  polling) mergeado en `v1` vía squash (#109). Frontend `npm test
  -- --run` → 4 passed (+2 nuevos sobre 06a). 571 LOC sin lockfile,
  bajo hard-cap 600. Completa la segunda mitad del PR-V1-06
  original: `TaskList` embebido en `ProjectDetail`,
  `TaskCreateModal`, delete con `409` toast, `refetchInterval`
  gated por `hasInFlightTask`. Codex: LGTM sin hallazgos.
- **2026-04-20** — PR-V1-06a (UI shell + routing + projects CRUD)
  mergeado en `v1` vía squash (#108). Frontend `npm test -- --run`
  → 2 passed (+2 nuevos desde 0). 524 LOC sin lockfile, bajo
  hard-cap 600. Primera mitad del PR-V1-06 original tras split.
  Codex: LGTM sin hallazgos.
- **2026-04-20** — PR-V1-06 original (UI mínima combinada) marcado
  **superseded** por 06a+06b al exceder el hard-cap 600 LOC.
- **2026-04-20** — PR-V1-05 (Executor echo daemon) mergeado en `v1`
  vía squash (#107). Backend `pytest -q` → 44 passed. Cierra
  Semana 1. `claim_next_task` atómico vía `BEGIN IMMEDIATE`.
- **2026-04-20** — PR-V1-04 (Tasks CRUD API) mergeado (#106).
  Backend 34 passed. 4 endpoints REST.
- **2026-04-20** — PR-V1-03 (Projects CRUD API) mergeado (#105).
  Backend 22 passed. 5 endpoints REST.
- **2026-04-20** — PR-V1-02 (Data models + initial Alembic migration)
  mergeado (#104). Backend 11 passed. Codex 3 majors + 1 minor
  resueltos en fix-up antes del merge.
- **2026-04-20** — PR-V1-01 (Skeleton FastAPI + React + SQLite)
  mergeado (#103). Backend 1 passed. 585 LOC scaffolding aceptado.
