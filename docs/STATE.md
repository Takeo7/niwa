# Niwa — Orchestrator state

Estado operativo de Niwa post-MVP. `main` es la rama oficial.
Tier 1 v1.1 cerrado. Tier 2 (features de uso real) en curso.

```
pr_merged: PR-V1-32
date: 2026-04-26
week: v1.1
next_pr: PR-V1-33
week_status: v1.1-tier-1-complete-tier-2-in-flight
blockers: []
```

## Historial

- **2026-04-26** — PR-V1-32 (`niwa-executor dev start/stop/status`)
  mergeado en `main` vía squash (#141). Backend **160 passed**
  (+4). **169 LOC** (sobre cap S 150 por +19; el 4º test
  opcional añade ~17 del overage). Tres subcomandos nuevos:
  `dev start [--detach]` con preflight (uvicorn venv +
  node_modules), foreground via `os.execvp("make", ["make",
  "-C", repo, "dev"])`, detach con `subprocess.Popen
  start_new_session=True` y PID files en `~/.niwa/run/`; `dev
  stop` con TERM → poll 3s → SIGKILL fallback +
  ProcessLookupError silente; `dev status` con `kill(pid, 0)`
  liveness. Codex: LGTM. Cierra Tier 1 del ciclo v1.1.
- **2026-04-26** — PR-V1-31 (`niwa-executor update` wrapper)
  mergeado (#140). Backend **156 passed**. **140 LOC** (+40
  sobre cap por +11 scope inicial + ~30 fix-ups codex). Codex
  primera pasada: 2 majors + 1 minor cerrados en fix-up:
  `out()` ignoraba returncode (mentira-de-completion estilo
  v0.2) → aborta con error claro; test no verificaba ruta venv
  → assert reforzado; `--repo-path` inválido → mensaje
  diferenciado. Patrón sistemático del overage por fix-ups
  documentado en `docs/plans/FOUND-20260426-loc-cap-pattern.md`.
- **2026-04-26** — PR-V1-30 (Bootstrap enables systemd user
  linger) mergeado (#139). Backend **153 passed**. **36 LOC**
  (+6). Codex: 1 major (test side effect host) cerrado en
  fix-up con `NIWA_BOOTSTRAP_SKIP_LINGER`.
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
  major en fix-up.
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
