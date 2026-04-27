# Niwa — Orchestrator state

Estado operativo de Niwa post-MVP. `main` es la rama oficial.
**Ciclo v1.1 cerrado** — Tier 1 (29-32) + Tier 2 (33, 34, 35).
Próximo: smoke completo de todo v1.1 antes de retro post-ciclo.

```
pr_merged: PR-V1-35
date: 2026-04-27
week: v1.1
next_pr: smoke-v1.1
week_status: v1.1-cycle-complete
blockers: []
```

## Historial

- **2026-04-27** — PR-V1-35 (PR merge button) mergeado vía
  squash (#147). Backend **193 passed** (+5: 2 originales del
  primer push + 3 fix-up codex: idempotente already-merged,
  parametrized failing-checks/missing-review/draft). Frontend
  **18 passed** (+1). **LOC ~325** (cap S 100, 3.25× — cuarta
  muestra `FOUND-20260426-loc-cap-pattern.md`, aceptado
  conscientemente como cierre del ciclo). Sub-agente respetó
  el gate "paras y consultas" (mejora vs 34a). Codex 2 majors
  + 2 minors: M1 (--auto exits rc=0 enabling auto-merge ≠
  merging) → drop --auto y simplificar service. M2 (already-
  merged caía en 502) → idempotente. m1 (markers incompletos)
  → 7 markers. m2 (autonomy_mode race) → safe default
  acceptable. Endpoint POST `/api/projects/{slug}/pulls/{n}/merge`
  con `PullNotMergeable` exception → 409 reusando patrón 34a.
  Frontend: `MergeButton` dentro de `PullsTab`, lee
  `autonomy_mode` vía `useProject`, confirma salvo dangerous.
  **Cierra Tier 2 v1.1.**
- **2026-04-26** — PR-V1-34b (Project pulls — frontend tab +
  PullsTab) mergeado vía squash (#146). Frontend **17 passed**
  (+2 nuevos). Backend 188 sin cambios. **543 LOC totales con
  brief; código frontend +320/-30** (cap 310, drift +10 dentro
  de tolerancia +30). Mantine `Tabs` en `ProjectDetail` con
  `keepMounted={false}`. `PullsTab` consume contrato Pydantic
  snake_case de 34a; renderiza `checks.state` directo sin
  recálculo cliente. 4 ramas de empty/warning state cubiertas
  (`no_remote`, `invalid_remote`, `gh_missing` 503, `gh_failed`/
  `gh_timeout` 502/504 unificados en Alert inline). Tests con
  mock `listPulls` cubren passing+failing data y 503.
  Codex LGTM (orquestador). 2 desviaciones del brief declaradas
  transparentemente: toast→Alert inline (UX, React Query ya
  reintenta) y doble protección refetch (`enabled: active` +
  `keepMounted={false}`). Cierra PR-V1-34 entero.
- **2026-04-26** — PR-V1-34a (Project pulls — backend service +
  endpoint) mergeado vía squash (#145). Backend **188 passed**
  (+12 nuevos: 3 originales + 4 ramas error + 5 parametrize de
  `collapse_check_state`). **Backend 388 LOC** (cap brief 240,
  +148 por fix-ups codex; aceptado pre-merge). Servicio
  `github_pulls` envuelve `gh pr list --json` con detección
  owner/repo (HTTPS+SSH), filtra a ramas `niwa/task-*`. Endpoint
  `GET /api/projects/{slug}/pulls` con contrato Pydantic
  (`PullRead`/`PullCheck`/`PullsResponse`, snake_case) y colapso
  server-side de `statusCheckRollup` a `check_state` con
  prioridad `failing>pending>passing>none`. Excepciones tipadas:
  `GhUnavailable`→503, `GhTimeout`→504, `GhCommandFailed`→502.
  Codex 3 majors + 2 minors resueltos en fix-up: contrato
  Pydantic ausente (Major 2), timeout 502→504 (Major 1), tests
  faltantes para rc!=0 / non-JSON / invalid_remote (Major 3),
  regex anchoring + logger DEBUG (minors). FOUND nuevo
  `FOUND-20260426-spec-deviation.md` documenta el patrón "el
  sub-agente desvía del brief sin parar a consultar" — companion
  al FOUND de LOC cap, mismo root probable; retro post-ciclo.
  Frontend NO se toca; reescrito en 34b contra el contrato
  Pydantic (no cherry-pick directo del PR-V1-34 monolítico).
- **2026-04-26** — PR-V1-33b (Task attachments — frontend
  Dropzone + lista) mergeado en `main` vía squash (#144).
  Frontend **15 passed** (+1 nuevo). Backend 176 sin cambios.
  **353 LOC** ≤ cap 400 (sin lockfile). Cierra el feature
  attachments end-to-end. Bump `@mantine/dropzone@7.17.8`
  (cherry-pick) + import del stylesheet en `main.tsx`.
  `uploadAttachment` con `fetch` directo + FormData (boundary
  multipart correcto). Modal con Dropzone debajo de
  `description`, lista local de files seleccionados, submit:
  POST task → N POST attachments secuencial.
  `TaskDetail.tsx` con sección "Attachments" gated por
  `task.status in {inbox, queued}` para botón delete. HANDBOOK
  añade sección completa "Task attachments" cubriendo trío
  (33a-i/ii/b). Codex: 2 minors no-blockers (cancel durante
  uploads, doble toast en fallo total) — UX edge cases follow-up.
- **2026-04-26** — PR-V1-33a-ii (Task attachments — API +
  executor integration) mergeado (#143). Backend **176 passed**
  (+4 brief + 3 parametrize). **252 LOC**. Cherry-pick limpio
  desde rama abandonada. 3 endpoints
  (`POST/GET/DELETE /api/tasks/{id}/attachments`) con 404/409
  gating. `_build_prompt(task, attachments)` extiende prompt
  con sección literal + paths via `os.path.relpath`. Resume
  path coexiste correctamente (descarta attachments en resume).
  `python-multipart` añadida (peer canónica FastAPI, aprobada
  explícitamente por humano). Codex: 3 minors no-blockers.
- **2026-04-26** — PR-V1-33a-i (Task attachments — data layer)
  mergeado (#142). Backend **169 passed**. **372 LOC**. ORM
  `Attachment` con CASCADE, migration `f98a50e87242`, service
  con sanitización + dedup. Codex: 2 minors. FOUND nuevo
  `FOUND-20260426-brief-loc-estimation.md` documenta patrón
  de briefs subestimando scope.
- **2026-04-26** — PR-V1-32 (`niwa-executor dev start/stop/status`)
  mergeado (#141). Backend **160 passed**. **169 LOC** (+19).
  Cierra Tier 1 del ciclo v1.1. Codex: LGTM.
- **2026-04-26** — PR-V1-31 (`niwa-executor update` wrapper)
  mergeado (#140). Backend **156 passed**. **140 LOC** (+40).
  Codex 2 majors + 1 minor cerrados en fix-up.
- **2026-04-26** — PR-V1-30 (Bootstrap enables systemd user
  linger) mergeado (#139). Backend **153 passed**. **36 LOC**
  (+6). Codex: 1 major fix-up.
- **2026-04-25** — PR-V1-29 (Actionable error when no default
  branch detected) mergeado (#138). Backend **153 passed**.
  **22 LOC**. Codex: LGTM.
- **2026-04-25** — PR-V1-28 (In-app help + first-project
  guidance) mergeado (#137). Frontend **14 passed**. **85 LOC
  código+tests** sin contenido estático. Codex: LGTM.
- **2026-04-23** — PR-V1-27 (docs: Python Ubuntu) mergeado
  (#136) directo por el humano.
- **2026-04-23** — PR-V1-26 (Onboarding polish for fresh
  install) mergeado (#135). Backend **152 passed**. Codex: 1
  major fix-up.
- **2026-04-22** — Rename de ramas: `v1 → main`. Fase 4 del
  PR-V1-25.
- **2026-04-22** — PR-V1-25 (Promote v1 to root + cleanup
  legacy) mergeado (#134). Codex: 4 blockers + 2 majors en
  fix-up.
- **2026-04-22** — PR-V1-23 (Parent task semantics) mergeado
  (#133). Backend **151 passed**.
- **2026-04-22** — PR-V1-22 (Resume via session_handle) mergeado
  (#132). Backend **147 passed**.
- **2026-04-22** — PR-V1-24 (Git workspace: branch from default)
  mergeado (#131). Backend **142 passed**.
- **2026-04-22** — PR-V1-21b (Verification structural needs_input)
  mergeado (#130). Backend **138 passed**.
- **2026-04-22** — PR-V1-21 (Verification: open question real
  CLI stream) mergeado (#129). Backend **133 passed**.
- **2026-04-22** — PR-V1-20 (Adapter
  --dangerously-skip-permissions) mergeado (#128). Backend
  **130 passed**.
- **2026-04-21** — PR-V1-19 (Clarification round-trip) mergeado
  (#127). Cierra Semana 5.
- **2026-04-21** — PR-V1-18 (Readiness endpoint + /system page)
  mergeado (#126).
- **2026-04-21** — PR-V1-17 (Deploy local static handler)
  mergeado (#125).
- **2026-04-21** — FIX-20260421 (Config alignment) mergeado
  (#124).
- **2026-04-21** — PR-V1-16 (Dangerous mode auto-merge) mergeado
  (#123). Cierra Semana 4.
- **2026-04-21** — PR-V1-15 (Executor launcher CLI) mergeado
  (#122).
- **2026-04-21** — PR-V1-14 (Bootstrap.sh reproducible) mergeado
  (#121).
- **2026-04-21** — PR-V1-13 (Safe mode) mergeado (#120). Cierra
  Semana 3.
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
- **2026-04-20** — PR-V1-02 (Data models + Alembic) mergeado
  (#104).
- **2026-04-20** — PR-V1-01 (Skeleton) mergeado (#103).
