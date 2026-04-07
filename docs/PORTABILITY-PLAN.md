# Niwa — Plan de portabilidad e instalación

> **Fecha:** 2026-04-07
> **Goal:** Niwa instalable en cualquier máquina (Mac/Linux con Docker), con setup interactivo, opcionalmente integrado con OpenClaw o standalone para el usuario.
> **Status:** plan, no implementado.

---

## 1. Objetivos y restricciones

### Objetivos
1. **Un solo comando de instalación** desde una máquina limpia con Docker → Niwa funcionando con sus 44 tools.
2. **Setup interactivo** que pregunte al usuario por las decisiones (paths, dominio, tokens, modo) en vez de tener que editar archivos a mano.
3. **Independiente de OpenClaw**: OpenClaw es *opcional*. Si está presente, Niwa se auto-registra. Si no, el usuario obtiene el endpoint y token y los configura donde quiera.
4. **Reproducible**: la misma instalación da el mismo resultado, y se puede uninstall limpio.
5. **Portable**: cero rutas hardcoded a `/Users/yume/`. Todo configurable.

### Restricciones (no cambian)
- Stack Docker (gateway oficial + caddy + socket-proxy + 3 servers propios)
- Single-user (no multi-tenant)
- Backend Python para los MCP servers (consistencia con lo actual)
- Cloudflare Tunnel para exposición pública (no exponemos puertos directos)
- Filosofía "trust the model": el setup pregunta lo mínimo y asume defaults sensatos

---

## 2. Lo que actualmente impide portar Niwa (blockers)

### 2.1 Paths hardcoded a `/Users/yume/`
- `docker-compose.yml`: 7 bind mounts apuntan a `/Users/yume/...`
- Volume mount del DB en el catálogo via template `{{niwa.db_path}}` ya está parametrizado pero el valor (`/Users/yume/data/desk.sqlite3`) está hardcoded en `niwa-config.yaml`
- `secrets/mcp.env` path hardcoded en compose y caddy
- `~/.openclaw/logs/mcp-gateway.sqlite` para el log del gateway

### 2.2 Whitelist del platform-mcp es específica a Arturo
- `RESTART_WHITELIST` en `platform-mcp/server.py` lista containers `arturo-*` que solo existen en esta máquina
- Otra máquina no tiene esos containers → restart whitelist invalida

### 2.3 DB schema asumido
- `niwa-mcp` espera tablas `tasks`, `projects` con CHECK constraints específicos
- `isu-mcp` espera `notes` (con extensiones Phase 5: `type`, `metadata`, etc.) e `inbox_items`
- Una máquina nueva sin Isu instalado **no tiene esa DB**
- Necesita un bootstrap: crear DB vacía con el schema mínimo de Niwa

### 2.4 Cloudflare Tunnel
- Tunnel ID `590d0340-...` y dominio `mcp.yumewagener.com` están hardcoded en docs/cloudflared
- Otra máquina necesita su propio tunnel + dominio
- Asumimos que el usuario YA TIENE cuenta Cloudflare con un dominio (no automatizamos eso)

### 2.5 Tokens
- `~/.openclaw/secrets/mcp.env` se generó manualmente
- Cada instalación nueva debe generar sus propios tokens

### 2.6 Registro de clientes
- `claude mcp add` y `openclaw mcp set` se hicieron a mano
- En la instalación deberían ser automáticos si los binarios están presentes

---

## 3. Arquitectura objetivo (post-portabilidad)

### 3.1 Estructura del repo (la "Niwa Pack")

Lo que el usuario clona:

```
niwa/                              # repo / pack
├── README.md
├── INSTALL.md                     # guía rápida
├── LICENSE
├── setup.py                       # script interactivo
├── niwa                           # CLI wrapper (bash) → llama a setup.py con subcomandos
├── docker-compose.yml.tmpl        # template con ${VAR} placeholders
├── caddy/
│   └── Caddyfile                  # ya usa env, sirve tal cual
├── config/
│   ├── niwa-catalog.yaml.tmpl     # template
│   └── niwa-config.yaml.tmpl      # template
├── servers/
│   ├── niwa-mcp/                  # imágenes MCP propias
│   │   ├── server.py
│   │   └── Dockerfile
│   ├── isu-mcp/
│   └── platform-mcp/
├── schema/
│   ├── 001-niwa-base.sql          # tablas mínimas: projects, tasks, notes, inbox_items
│   └── 002-notes-typed.sql        # extensiones Phase 5
└── docs/
    ├── PORTABILITY-PLAN.md        # este doc
    ├── N8N-INTEGRATION.md
    └── CURRENT-STATE.md
```

### 3.2 Estructura del install (lo que se genera en la máquina del usuario)

Default `${NIWA_HOME} = ~/.niwa/`:

```
~/.niwa/
├── niwa.env                       # tokens y vars generadas, chmod 600
├── docker-compose.yml             # con paths/tokens substituidos
├── config/
│   ├── niwa-catalog.yaml          # con paths del usuario
│   └── niwa-config.yaml
├── caddy/Caddyfile                # symlink al pack o copia
├── data/
│   └── desk.sqlite3               # DB (puede ser symlink al DB existente del usuario o fresh)
├── logs/
│   ├── mcp-gateway.sqlite
│   └── caddy/
└── install.json                   # metadata del install: versión, timestamp, decisiones
```

### 3.3 Variables del install (todas en `niwa.env`)

```bash
# Identidad del install
NIWA_HOME=/Users/foo/.niwa
NIWA_VERSION=1.0.0
NIWA_INSTANCE_NAME=foo

# Paths
NIWA_DB_PATH=/Users/foo/.niwa/data/desk.sqlite3
NIWA_LOGS_DIR=/Users/foo/.niwa/logs
NIWA_CONFIG_DIR=/Users/foo/.niwa/config
NIWA_FILESYSTEM_WORKSPACE=/Users/foo/.niwa/data    # qué expone fs MCP como /workspace
NIWA_FILESYSTEM_MEMORY=/Users/foo/.niwa/memory     # qué expone como /memory

# Puertos (default loopback)
NIWA_GATEWAY_STREAMING_PORT=18810
NIWA_GATEWAY_SSE_PORT=18812
NIWA_CADDY_PORT=18811

# Modo de exposición
NIWA_MODE=local-only|remote-public|hybrid          # default: local-only
NIWA_PUBLIC_DOMAIN=mcp.example.com                 # solo si modo != local-only
NIWA_CLOUDFLARE_TUNNEL_ID=                         # solo si quiere usar tunnel

# Tokens (generados)
NIWA_REMOTE_TOKEN=<64-hex>
NIWA_LOCAL_TOKEN=<64-hex>
MCP_GATEWAY_AUTH_TOKEN=<64-hex>

# Platform MCP whitelist (configurable, lista separada por comas)
NIWA_PLATFORM_RESTART_WHITELIST=

# Integraciones detectadas
NIWA_HAS_OPENCLAW=true|false
NIWA_HAS_CLAUDE_CODE=true|false
NIWA_HAS_CLOUDFLARED=true|false
```

---

## 4. Refactors necesarios al código actual

Antes del setup script, hay que parametrizar lo que hoy está hardcoded.

### 4.1 `docker-compose.yml` → `docker-compose.yml.tmpl`
- Reemplazar todos los `/Users/yume/...` por `${NIWA_*}` vars
- Reemplazar `niwa-mcp:latest` etc. por `${NIWA_INSTANCE_NAME}-niwa-mcp:latest` (para multi-instancia en la misma máquina si hace falta) — opcional, decisión abierta
- Container names también prefijables: `${NIWA_INSTANCE_NAME}-mcp-gateway` etc.

### 4.2 `platform-mcp/server.py`
- `RESTART_WHITELIST` se carga al arrancar desde `os.environ.get("PLATFORM_RESTART_WHITELIST", "").split(",")`
- Si está vacía: el verb `container_restart` devuelve error "no whitelist configured" en vez de fallar silenciosamente
- Eso permite a cada instalación tener su propia whitelist sin tocar código

### 4.3 `niwa-config.yaml.tmpl`
- `niwa.db_path: ${NIWA_DB_PATH}`
- `isu.db_path: ${NIWA_DB_PATH}`
- (con sustitución antes del docker compose up)

### 4.4 `Caddyfile`
- Ya usa `{$NIWA_REMOTE_TOKEN}`. Verificar que el resto está parametrizado (puerto, etc.)

### 4.5 Schema bootstrap
- Extraer las tablas que Niwa necesita en archivos SQL versionados:
  - `001-niwa-base.sql`: `projects`, `tasks`, `notes` básico, `inbox_items`
  - `002-notes-typed.sql`: las 5 columnas extra de Phase A
- En el setup, si el usuario elige "fresh DB": correr ambos en orden contra una `desk.sqlite3` vacía
- Si usa DB existente: solo correr migraciones que no estén ya aplicadas (hace falta tabla `_niwa_migrations` para tracking)

### 4.6 Logs path
- Los logs del gateway y caddy viven en `${NIWA_LOGS_DIR}` en vez de `~/.openclaw/logs/`

---

## 5. Setup script — flujo interactivo

CLI wrapper: `./niwa install`, `./niwa uninstall`, `./niwa upgrade`, `./niwa status`, `./niwa logs`.

`./niwa install` ejecuta:

### Step 0 — Pre-flight checks (silent)
- Detect OS (`uname -s`)
- Detect Docker (`docker --version` + `docker info`)
- Detect runtime: OrbStack (`/Users/$(whoami)/.orbstack/run/docker.sock`), Docker Desktop, Colima, Podman
- Detect optional: `which openclaw`, `which claude`, `which cloudflared`
- Detect Python 3.10+
- Comprobar que los puertos default (18810/18811/18812) están libres
- Si algo falla → error claro con la solución sugerida

### Step 1 — Bienvenida
```
🌿 Niwa MCP installer
   This will install Niwa MCP gateway with 4 servers (44 tools) on your machine.
   Detected: macOS / Docker (OrbStack) / OpenClaw ✓ / Claude Code ✓ / cloudflared ✓
   Continue? [Y/n]
```

### Step 2 — Modo de exposición
```
How will you use Niwa?
  [1] Local only (recommended for first install)
      → Niwa runs on 127.0.0.1, only local clients (Claude Code, Yume on this machine)
  [2] Local + remote (HTTPS via Cloudflare Tunnel + bearer auth)
      → For accessing Niwa from your phone, ChatGPT, etc.
  [3] Custom (advanced — pick each piece)
Choice [1]:
```

### Step 3 — Install location
```
Where to install? [default: ~/.niwa]
Instance name (used for container prefixes) [default: hostname]
```

### Step 4 — Database
```
Niwa needs a SQLite database with tables: projects, tasks, notes, inbox_items.
  [1] Create a fresh empty database (recommended for new installs)
  [2] Use an existing database (e.g. if you already have one from another install)
      → ask for path
      → run migrations to add Niwa columns if missing
Choice [1]:
```

Si elige (1): crea `~/.niwa/data/desk.sqlite3` y aplica `001-niwa-base.sql` + `002-notes-typed.sql`.

Si elige (2): pide path, hace backup en `~/.niwa/data/backup-pre-niwa.sqlite3`, comprueba qué migraciones faltan, las aplica preguntando confirmación.

### Step 5 — Filesystem MCP scope
```
The filesystem MCP server will give the LLM read+write access to specific directories.
  Default scope:
    /workspace → ~/.niwa/data       (for files Niwa works with)
    /memory    → ~/.niwa/memory     (will be created)
  Add additional directories? [y/N]
```

### Step 6 — Platform MCP whitelist
```
The platform MCP server can list/restart Docker containers.
For the restart verb, you must whitelist which containers it can touch.
  Detected running containers:
    [x] arturo-cron
    [x] arturo-n8n
    [ ] niwa-mcp-gateway       (excluded — would kill the gateway itself)
    [x] my-app
    [ ] postgres-prod          (excluded — sensitive)
  Use spacebar to toggle, enter to confirm.
```

(Default: pre-marca todos excepto los del propio Niwa.)

### Step 7 — Tokens
```
Niwa needs 2 auth tokens (local-trusted and remote-restricted).
  [1] Generate them automatically (recommended)
  [2] Paste your own (e.g. if migrating from another install)
Choice [1]:
```

### Step 8 — Public exposure (solo si Step 2 != local-only)
```
Public domain: e.g. mcp.example.com
Cloudflare Tunnel:
  [1] Use existing tunnel (provide tunnel ID)
  [2] Create a new tunnel via cloudflared (requires logged-in cloudflared)
  [3] Skip — you'll configure routing manually
```

### Step 9 — Cliente registration
```
Register Niwa with detected clients:
  [x] Claude Code (user-scope, so all `claude` invocations see Niwa)
  [x] OpenClaw (uses SSE transport, you'll get the SSE endpoint)
Continue? [Y/n]
```

### Step 10 — Confirmación + ejecución
Muestra un resumen de TODO lo que va a hacer:
```
Summary:
  Install location: ~/.niwa
  Mode: local-only
  Database: fresh at ~/.niwa/data/desk.sqlite3
  Filesystem scope: ~/.niwa/data, ~/.niwa/memory
  Restart whitelist: arturo-cron, arturo-n8n, my-app
  Tokens: auto-generated
  Clients: Claude Code (user), OpenClaw

Proceed? [Y/n]
```

Si confirma, ejecuta:
1. `mkdir -p ~/.niwa/{config,data,logs,caddy}`
2. Genera `~/.niwa/niwa.env` con chmod 600
3. Sustituye templates → archivos finales
4. Bootstrap DB si fresh
5. `docker build -t ${INSTANCE}-niwa-mcp:latest niwa-mcp/`
6. Idem para isu-mcp y platform-mcp
7. `docker compose -f ~/.niwa/docker-compose.yml up -d`
8. Espera 5s, healthcheck contra el gateway local
9. Si modo remote: añade hostname al cloudflared config + reload
10. Si claude code detectado: `claude mcp add --scope user --transport http niwa http://localhost:${NIWA_GATEWAY_STREAMING_PORT}/mcp`
11. Si openclaw detectado: `openclaw mcp set niwa '{"type":"sse","url":"http://localhost:${NIWA_GATEWAY_SSE_PORT}/sse"}'`
12. Test final: handshake + tools/list (debe devolver 44)

### Step 11 — Output final
```
✅ Niwa is up.

  Endpoints:
    Local (Claude Code):  http://localhost:18810/mcp
    Local (OpenClaw):     http://localhost:18812/sse
    Public:               https://mcp.example.com/mcp  (Bearer NIWA_REMOTE_TOKEN)

  Token (remote):  abc123...   (also in ~/.niwa/niwa.env)
  Tools available: 44 (niwa: 7, isu: 22, platform: 4, filesystem: 11)

  Next steps:
    - Test from Claude Code: `claude` then ask "list mis tareas pendientes"
    - Configure other clients with the URL+token above
    - View logs: `./niwa logs`
    - Uninstall: `./niwa uninstall`

  Docs: ~/.niwa/README.md
```

---

## 6. Comandos del CLI `niwa`

| Command | Qué hace |
|---|---|
| `niwa install` | Setup interactivo (Steps 0-11) |
| `niwa install --headless --config niwa.json` | No interactivo, lee de un JSON |
| `niwa uninstall` | `docker compose down`, remove ~/.niwa, remove de claude/openclaw, remove tunnel hostname |
| `niwa upgrade` | Pull nueva versión del repo, re-aplica migraciones, rebuild imágenes, restart |
| `niwa status` | Muestra qué containers están up, cuántos tools, healthcheck de cada endpoint |
| `niwa logs [server]` | Tail de logs (gateway por default; opcional `niwa-mcp`, `isu-mcp`, `platform-mcp`, `caddy`) |
| `niwa restart` | Restart de todos los containers |
| `niwa token rotate` | Genera nuevos tokens, actualiza niwa.env, recrea caddy, re-registra en claude/openclaw |
| `niwa add-server <name> <image>` | Añade un MCP server custom al catálogo |
| `niwa config edit` | Abre niwa.env en `$EDITOR` |

---

## 7. Distribución

### 7.1 Repo público / privado
- Crear `github.com/yumewagener/niwa` (privado primero, público después si tiene sentido)
- Tags semver: `v0.1.0` (alpha), `v1.0.0` (stable)

### 7.2 Métodos de instalación
1. **Git clone** (default):
   ```bash
   git clone https://github.com/yumewagener/niwa ~/niwa-pack
   cd ~/niwa-pack && ./niwa install
   ```
2. **Curl one-liner** (cómodo, riesgoso): para v1.0.0+
   ```bash
   curl -sSf https://niwa.dev/install.sh | sh
   ```
3. **Docker installer** (alternativa, no requiere git/python en el host):
   ```bash
   docker run --rm -it -v ~/.niwa:/niwa -v /var/run/docker.sock:/var/run/docker.sock niwa/setup install
   ```

Para v0.1: solo git clone. Lo demás después.

---

## 8. Fases de implementación

| Phase | Scope | Estimación | Dependencias |
|---|---|---|---|
| **P0 — Decisiones** | Resolver las 7 open questions de la sección 10 | 1h conversación con Arturo | — |
| **P1 — Refactor portabilidad** | Replace de paths hardcoded por ${VAR}, env-driven whitelist, verifica que install actual sigue funcionando | 3-4h | P0 |
| **P2 — Schema bootstrap** | Extraer SQL, migraciones versionadas, tabla _niwa_migrations | 1-2h | P1 |
| **P3 — Setup script (interactivo)** | `setup.py` con todos los steps, modo local-only primero | 4-6h | P1, P2 |
| **P4 — Auto-registro clientes** | Detecta openclaw/claude code, registra automáticamente | 1-2h | P3 |
| **P5 — Modo remote** | Cloudflared integration, generación de Caddyfile con dominio, healthchecks remotos | 2-3h | P3 |
| **P6 — Uninstall + upgrade** | Symmetric to install, idempotente | 2-3h | P3 |
| **P7 — Doc + README** | Install guide, troubleshooting, FAQ | 1-2h | todos |
| **P8 — Test fresh machine** | Probar desde cero en una VM Linux y un Mac limpio (o OrbStack VM nueva) | 1-2h | P7 |
| **P9 — Headless mode** | `niwa install --config foo.json` para CI/automation | 1-2h | P8 |

**Total estimado:** ~20-30h de trabajo, repartido en 5-7 sesiones.

**Mínimo viable (MVP) para "instalable en otra máquina":** P0 + P1 + P2 + P3 + P4 + P7 = ~12-16h.

---

## 9. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El refactor de paths rompe el install actual | P1 incluye verificación de que el current install sigue arriba al final. Backup pre-cambios. |
| Schemas divergen entre Niwa standalone y Niwa+Isu | Versionar migraciones con hash. La tabla `_niwa_migrations` registra qué se aplicó cuando. |
| OrbStack-only path para socket-proxy | Auto-detect del runtime en Step 0; soportar Docker Desktop, Colima, Podman como alternativos |
| Tokens regenerados rompen clientes ya configurados | `niwa token rotate` actualiza claude/openclaw automáticamente |
| Cloudflared interactive auth | El installer detecta si cloudflared está logged-in; si no, pide al usuario que ejecute `cloudflared login` antes |
| Conflictos de puerto en otra máquina | Step 0 verifica puertos libres; permite override |
| Versiones de Docker MCP Gateway cambian APIs | Pinning de versión en compose (ya hacemos `docker/mcp-gateway:latest` — debería ser `:v2.0.1` específicamente) |

---

## 10. Decisiones tomadas (2026-04-07)

| # | Pregunta | Decisión |
|---|---|---|
| 1 | Niwa standalone o con Isu | **Con Isu siempre.** Schema completo de Isu se empaqueta en `schema/001-isu-base.sql`. NO se porta la app web de Isu, solo la DB schema. |
| 2 | Multi-instancia | Single instance |
| 3 | Default exposición | Opt-in (default local-only) |
| 4 | Runtime | Solo Docker socket-compatible |
| 5 | Repo | Privado primero |
| 6 | Versionado | Semver + `niwa upgrade` |
| 7 | Lenguaje setup | Python |
| **8** | **Nombres renombrables** | **Sí.** Instance name + cada MCP server name renombrable en el wizard. Defaults: `niwa`, `isu`, `platform`, `filesystem`. Renombrado post-install via `niwa rename` (Phase 2, no MVP). |

## 10b. Naming layers (todas configurables)

| Layer | Variable | Default | Ejemplo personalizado |
|---|---|---|---|
| Instance name | `NIWA_INSTANCE_NAME` | `niwa` | `atlas`, `garden`, `vault` |
| Install dir | `NIWA_HOME` | `~/.${INSTANCE_NAME}` | `~/.atlas` |
| Container prefix | derivado de instance | `${INSTANCE_NAME}-` | `atlas-mcp-gateway` |
| Network name | derivado | `${INSTANCE_NAME}-mcp` | `atlas-mcp` |
| Image tag | derivado | `${INSTANCE_NAME}-niwa-mcp:latest` | `atlas-tasks-mcp:latest` |
| MCP server "tasks" | `NIWA_TASKS_SERVER_NAME` | `niwa` | `tasks`, `kanban` |
| MCP server "notes" | `NIWA_NOTES_SERVER_NAME` | `isu` | `notes`, `vault` |
| MCP server "platform" | `NIWA_PLATFORM_SERVER_NAME` | `platform` | `docker`, `ops` |
| MCP server "filesystem" | `NIWA_FILESYSTEM_SERVER_NAME` | `filesystem` | `files`, `fs` |

Las variables se setean en `niwa.env` y los templates las sustituyen.

**Caveat documentado:** cambiar nombre post-install requiere re-registrar clientes (Claude Code, OpenClaw). El comando `niwa rename <old> <new>` (Phase 2) automatiza esto. En MVP los nombres se eligen una vez al instalar y no se cambian.

## 10c. Open questions originales (resueltas)

1. **Niwa standalone o solo Niwa+Isu?**
   - **A)** Niwa puede vivir sin Isu, con un schema mínimo propio (projects/tasks/notes/inbox_items). Más portable, menos features fuera de la caja.
   - **B)** Niwa requiere el schema completo de Isu siempre. Más coherente con tu sistema actual, pero asume Isu. Mi voto: **A**.

2. **Multi-instancia en la misma máquina?**
   - ¿Quieres poder tener `niwa-arturo` y `niwa-trabajo` en el mismo Mac sin que choquen, o always single-instance? Mi voto: **single-instance** para v1, multi-instancia es complejidad innecesaria.

3. **Default de exposición pública: opt-in o opt-out?**
   - Mi voto: **opt-in** (default = local-only). El usuario que quiera remote lo elige explícitamente.

4. **Container runtime support: solo Docker socket-compatible o también Podman API?**
   - Mi voto: **solo socket-compatible**. Cualquier daemon que exponga `/var/run/docker.sock` funciona (OrbStack, Docker Desktop, Colima, rootful Podman). Podman rootless es otro mundo, lo dejaría fuera.

5. **Repo público o privado?**
   - Mi voto: **privado** primero (mientras maduramos), público en algún momento si crees que tiene tracción.

6. **Versionado**:
   - ¿Tags semver con `niwa upgrade` que pulla del git? ¿O versiones inmutables y reinstall? Mi voto: **semver + upgrade** con backup automático.

7. **Lenguaje del setup script**:
   - **A) Python**: ya está en los servers, plataforma neutral, rich prompting via `questionary` (1 dep) o `input()` puro (0 deps). Mi voto.
   - **B) Bash**: cero dependencias adicionales pero feo para flujos interactivos.
   - **C) Go binary**: cero deps en runtime pero requiere build pipeline.

---

## 11. Lo que NO entra en este plan (anti-scope explícito)

- **Auth/OAuth para los servers MCP propios** (más allá del bearer del caddy). Niwa no autentica usuarios — el bearer único es la unidad de auth.
- **Multi-tenant**. Una instalación = un usuario.
- **Auto-update sin intervención**. El usuario corre `niwa upgrade` cuando quiere; nada se actualiza solo.
- **GUI**. Todo CLI. Si el usuario quiere UI, usa la de Isu o lo que tenga.
- **Métricas/observabilidad**. Logs en sqlite es suficiente.
- **Backups del DB** (deja eso al usuario o a un workflow de su sistema).
- **Migración automática desde otros sistemas** (Notion, Obsidian, etc.). El doc original lo descartó.
- **Containers que no sean los de Niwa** (la whitelist de platform-mcp es solo para containers que YA existen en la máquina del usuario).

---

## 12. Lo que necesito de ti para empezar

Responde a las 7 open questions de la sección 10 (o di "tus recomendaciones OK" si te valen mis votos).
Después arranco con P0 → P1 → P2... con review agent entre fases si quieres.
