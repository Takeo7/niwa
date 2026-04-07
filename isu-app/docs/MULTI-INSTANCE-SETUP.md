# Yume — Multi-Instance Setup (Mac Mini)

## Objetivo

Ejecutar múltiples instancias independientes de Yume en un mismo Mac Mini. Cada usuario tiene su propio Desk, agentes, proyectos, Telegram bot y dominios.

---

## Arquitectura

```
Mac Mini (M2/M4, 16GB+ RAM)
│
├── Infraestructura compartida
│   ├── Traefik (reverse proxy, HTTPS, puertos 80/443)
│   ├── Supabase (opcional, si ambos lo usan)
│   └── DNS wildcard: *.tudominio.com → Mac Mini IP
│
├── Instancia: Arturo
│   ├── OpenClaw gateway (:18789)
│   ├── Desk (:8080) → desk.arturo.tudominio.com
│   ├── Agentes (main, iris, claude-code)
│   ├── Task executor + worker
│   ├── Cron jobs
│   ├── Telegram bot (token A)
│   ├── n8n (:5678) → n8n.arturo.tudominio.com
│   └── Proyectos desplegados → *.arturo.tudominio.com
│
├── Instancia: Pareja
│   ├── OpenClaw gateway (:18790)
│   ├── Desk (:8081) → desk.pareja.tudominio.com
│   ├── Agentes (main, iris, claude-code)
│   ├── Task executor + worker
│   ├── Cron jobs
│   ├── Telegram bot (token B)
│   ├── n8n (:5679) → n8n.pareja.tudominio.com
│   └── Proyectos desplegados → *.pareja.tudominio.com
│
└── Recursos compartidos
    ├── Docker engine
    ├── Traefik
    ├── Certificados HTTPS (Let's Encrypt)
    └── Red local
```

## Recursos necesarios

| Componente | RAM por instancia | CPU | Disco |
|------------|------------------|-----|-------|
| OpenClaw gateway | ~50MB | mínimo | <100MB |
| Desk (Python) | ~30MB | mínimo | ~50MB + DB |
| Task executor | ~10MB idle | burst al ejecutar | - |
| Agente ejecutando | ~200-500MB | 1 core burst | temporal |
| n8n | ~150MB | mínimo | ~100MB |
| Supabase (compartido) | ~500MB | bajo | ~200MB |
| Traefik (compartido) | ~30MB | mínimo | <50MB |

**Total por instancia:** ~450MB idle, ~1GB con agente ejecutando.
**Total para 2 instancias:** ~2GB idle, ~3GB pico. Un Mac Mini con 16GB va sobrado.

## Empaquetado: `yume-setup`

### Concepto

Un CLI o script que automatice la creación de instancias:

```bash
# Crear nueva instancia
yume-setup create --name "arturo" --domain "arturo.tudominio.com" --telegram-token "BOT_TOKEN"

# Resultado:
# - Crea /opt/yume/instances/arturo/
# - Genera docker-compose.yml con puertos únicos
# - Crea .openclaw/ con config base
# - Configura Desk con credenciales
# - Registra en Traefik
# - Inicia todos los servicios

# Listar instancias
yume-setup list

# Parar/arrancar
yume-setup stop arturo
yume-setup start arturo

# Eliminar
yume-setup destroy arturo
```

### Estructura por instancia

```
/opt/yume/
├── shared/
│   ├── traefik/
│   │   └── docker-compose.yml
│   └── supabase/  (opcional)
│
├── instances/
│   ├── arturo/
│   │   ├── docker-compose.yml        # Stack completo
│   │   ├── .env                       # Puertos, tokens, dominio
│   │   ├── .openclaw/                 # Config OpenClaw
│   │   │   ├── openclaw.json
│   │   │   ├── agents/
│   │   │   ├── cron/
│   │   │   └── workspace/
│   │   │       ├── Desk/
│   │   │       ├── scripts/
│   │   │       └── Workspace-{name}/
│   │   └── data/
│   │       └── desk.sqlite3
│   │
│   └── pareja/
│       └── (misma estructura)
│
└── yume-setup                         # CLI de gestión
```

### docker-compose.yml por instancia (template)

```yaml
# Auto-generado por yume-setup
# Instancia: ${INSTANCE_NAME}

services:
  openclaw:
    image: openclaw:latest
    container_name: ${INSTANCE_NAME}-openclaw
    restart: unless-stopped
    network_mode: host
    environment:
      - OPENCLAW_PORT=${OPENCLAW_PORT}
      - OPENCLAW_WORKSPACE=/workspace
    volumes:
      - ./.openclaw:/home/yume/.openclaw
      - ./workspace:/workspace

  desk:
    image: python:3.12-slim
    container_name: ${INSTANCE_NAME}-desk
    restart: unless-stopped
    network_mode: host
    command: ["python", "/app/backend/app.py"]
    environment:
      - DESK_PORT=${DESK_PORT}
      - DESK_DB_PATH=/app/data/desk.sqlite3
      - DESK_PUBLIC_BASE_URL=https://desk.${DOMAIN}
      - DESK_USERNAME=${DESK_USERNAME}
      - DESK_PASSWORD=${DESK_PASSWORD}
      - DESK_SESSION_SECRET=${SESSION_SECRET}
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
      - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
    labels:
      - traefik.enable=true
      - traefik.http.routers.${INSTANCE_NAME}-desk.rule=Host(`desk.${DOMAIN}`)
      - traefik.http.routers.${INSTANCE_NAME}-desk.entrypoints=websecure
      - traefik.http.routers.${INSTANCE_NAME}-desk.tls.certresolver=letsencrypt
      - traefik.http.services.${INSTANCE_NAME}-desk.loadbalancer.server.port=${DESK_PORT}
      - traefik.http.middlewares.${INSTANCE_NAME}-sso.forwardauth.address=http://127.0.0.1:${DESK_PORT}/auth/check
    volumes:
      - ./.openclaw/workspace/Desk:/app:rw
      - ./.openclaw:/home/yume/.openclaw:ro
      - ./.openclaw/cron:/home/yume/.openclaw/cron:rw

  n8n:
    image: n8nio/n8n:latest
    container_name: ${INSTANCE_NAME}-n8n
    restart: unless-stopped
    environment:
      - N8N_PORT=${N8N_PORT}
      - N8N_BASIC_AUTH_USER=${DESK_USERNAME}
      - N8N_BASIC_AUTH_PASSWORD=${N8N_PASSWORD}
      - N8N_HOST=n8n.${DOMAIN}
    labels:
      - traefik.enable=true
      - traefik.http.routers.${INSTANCE_NAME}-n8n.rule=Host(`n8n.${DOMAIN}`)
      - traefik.http.routers.${INSTANCE_NAME}-n8n.entrypoints=websecure
      - traefik.http.routers.${INSTANCE_NAME}-n8n.tls.certresolver=letsencrypt
      - traefik.http.routers.${INSTANCE_NAME}-n8n.middlewares=${INSTANCE_NAME}-sso@docker
      - traefik.http.services.${INSTANCE_NAME}-n8n.loadbalancer.server.port=${N8N_PORT}
    volumes:
      - ./data/n8n:/home/node/.n8n
```

### .env por instancia (template)

```env
INSTANCE_NAME=arturo
DOMAIN=arturo.tudominio.com

# Puertos (auto-asignados, no conflictan entre instancias)
OPENCLAW_PORT=18789
DESK_PORT=8080
N8N_PORT=5678

# Credenciales (generadas en setup)
DESK_USERNAME=arturo
DESK_PASSWORD=<generada>
SESSION_SECRET=<generada>
N8N_PASSWORD=<generada>

# Telegram
TELEGRAM_BOT_TOKEN=<token del bot>
TELEGRAM_CHAT_ID=<chat id>

# API keys (usuario proporciona)
ANTHROPIC_API_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
```

## Setup interactivo (visión)

```
$ yume-setup create

  ╭─────────────────────────────╮
  │  YUME — Nueva instancia     │
  ╰─────────────────────────────╯

  Nombre de usuario: pareja
  Dominio base: pareja.wagener.dev

  ¿Telegram bot? (s/n): s
  Bot token: 123456:ABC...
  Chat ID: 987654

  ¿API key de Anthropic?: sk-ant-...
  ¿Google OAuth? (s/n): n

  Creando instancia...
  ✓ Directorio /opt/yume/instances/pareja/
  ✓ Config OpenClaw
  ✓ Base de datos Desk
  ✓ docker-compose.yml
  ✓ Registrado en Traefik
  ✓ Servicios iniciados

  ✅ Instancia "pareja" lista

  Desk:     https://desk.pareja.wagener.dev
  Terminal: https://terminal.pareja.wagener.dev
  n8n:      https://n8n.pareja.wagener.dev

  Usuario: pareja
  Password: kX7m2pQ4vL (cámbiala en Desk > Config)
```

## Migración desde VPS actual

Para mover la instancia actual del VPS al Mac Mini:

```bash
# En el VPS — exportar
yume-setup export arturo > arturo-backup.tar.gz

# En el Mac Mini — importar
yume-setup import arturo-backup.tar.gz
yume-setup start arturo
```

El backup incluye: workspace completo, DB, cron jobs, proyectos desplegados, config.

## Notas

- **Aislamiento**: cada instancia es completamente independiente. No comparten DB, agentes, ni proyectos.
- **Seguridad**: cada Desk tiene su propio SSO. Los proyectos de una instancia no son accesibles desde otra.
- **Recursos**: el Mac Mini M2/M4 con 16GB soporta 2-3 instancias simultáneas sin problema. Con 32GB podrían ser 5+.
- **API keys**: cada instancia puede usar la misma API key de Anthropic o diferentes. Si comparten key, comparten rate limits.
- **Dominios**: se recomienda un dominio por usuario (arturo.tudominio.com, pareja.tudominio.com) con wildcard DNS para cada uno.
