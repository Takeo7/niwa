# Niwa — Orchestrator state

Estado operativo final del MVP Niwa v1. Tras PR-V1-25, `v1/` se
promovió a la raíz del repo y la rama `v1` está lista para
renombrarse a `main`.

```
pr_merged: PR-V1-25
date: 2026-04-22
week: 6
next_pr: (none)
week_status: MVP-COMPLETE
blockers: []
```

## Fase 4 — rename de ramas (operación manual pendiente del humano)

La MCP tool de GitHub no expone `branches/rename` y el orquestador
no tiene acceso al `gh` CLI en su sandbox. La fase 4 queda
documentada aquí para que el humano la ejecute manualmente desde
la CLI local o desde GitHub UI.

**Vía `gh` CLI** (desde la Mac del autor):

```bash
gh api -X POST /repos/takeo7/niwa/branches/v0.2/rename \
  -f new_name=v0.2-legacy
gh api -X POST /repos/takeo7/niwa/branches/main/rename \
  -f new_name=main-legacy
gh api -X POST /repos/takeo7/niwa/branches/v1/rename \
  -f new_name=main
gh api /repos/takeo7/niwa | jq .default_branch
# debe imprimir "main"
```

**Vía GitHub UI**: Settings → Branches → rename cada una (30 s).

**Post-rename**, los consumidores con clones locales deben
actualizar tracking branches:

```bash
git fetch origin --prune
git branch -m v1 main
git branch --set-upstream-to=origin/main main
```

## Historial

- **2026-04-22** — PR-V1-25 (Promote v1 to root + cleanup legacy
  + branch switch) mergeado en `v1` vía squash (#134). PR de
  release final. 508 ficheros tocados: +157 / −102,200. Movió
  `v1/backend/`, `v1/frontend/`, `v1/templates/`, `v1/Makefile`,
  `v1/bootstrap.sh`, `v1/CLAUDE.md`, `v1/data/`, `v1/docs/` a
  raíz con `git mv` preservando historial. Borró todo el código
  legacy de v0.2 (`niwa-app/` 290 ficheros + `bin/` + `servers/` +
  `setup.py` + `docker-compose*` + `caddy/` + `config/` + `tests/`
  + 9 docs históricos). Reescribió `README.md` raíz mínimo con
  link a SPEC y HANDBOOK. Tests post-promoción: **151 backend +
  12 frontend**, sin regresión. Codex primera pasada: **4 blockers
  + 2 majors + minors** reales — `bootstrap.sh:11` resolvía `..`
  al padre del repo, templates `plist`/`systemd` con
  `{{REPO_DIR}}/v1/backend` hardcoded, `CLAUDE.md` raíz con todas
  las rutas apuntando a `v1/...`, test de bootstrap sin assert
  sobre contenido del service file, error message de
  `niwa_cli.py` apuntando a `v1/bootstrap.sh`, docstrings varios.
  Todos cerrados con fix-up en 6 commits sobre la misma rama
  antes del merge. **Fase 4 (rename de ramas) pendiente manual**
  — MCP tool no expone rename, `gh` CLI no disponible en sandbox
  del orquestador.
- **2026-04-22** — PR-V1-23 (Parent task semantics: promote on
  subtasks terminal) mergeado en `v1` vía squash (#133). Backend
  **151 passed**. **262 LOC netas**. Madre de split queda
  `running`; `_maybe_promote_parent` agrega cuando todas las
  hijas son terminales. Hook en `_finalize` Y
  `_finalize_triage_failure` (fix-up codex major: sin el
  segundo, hijas que fallaban en triage dejaban parent running
  indefinidamente).
- **2026-04-22** — PR-V1-22 (Resume via session_handle + user
  response prompt) mergeado (#132). Backend **147 passed**.
  **290 LOC netas**. Adapter expone `session_id` del primer
  `system/init`; `run.session_handle` persistido; executor
  detecta resume path via last user_response + last run con
  session_handle; spawnea adapter con `--resume <handle>` +
  prompt=respuesta. Fix-up codex: dead code
  `had_pending_question` en `_finalize`.
- **2026-04-22** — PR-V1-24 (Git workspace: branch from default,
  not current HEAD) mergeado (#131). Backend **142 passed**.
  **148 LOC netas**. Fix: rama nace desde default branch
  (`origin/HEAD` → `main` → `master`), no desde HEAD actual.
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
