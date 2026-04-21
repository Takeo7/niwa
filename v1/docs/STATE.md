# Niwa v1 — Orchestrator state

Estado operativo del orquestador v1. Cada entrada se añade tras el
merge de un PR. El campo `next_pr` indica el PR que debe arrancar la
siguiente sesión del orquestador.

```
pr_merged: PR-V1-19
date: 2026-04-21
week: 6
next_pr: PR-V1-20
week_status: week-5-complete-awaiting-approval-for-week-6
blockers: []
```

## Historial

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
  atómica (2 TaskEvents + status change en un commit). UI:
  `TaskDetail.tsx` banner Mantine Alert yellow + Textarea +
  Button "Responder" cuando status=waiting_input. Hook
  `useRespondTask` invalida `["task", taskId]` tras success.
  **Known limitation documentada**: next adapter run usa prompt
  fresco (no composite, no session_handle/CLI resume — follow-up).
  Codex: LGTM.
- **2026-04-21** — PR-V1-18 (Readiness endpoint + /system page)
  mergeado en `v1` vía squash (#126). Backend **124 passed** (+6
  con fix-up: 5 iniciales + 1 regression exception branch).
  Frontend 10 passed (+2 SystemRoute). **421 LOC netas** código+tests
  tras fix-up (400 inicial + 21 por blocker codex real).
  `/api/readiness` devuelve 4 booleanos + details (db_ok,
  claude_cli_ok, git_ok, gh_ok). Frontend `/system` consume via
  React Query sin refetchInterval, tabla Mantine, botón Refresh.
  Codex primera pasada: 1 blocker (handler ignoraba
  `get_session` override y tocaba fichero SQLite real del
  repo en tests) + 2 minors (SQLite crea fichero al conectar;
  rama `except` sin cobertura real). Cerrados con refactor:
  `check_db_via_session(session)` usa la DI Session en vez de
  engine ad-hoc. Test isolation verificado (dev sqlite no se
  crea). Semánticamente no systemd/disk/auth — documentado.
- **2026-04-21** — PR-V1-17 (Deploy local: static handler)
  mergeado en `v1` vía squash (#125). Backend **118 passed** (+5
  deploy). **188 LOC netas** bajo cap. `GET
  /api/deploy/{slug}/{path:path}` sirve `<local_path>/dist/*`
  para proyectos `kind="web-deployable"` con traversal guard
  (`Path.resolve() + relative_to`). Fallback a `index.html` para
  root/dirs. 404 uniforme entre "proyecto no existe" y
  "kind != web-deployable" (no leak de existencia). `deploy_port`
  column mantenida como aspiracional v1.1 (no leída). Sin
  process spawn, sin build automático, sin integración en
  `finalize.py`. Codex: LGTM.
- **2026-04-21** — FIX-20260421 (Config alignment: templates ↔
  config.py) mergeado en `v1` vía squash (#124). Backend **113
  passed** (+6 nuevos en `test_config.py`). **192 LOC netas**
  código+tests bajo cap S (200). Cierra un mismatch de boot
  detectado post-Semana 4: `config.py` leía `[server]`/`[database]`
  y `NIWA_CONFIG`, pero los templates de PR-V1-14 emiten
  `[claude]`/`[db]`/`[executor]` y exportan `NIWA_CONFIG_PATH`.
  Resultado pre-fix: bootstrap migraba DB a
  `~/.niwa/data/niwa-v1.sqlite3` pero backend leía
  `DEFAULT_DB_PATH` (DB vacía, migrada huérfana). Fix alinea
  `config.py` a los templates como fuente de verdad: lee
  `[claude]/[db]/[executor]`, acepta `NIWA_CONFIG_PATH` preferido
  con `NIWA_CONFIG` como alias deprecado, `Settings` extendido
  con `claude_cli`, `claude_timeout_s`,
  `executor_poll_interval_s`. `[server]` se mantiene leyéndose
  opcional para forward-compat. Cero cambios a templates,
  adapter, executor, finalize, niwa_cli, frontend. Codex: LGTM.
- **2026-04-21** — PR-V1-16 (Dangerous mode: auto-merge + UI
  banner) mergeado en `v1` vía squash (#123). Backend 107 passed
  (+3 finalize). Frontend **8 passed** (+2 ProjectDetail).
  **222 LOC netas** código+tests tras fix-up (212 inicial + 10
  kwargs refactor), bajo cap 400. Cierra Semana 4 del SPEC §9:
  `FinalizeResult.pr_merged: bool = False` nuevo campo;
  `finalize_task` paso 4 opcional: si `pr_url` + `autonomy_mode
  == "dangerous"` + `shutil.which("gh")`, ejecuta `gh pr merge
  <url> --squash --delete-branch`. Best-effort (nunca regresa la
  task). Banner rojo `Alert` con `IconAlertTriangle` en
  `ProjectDetail.tsx` cuando mode dangerous. Codex primera
  pasada: 1 major (positional args en `test_executor.py` rotos
  por reorden del dataclass tras `pr_merged`) + 1 minor (brief vs
  impl en caso unreachable). Major cerrado con fix kwargs; minor
  clarificado con comentario.
- **2026-04-21** — PR-V1-15 (Executor launcher +
  `niwa-executor` CLI) mergeado en `v1` vía squash (#122). Backend
  **104 passed** (+10 CLI unit). **377 LOC netas** bajo cap.
  CLI argparse con `start|stop|restart|status|logs` (flags
  `--follow`, `--lines N`). Platform dispatch via
  `platform.system()`: Darwin → `launchctl load/unload/kickstart/
  list`; Linux → `systemctl --user enable/disable/restart/status`.
  Entry point `niwa-executor = "app.niwa_cli:main"` en
  `pyproject.toml`. `_run` helper centraliza subprocess con
  `FileNotFoundError → exit 127`. Codex: LGTM.
- **2026-04-21** — PR-V1-14 (Bootstrap.sh reproducible) mergeado
  en `v1` vía squash (#121). Backend 94 passed (+5 bootstrap
  subprocess). **306 LOC netas** bajo cap. `v1/bootstrap.sh` bash
  con `set -euo pipefail`: preconditions (python3≥3.11 / npm /
  git) con log up-front, layout `~/.niwa/{venv,logs,data}`, venv
  + backend editable `pip install -e [dev]`, frontend `npm install`
  (skippable), `alembic upgrade head`, config.toml generado via
  sed sobre template (preservado si existe), service file por
  OS. NO carga servicio — PR-V1-15 hace eso. Codex: LGTM.
- **2026-04-21** — PR-V1-13 (Safe mode: commit + push + open PR)
  mergeado en `v1` vía squash (#120). Backend 89 passed (+6).
  **400 LOC netas exactos en el cap**. Cierra Semana 3. Codex:
  LGTM.
- **2026-04-21** — PR-V1-12b (Triage executor integration)
  mergeado (#119). Backend 83 passed. **299 LOC netas**. Codex:
  LGTM.
- **2026-04-21** — PR-V1-12a (Triage module puro) mergeado (#118).
  Backend 81 passed. **392 LOC netas**. Codex: LGTM.
- **2026-04-21** — PR-V1-12 original marcado **superseded** por
  12a+12b.
- **2026-04-21** — PR-V1-11c (Verification E5) mergeado (#116).
  77 passed. **380 LOC netas** tras fix-up. 1 blocker + 2 minors
  resueltos.
- **2026-04-21** — PR-V1-11b (Verification E3+E4) mergeado (#115).
  72 passed. **499 LOC netas** tras fix-up (blocker E4 ciego a
  tool_use embebido).
- **2026-04-21** — PR-V1-11a (Verification E1+E2 + skeleton)
  mergeado (#114). 65 passed. **387 LOC netas**. Codex: LGTM.
- **2026-04-21** — PR-V1-11 original marcado **superseded** por
  11a+11b+11c.
- **2026-04-20** — PR-V1-10 (UI task detail con stream) mergeado
  (#113). Frontend 6 passed. **506 LOC netas**. Cierra Semana 2.
  Codex: LGTM.
- **2026-04-20** — PR-V1-09 (SSE endpoint) mergeado (#112).
  Backend 59 passed. **541 LOC netas**. Codex: LGTM.
- **2026-04-20** — PR-V1-08 (Git workspace) mergeado (#111).
  Backend 56 passed. **381 LOC netas**. Codex: LGTM.
- **2026-04-20** — PR-V1-07 (Claude Code adapter) mergeado
  (#110). Backend 50 passed. **925 LOC netas** (opción A por
  brief inconsistente).
- **2026-04-20** — PR-V1-06b (UI tasks list + create + delete +
  polling) mergeado (#109). Frontend 4 passed. 571 LOC.
- **2026-04-20** — PR-V1-06a (UI shell + routing + projects CRUD)
  mergeado (#108). Frontend 2 passed. 524 LOC.
- **2026-04-20** — PR-V1-06 original marcado **superseded** por
  06a+06b.
- **2026-04-20** — PR-V1-05 (Executor echo daemon) mergeado
  (#107). Backend 44 passed. Cierra Semana 1.
- **2026-04-20** — PR-V1-04 (Tasks CRUD API) mergeado (#106).
  Backend 34 passed.
- **2026-04-20** — PR-V1-03 (Projects CRUD API) mergeado (#105).
  Backend 22 passed.
- **2026-04-20** — PR-V1-02 (Data models + initial Alembic migration)
  mergeado (#104). Backend 11 passed. Codex 3 majors + 1 minor
  resueltos en fix-up.
- **2026-04-20** — PR-V1-01 (Skeleton FastAPI + React + SQLite)
  mergeado (#103). Backend 1 passed. 585 LOC scaffolding.
