# Niwa — Orchestrator state

Estado operativo de Niwa post-MVP. `main` es la rama oficial.
Tier 1 v1.1 cerrado. Tier 2 (features de uso real) en curso —
PR-V1-33 (task attachments) splitado en 33a-i + 33a-ii + 33b
por overage de scope. Backend completo de attachments en main;
frontend (33b) pendiente.

```
pr_merged: PR-V1-33a-ii
date: 2026-04-26
week: v1.1
next_pr: PR-V1-33b
week_status: v1.1-tier-2-attachments-backend-complete
blockers: []
```

## Historial

- **2026-04-26** — PR-V1-33a-ii (Task attachments — API +
  executor integration) mergeado en `main` vía squash (#143).
  Backend **176 passed** (+4 nuevos del brief original; +3
  vía parametrize de path traversal). **252 LOC** ≤ cap real
  400. Cherry-pick limpio desde la rama abandonada
  `claude/v1-pr-33-task-attachments` de los commits API. Tres
  endpoints nuevos: `POST /api/tasks/{id}/attachments`
  (multipart), `GET .../attachments`, `DELETE
  .../attachments/{aid}` con 404/409 gating. Schema
  `AttachmentRead` Pydantic v2. `_build_prompt(task,
  attachments)` extiende prompt con "## Attached files (read
  these as context):" + paths via `os.path.relpath`. Resume
  path (PR-V1-22) sobrescribe `adapter_prompt` con
  user_response sin tocar attachments — coherente con brief
  (resume = task ya empezada, attachments congeladas a
  inbox/queued). `python-multipart` añadida como peer canónica
  de FastAPI para `UploadFile` (aprobada explícitamente por
  humano + documentada en
  `FOUND-20260426-brief-loc-estimation.md`). Codex: 3 minors
  no-blockers (formalización dep policy en PR aparte; DELETE
  status_code redundante; test traversal sin assert DB —
  cosmético). Pendiente: 33b (frontend Dropzone + bump
  `@mantine/dropzone@7.17.8`).
- **2026-04-26** — PR-V1-33a-i (Task attachments — data layer)
  mergeado (#142). Backend **169 passed**. **372 LOC**. ORM
  `Attachment` con `ON DELETE CASCADE`, migration
  `f98a50e87242` reversible, service `attachments.py` (145
  LOC) con `sanitize_filename` (`..`/`/`/`\\`/NUL) + dedup
  `__N`. Codex: 2 minors (docstring stale, write parcial sin
  cleanup) — follow-up. FOUND nuevo
  `docs/plans/FOUND-20260426-brief-loc-estimation.md`
  documenta el patrón sistemático de briefs subestimando
  scope.
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
