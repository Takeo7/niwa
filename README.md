# Niwa

> Personal MCP gateway with a React web app, 13 configurable services, autonomous 3-tier task execution, and 21 MCP tools — installable on any machine with Docker.

**Version:** 0.1.0
**Status:** beta — feature-complete and tested on macOS (OrbStack) and Linux VPS (Ubuntu 24.04). 31 smoke tests pass.

## What is Niwa

Niwa is a self-contained Docker stack you install on your machine. It gives you:

- **A React 19 web app** (Vite + TypeScript + Mantine v7) with 9 views: Dashboard, Chat, Tasks, Kanban, Projects, Notes, History, Metrics, System.
- **21 MCP tools** in the tasks-mcp server, organized in 3 domains (core 14, ops 5, files 2).
- **13 configurable services** with guided setup: 7 LLM providers, 5 image generators, 4 search engines, notifications (Telegram + webhook), hosting, and OpenClaw orchestration.
- **Two MCP gateway transports**: streamable-http (v0.2 standard — the only one used by Assistant mode) + SSE (legacy, kept only for older clients).
- **3-tier autonomous executor**: Haiku (chat) → Opus (planner) → Sonnet (executor), with automatic retry and heartbeat.
- **OAuth support**: Anthropic (API key + setup token) and OpenAI (API key + OAuth with PKCE for ChatGPT subscriptions).
- **A bearer-authed reverse proxy** (Caddy) for optional public exposure via Cloudflare Tunnel.
- **Web terminal** (ttyd) for server administration from the browser — disabled by default, enable via advanced compose overlay (see below).
- **Theme customization** with 7 presets, 7 color pickers, font selector, and radius control.

It runs as 5 long-lived containers (`mcp-gateway`, `mcp-gateway-sse`, `caddy`, `socket-proxy`, `app`) + spawns ephemeral MCP server containers per tool call. The executor runs on the host as a systemd service (Linux) or launchd agent (macOS).

> **Web terminal (advanced):** The `terminal` service (ttyd with full host access) is in `docker-compose.advanced.yml`. To enable it:
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.advanced.yml up
> ```
> Only use this in trusted environments — it runs with `privileged: true`, `pid: host`, and `network_mode: host`.

## The 9 Views

| View | Route | Description |
|------|-------|-------------|
| **Dashboard** | `/dashboard` | KPI cards, 7-day velocity chart, blocked/overdue items, project progress, activity feed |
| **Chat** | `/chat` | Conversational AI interface with session management, markdown rendering, inline image display |
| **Tasks** | `/tasks` | Sortable data table with filters (status, priority, project), task detail with labels/attachments/pipeline |
| **Kanban** | `/kanban` | Drag-and-drop board via @dnd-kit with project filter |
| **Projects** | `/projects` | Card grid with progress bars, file tree browser, file uploads |
| **Notes** | `/notes` | Markdown notes with project association, tags, and edit/preview toggle |
| **History** | `/history` | Completed task log with search, status filter, pagination, duration stats |
| **Metrics** | `/metrics` | Executor performance: success rate, completion trends, avg execution time |
| **System** | `/system` | 6 tabs: Servicios, Agentes, Config, Rutinas, Logs, Estilos |

### System Tabs

1. **Servicios** — Configure all 13 services with dynamic forms, conditional fields, OAuth flows, setup guides, and connection testing.
2. **Agentes** — Configure the 3-tier LLM agents (Chat/Planner/Executor) with model selection and max turns.
3. **Config** — Executor settings (poll interval, timeout, idle review) and app language.
4. **Rutinas** — Scheduled routines with cron expressions, enable/disable, manual trigger.
5. **Logs** — Color-coded log viewer for App, Executor, MCP, Gateway, and Sync sources.
6. **Estilos** — Theme customization: 7 presets, color pickers, font family, border radius, live preview.

## 13 Configurable Services

All services are configured through the web UI with guided setup wizards and connection testing.

### LLM Providers (7)

| Provider | Auth | Models |
|----------|------|--------|
| **Anthropic** | API key or Setup Token | Haiku 4.5, Sonnet 4.6, Opus 4.6 |
| **OpenAI** | API key or OAuth (ChatGPT subscription) | GPT-5.4, GPT-5.4 Mini, GPT-5.4 Pro, o4 Mini, o3 Pro |
| **Google** | API key | Gemini 3.1 Pro, Gemini 3 Flash, Gemini 3.1 Flash-Lite, Gemini 2.5 Pro, Gemini 2.5 Flash |
| **Ollama** | Base URL (local) | Dynamically detected from Ollama API |
| **Groq** | API key | Llama 3.3 70B, Llama 3.1 8B, Mixtral 8x7B, DeepSeek R1 Distill 70B |
| **Mistral** | API key | Mistral Large, Medium, Small, Codestral |
| **DeepSeek** | API key | DeepSeek V3 (chat), DeepSeek R1 (reasoner) |

### Image Generation (5 providers)

OpenAI DALL-E, Stability AI, Replicate, fal.ai, Together AI — all selectable from a single service with dynamic model options.

### Web Search (4 providers)

DuckDuckGo (free, no key), SearXNG (self-hosted), Tavily, Brave Search.

### Notifications

- **Telegram** — Bot token + chat ID
- **Webhook** — Generic (Slack, Discord, n8n, Make, etc.)

### Hosting

Static website hosting on subdomains with guided DNS setup, configurable domain and port.

### OpenClaw

Dynamic detection + auto-config. Modes: disabled, MCP client, bidirectional. Configures gateway URL, token, and exposed domains.

> **v0.2 — streamable-http is the standard.** OpenClaw integration (Assistant mode, `install --quick --mode assistant`) uses `streamable-http`. The SSE gateway is legacy — it remains reachable for MCP clients that have not upgraded yet, but no new integration in v0.2 targets it. See `docs/adr/0002-v02-architecture.md` for the full rationale.

## 3-Tier Autonomous Executor

The task executor (`bin/task-executor.py`) runs on the host and polls the database for pending tasks. It uses a 3-tier LLM system:

| Tier | Role | Default Model | Timeout |
|------|------|---------------|---------|
| **Tier 1: Chat** | Fast conversational responses | Haiku | 120s |
| **Tier 2: Planner** | Analyzes complexity, splits complex tasks into subtasks | Opus | 300s |
| **Tier 3: Executor** | Implements code, writes files, does real work | Sonnet | 1800s |

**How it works:**

1. **Chat tasks** (from the web UI) go directly to Tier 1 (Haiku). Simple questions get answered immediately; work requests create a new auto-assigned task.
2. **Regular tasks** go to Tier 2 (Opus) for analysis. The planner chooses:
   - **Execute directly** — simple task, proceed to Tier 3.
   - **Split into subtasks** — complex task, creates 2-5 subtasks that execute independently.
3. **Tier 3** (Sonnet) receives a rich prompt with project context, active tasks, recent completions, architectural decisions, notes, and memories. It implements the actual work.

**Additional features:**
- Concurrent execution with configurable max workers (default 3)
- Automatic retry with enriched error context on first failure
- Heartbeat thread prevents stale task detection
- Hot reload of configuration without restart
- Consecutive failure protection (pauses after 3 failures)

## 21 MCP Tools

Organized in 3 domains (`config/mcp-catalog/`):

### niwa-core (14 tools) — Tasks, projects, memory, pipeline

| Tool | Description |
|------|-------------|
| `task_list` | List tasks with filters (status, area, project, limit) |
| `task_get` | Get a single task by ID |
| `task_create` | Create a task (auto-execute with `assigned_to_claude=true`) |
| `task_update` | Update task fields |
| `task_update_status` | Change task status |
| `project_list` | List all projects |
| `project_get` | Get project details |
| `project_create` | Create a new project |
| `project_update` | Update project fields |
| `project_context` | Full project context in one call (tasks, notes, decisions) |
| `pipeline_status` | Aggregate task counts by status |
| `memory_store` | Persist facts/preferences (global or per-project) |
| `memory_search` | Search long-term memory by text |
| `memory_list` | List all memories |

### niwa-ops (5 tools) — Search, images, deployment

| Tool | Description |
|------|-------------|
| `web_search` | Search the web (SearXNG or DuckDuckGo fallback) |
| `generate_image` | Generate images from text (DALL-E, Stability, etc.) |
| `deploy_web` | Deploy a project as a static website |
| `undeploy_web` | Take down a deployed site |
| `list_deployments` | List all active deployments |

### niwa-files (2 tools) — Logging and human interaction

| Tool | Description |
|------|-------------|
| `task_log` | Record findings/progress on a task |
| `task_request_input` | Pause and ask the human a question |

## Authentication

### Web UI Login

Session-based authentication with HMAC-SHA256 signed cookies. Configurable credentials, 7-day session TTL, login rate limiting (5 attempts per 15 minutes).

### OAuth (OpenAI)

Full PKCE OAuth flow for ChatGPT subscription authentication. The web UI provides a guided flow: click "Sign in with OpenAI" → authorize in popup → tokens stored automatically. Includes automatic token refresh.

### ForwardAuth

`/auth/check` endpoint for Traefik integration — enables SSO across subdomains.

## Quick Install

**Requirements:**
- macOS or Linux (Ubuntu 22.04/24.04 tested)
- Docker (OrbStack, Docker Desktop, Colima, or rootful Docker)
- Python 3.10+
- Node.js 22+ (used in the Docker multi-stage build for the React frontend)

```bash
git clone https://github.com/Takeo7/niwa
cd niwa

# Quick install — PR-11, recommended. Non-interactive, under 10 minutes.
./niwa install --quick --mode core --yes          # Niwa standalone
./niwa install --quick --mode assistant --yes     # + OpenClaw registration (requires `openclaw` CLI)

# Or the classic interactive wizard (14 steps):
python3 setup.py install
```

**`install --quick`** asks at most: workspace root, local-only vs public, Claude/Codex credentials. Everything else is detected or auto-generated. Passes a post-install smoke that verifies the app, DB, and (in `--mode assistant`) the MCP contract via `bin/niwa-mcp-smoke`. See [INSTALL.md](INSTALL.md) for flags and exit codes.

The interactive installer is a **14-step wizard** that configures: instance name, install location, database, filesystem scope, restart whitelist, tokens, credentials, ports, LLM executor, projects, remote exposure, notifications, and MCP client registration.

**During install, `setup.py` offers to automatically install:**
- Claude CLI (via npm)
- OpenClaw (via npm)

**What gets created:**

1. `~/.niwa/` directory with `config/`, `data/`, `logs/`, `secrets/`, `caddy/`, `bin/`
2. `secrets/mcp.env` (chmod 600) with all env vars and tokens
3. `docker-compose.yml` generated from template
4. MCP catalog YAML with 4 server registrations (tasks, notes, platform, filesystem)
5. Fresh SQLite DB with schema, kanban columns, default project, and version tracking
6. 4 custom Docker images built (`tasks-mcp`, `notes-mcp`, `platform-mcp`, `niwa-app`) + `mcp/filesystem:2025.1` pulled
7. 6 containers started via `docker compose up -d`
8. Task executor installed as systemd unit (Linux) or launchd agent (macOS)
9. Hosting server installed as a system service
10. Optional: MCP client registration with Claude Code and/or OpenClaw

## CLI Commands

### setup.py commands

```bash
python3 setup.py install        # interactive 14-step wizard (default)
python3 setup.py status         # show running status (container health, endpoints)
python3 setup.py restart        # restart all Docker containers
python3 setup.py logs [service] # tail container or executor logs
python3 setup.py config         # view or update configuration
python3 setup.py backup         # online SQLite backup with 7-day rotation
python3 setup.py update         # git pull, rebuild, restart (preserves data)
python3 setup.py hosting        # set up web hosting with Caddy
python3 setup.py uninstall      # tear down (containers + images + install dir)
```

### bin/niwa management commands

```bash
bin/niwa migrate            # apply pending DB migrations
bin/niwa migrate -y         # apply without confirmation
bin/niwa version            # show version and schema info
bin/niwa check              # pre-flight health verification
```

`check` verifies: database tables exist, migrations directory present, Python syntax valid, MCP catalog JSON valid.

## Architecture

```
                      Local clients
                      (Claude Code, OpenClaw, n8n, custom)
                              │
                   ┌──────────┴──────────┐
                   │                     │
                   ▼                     ▼
        127.0.0.1:18810/mcp    127.0.0.1:18812/sse
        (streaming HTTP)        (SSE legacy)
                   │                     │
                   └──────────┬──────────┘
                              │
                      mcp-gateway (×2 twin instances)
                              │
                              │  DOCKER_HOST=tcp://socket-proxy:2375
                              ▼
                    socket-proxy (only container with Docker socket)
                              │
                              │  spawn on-demand (--rm)
                              ▼
              ┌───────────┬───────────┬───────────┐
              │           │           │           │
          tasks-mcp    notes-mcp  platform-mcp  mcp/filesystem
          (21 tools)   (notes)    (Docker ops)  (filesystem)
              │           │           │           │
              ▼           ▼           ▼           ▼
            niwa.sqlite3 (RW)    socket-proxy   /workspace + /memory


        niwa-app (React 19 + Python backend, port 8080)
        ────────────────────────────────────────────────
        Multi-stage Docker build:
          Stage 1: Node 22 → npm ci && npm run build (Vite)
          Stage 2: Python 3.12 → serves React SPA + API

        caddy (reverse proxy, bearer auth, port 18811)
        terminal (ttyd web shell, port 7681) — advanced overlay only

        task-executor (host-side, systemd/launchd)
        ────────────────────────────────────────────
        bin/task-executor.py
        3-tier: Haiku (chat) → Opus (planner) → Sonnet (executor)
        polls niwa.sqlite3 for pending tasks
```

## Docker Setup

**Multi-stage Dockerfile** (`niwa-app/Dockerfile`):
- **Stage 1** (`node:22-slim`): `npm ci` + `npm run build` produces the React production bundle
- **Stage 2** (`python:3.12.8-slim`): copies backend (pure stdlib Python, no pip), React build output, and legacy fallback. Serves on port 8080.

**5 containers** defined in `docker-compose.yml.tmpl`:

| Container | Image | Purpose | Memory |
|-----------|-------|---------|--------|
| `socket-proxy` | `tecnativa/docker-socket-proxy:0.3.0` | Filtered Docker socket proxy | 64 MB |
| `mcp-gateway` | `docker/mcp-gateway:v0.40.4` | Streamable HTTP transport (pinned) | 256 MB |
| `mcp-gateway-sse` | `docker/mcp-gateway:v0.40.4` | Legacy SSE transport (pinned) | 256 MB |
| `app` | `<instance>-app:<version>` | Niwa web app | 256 MB |
| `caddy` | `caddy:2-alpine` | Reverse proxy with bearer auth | 64 MB |

**Advanced** (in `docker-compose.advanced.yml`):

| Container | Image | Purpose | Memory |
|-----------|-------|---------|--------|
| `terminal` | `tsl0922/ttyd:1.7.7` | Web-based host terminal (privileged) | 128 MB |

Base images (Python, Node) and custom builds are pinned to specific versions. `docker/mcp-gateway` is pinned to a fixed semver tag (`v0.40.4` at time of writing) to avoid operational drift in `install --quick`; override with `NIWA_MCP_GATEWAY_IMAGE` at install time to upgrade. `caddy:2-alpine` tracks the Caddy 2.x major release.

## MCP Catalog

The 21 tasks-mcp tools are organized in 3 domain catalogs at `config/mcp-catalog/`:

- **niwa-core.json** (14 tools): task management, project management, memory, pipeline
- **niwa-ops.json** (5 tools): web search, image generation, deployment/hosting
- **niwa-files.json** (2 tools): task logging, human input requests
- **combined.json**: master catalog referencing all 3 domains

## Project Structure

```
niwa/
├── README.md                      # this file
├── setup.py                       # interactive installer (14 steps, stdlib only)
├── docker-compose.yml.tmpl        # template (setup.py generates docker-compose.yml)
├── bin/
│   ├── task-executor.py           # host-side 3-tier executor (systemd/launchd)
│   └── niwa                       # CLI: migrate, version, check
├── servers/
│   └── tasks-mcp/
│       └── server.py              # 21 MCP tools (Python + mcp SDK)
├── config/
│   └── mcp-catalog/               # 3 domain catalogs + combined.json
├── tests/
│   └── test_smoke.py              # 31 smoke tests (schema, MCP, syntax, services)
├── niwa-app/
│   ├── Dockerfile                 # multi-stage: Node 22 build → Python 3.12 runtime
│   ├── backend/
│   │   └── app.py                 # HTTP server (stdlib), 70+ API endpoints
│   ├── frontend/
│   │   ├── package.json           # React 19, Vite 8, Mantine 7, TypeScript 6
│   │   └── src/                   # 43 TypeScript files
│   │       ├── main.tsx           # entrypoint
│   │       ├── app/               # App, Router, theme
│   │       ├── shared/            # API client, queries, AppShell, types, Zustand store
│   │       └── features/          # chat, dashboard, history, kanban, metrics, notes, projects, system, tasks
│   └── db/
│       ├── schema.sql             # authoritative schema (18 tables)
│       └── migrations/            # versioned SQL migrations
├── caddy/
│   └── Caddyfile                  # reverse proxy config
└── docs/                          # internal documentation
```

## Tests

31 smoke tests across 10 test classes:

```bash
pytest tests/test_smoke.py -v
```

| Class | Tests | What it verifies |
|-------|-------|------------------|
| `TestInstalacionLimpia` | 4 | Schema creates all 18 tables, migrations are idempotent |
| `TestAutenticacion` | 2 | Default credentials detected as insecure |
| `TestSuperficieMCP` | 3 | Catalog files exist, tools match server, no duplicates across domains |
| `TestSintaxisPython` | 3 | All Python files compile without errors |
| `TestHosting` | 4 | Hosting service registered, prefix map, test action, deploy config |
| `TestImageGeneration` | 6 | Image service exists, MCP tool present, catalog entry, config from DB |
| `TestOpenClaw` | 5 | OpenClaw in registry, detect/config endpoints, prefix map, test action |
| `TestAllEndpoints` | 1 | 17 critical API endpoint strings exist in app.py |
| `TestFrontendBuild` | 3 | package.json exists, all versions pinned, 18 component files exist |

All tests are structural — they verify file existence, SQL schema correctness, string presence, and Python syntax without starting any server.

## Security

- **Default bind**: all ports on `127.0.0.1`. Not publicly reachable until you opt in.
- **Fail-fast**: the server refuses to start if bound to a non-local address with default credentials.
- **Tokens**: 256-bit (`secrets.token_hex(32)`), stored in `~/.niwa/secrets/mcp.env` (chmod 600).
- **Session security**: HMAC-SHA256 signed cookies, constant-time comparison, configurable TTL.
- **Login rate limiting**: 5 attempts per 15-minute window per IP, with lockout.
- **Trusted proxy validation**: `X-Forwarded-For` only trusted from configured proxy networks.
- **Path traversal protection**: all static file serving validates resolved paths.
- **SQL injection prevention**: parameterized queries throughout, LIKE wildcards escaped.
- **Sensitive data masking**: API keys, tokens, and secrets masked in API responses.
- **Prompt injection mitigation**: chat messages wrapped in untrusted-input delimiters.
- **Docker isolation**: only `socket-proxy` touches the Docker socket; all other containers go through the filtered proxy.

## Renameable

The 4 MCP servers are nameable per install (defaults: `tasks`, `notes`, `platform`, `filesystem`). The instance name (default `niwa`) prefixes container/image/network names so multiple installs can coexist on the same machine.

## Known Limitations

- Single-user, single-instance per install location.
- Token rotation not exposed as a command — edit `~/.niwa/secrets/mcp.env` and restart.
- The backend uses Python stdlib only (no framework) — works well for the current scope but may need a framework for significant feature additions.

## License

TBD

## Credits

Built on top of:
- [Docker MCP Gateway](https://github.com/docker/mcp-gateway) — official, used as the gateway
- [tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) — socket isolation
- [Caddy](https://caddyserver.com/) — reverse proxy
- [@modelcontextprotocol/server-filesystem](https://hub.docker.com/r/mcp/filesystem) — filesystem MCP
- [Mantine](https://mantine.dev/) — React component library
- [TanStack Query](https://tanstack.com/query) — data fetching
- [Vite](https://vite.dev/) — frontend build tool

---

*Niwa* (庭) means "garden" in Japanese — the place where the personal system grows.
