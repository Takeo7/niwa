# Niwa — Arquitectura y flujos

## 1. Arquitectura (containers + host)

```
                         ┌─────────────────────────┐
                         │   Cliente MCP / Web     │
                         │ Claude Code · OpenClaw  │
                         │   navegador (UI)        │
                         └───────────┬─────────────┘
                                     │ HTTPS + Bearer
                                     ▼
                       ┌──────────────────────────┐
                       │   Cloudflare Tunnel      │  (opcional, host)
                       │     cloudflared          │
                       └───────────┬──────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │                                          │
              ▼                                          ▼
   ┌──────────────────┐                       ┌──────────────────┐
   │   Caddy (443)    │                       │ niwa-app  :8765  │
   │ reverse-proxy +  │                       │  (web UI + API)  │
   │  bearer auth     │                       │  Python stdlib   │
   └────┬────────┬────┘                       └────────┬─────────┘
        │        │                                     │
        │        └─────────────┐                       │
        ▼                      ▼                       │
┌───────────────┐    ┌──────────────────┐              │
│ mcp-gateway   │    │ mcp-gateway-sse  │              │
│ (HTTP stream) │    │   (SSE legacy)   │              │
│   :8811       │    │      :8812       │              │
└───────┬───────┘    └────────┬─────────┘              │
        │                     │                        │
        └──────────┬──────────┘                        │
                   ▼                                   │
       ┌─────────────────────┐                         │
       │  servers MCP        │                         │
       │  ├─ tasks-mcp       │◀────────────────────────┤
       │  ├─ notes-mcp       │◀────────────────────────┤
       │  └─ platform-mcp    │                         │
       └──────────┬──────────┘                         │
                  │                                    │
                  ▼                                    ▼
            ┌───────────────────────────────────────────┐
            │         SQLite (WAL)  data/niwa.sqlite3   │
            │  tasks · task_events · projects · notes   │
            └───────────────▲───────────────────────────┘
                            │
                ┌───────────┴───────────┐
                │  task-executor (host) │  ← launchd / systemd user
                │  bin/task-executor.py │
                │  HeartbeatThread 60s  │
                └───────────┬───────────┘
                            │ subprocess
                            ▼
              ┌────────────────────────────┐
              │ LLM CLI provider           │
              │  claude · llm · gemini ·   │
              │  custom command            │
              └────────────────────────────┘

  socket-proxy (tecnativa) ── expone /var/run/docker.sock al gateway
```

Red docker: `niwa-net`. Servicios resueltos por nombre (`mcp-gateway`, `app`, etc.).

---

## 2. Flujo de una tarea (creación → ejecución → cierre)

```
   Usuario / MCP client / API
            │
            │  POST /api/tasks         o   tasks-mcp.create_task
            ▼
   ┌─────────────────────┐
   │    niwa-app API     │  inserta en `tasks` (status=pendiente)
   │  tasks_service.py   │  emite task_event(created)
   └──────────┬──────────┘
              │
              ▼
        SQLite (WAL)
              │
              │  poll cada N seg
              ▼
   ┌─────────────────────┐
   │  task-executor      │  SELECT * FROM tasks
   │  (host daemon)      │   WHERE status='pendiente'
   └──────────┬──────────┘   (status='inbox' → NO se ejecuta)
              │
              │  status → en_progreso
              │  HeartbeatThread arranca (tick 60s)
              ▼
   ┌─────────────────────┐
   │  LLM provider CLI   │  subprocess: claude / llm / gemini
   │  prompt = task body │
   └──────────┬──────────┘
              │
       ┌──────┴───────┐
       ▼              ▼
   éxito (0)     error / timeout
       │              │
       ▼              ▼
   status=hecha   status=revision
   completed_at   payload con stderr
       │              │
       └──────┬───────┘
              ▼
   task_events: status_changed
              │
              ▼
   UI / history.py  ─►  /api/tasks/history (filtros + stats)
```

Estados: `inbox` · `pendiente` · `en_progreso` · `revision` · `hecha` · `archivada`.
Regla clave: solo `pendiente` se autoejecuta. `inbox` = bandeja manual.

---

## 3. Rutinas / triggers

```
   ┌────────────────────────────────────────────────────┐
   │                Disparadores en Niwa                │
   └────────────────────────────────────────────────────┘

   IMPLEMENTADOS
   ─────────────
   • Polling del executor          → cada N seg, host daemon
   • HeartbeatThread               → cada 60s mientras corre tarea
   • health_service                → on-demand desde /api/health
   • task_events                   → emitidos sincronamente en cada cambio
   • Scheduler thread              → cada 60s, evalúa cron expressions
   • Routines table                → cron-like, acciones: create_task | script | webhook
   • Notifier (Telegram + webhook) → envío de resultados de routines
   • Backup automático             → routine built-in, 3am UTC, rotación 7 días
```

Flujo de una routine:

```
  scheduler tick (60s) ──► for each enabled routine:
                              │
                              │  cron_matches(schedule, now)?
                              │
                              ├── action=create_task ─► INSERT INTO tasks (status=pendiente)
                              │                           ↓
                              │                    executor lo recoge en el siguiente poll
                              │
                              ├── action=script ─► subprocess.run(command)
                              │
                              └── action=webhook ─► urllib POST
                              │
                              ▼
                    UPDATE routines SET last_run_at, last_status
                              │
                              ├── notify_channel=telegram ─► Telegram Bot API
                              └── notify_channel=webhook  ─► POST genérico
```

Built-in routines (seeded en primer arranque):
- `healthcheck` — cada 30 min, verifica DB + disco (enabled)
- `daily-backup` — 3am, copia sqlite + rotación 7 días (enabled)
- `idle-project-review` — 9am L-V, crea task de revisión (disabled by default)
- `daily-task-summary` — 20h, resumen diario → Telegram (disabled by default)
- `morning-brief` — 8am L-V, overview matinal → Telegram (disabled by default)

---

## ¿Qué llama a qué?

| Origen | Llama a | Vía |
|---|---|---|
| Cliente MCP | `mcp-gateway` | HTTPS+Bearer → Caddy |
| `mcp-gateway` | `tasks-mcp` / `notes-mcp` / `platform-mcp` | stdio dentro del contenedor |
| Servers MCP | SQLite | volumen `data/` |
| niwa-app UI | niwa-app API | fetch local |
| niwa-app API | SQLite | mismo volumen (WAL) |
| task-executor (host) | SQLite + LLM CLI | acceso directo + subprocess |
| Scheduler thread | routines table → tasks / scripts / webhooks | in-process |
| Notifier | Telegram Bot API / webhook | urllib HTTPS POST |
