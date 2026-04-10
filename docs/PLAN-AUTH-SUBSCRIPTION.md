# Plan: Autenticación por suscripción en Niwa

## Contexto

Niwa es un sistema autónomo de gestión de tareas con un executor que despacha tareas a LLMs (Claude, OpenAI, Gemini). Actualmente el executor soporta:

- **API Key**: el usuario pega una key de consola (Anthropic/OpenAI/Google) — paga por uso de API
- **Setup Token**: el usuario genera un token OAuth de Claude Code (`sk-ant-oat01-*`) — usa su suscripción Pro/Max

El objetivo es que Niwa pueda usar **suscripciones** (Claude Pro/Max, ChatGPT Plus/Pro) en vez de API keys, para todos los providers.

---

## Estado actual

### Claude (funciona)

- El usuario ejecuta `claude setup-token` en su laptop (requiere navegador)
- Obtiene un token `sk-ant-oat01-*` de larga duración (1 año)
- Lo pega en la UI de Niwa (System > Config > LLM > Setup Token)
- El executor lo inyecta como `CLAUDE_CODE_OAUTH_TOKEN` en el env del subprocess
- Claude Code CLI lo lee y autentica contra la suscripción

**Archivos relevantes:**
- `bin/task-executor.py` línea ~477: `run_env["CLAUDE_CODE_OAUTH_TOKEN"] = LLM_SETUP_TOKEN`
- `niwa-app/backend/app.py` función `apply_setup_token()`: valida formato `sk-ant-*`
- `niwa-app/frontend/static/app.js`: panel de integrations con selector API Key / Setup Token / OAuth

### OpenAI (no implementado)

OpenClaw (referencia) usa el **backend interno de ChatGPT** (`chatgpt.com/backend-api`), no la API pública (`api.openai.com/v1`).

**Flujo OAuth de OpenClaw para OpenAI:**

1. Inicia servidor HTTP local en `127.0.0.1:1455/auth/callback`
2. Abre `https://auth.openai.com/oauth/authorize` con PKCE (SHA-256)
   - Client ID: `app_EMoamEEZ73f0CkXaXp7hrann`
   - Scopes: `openid profile email offline_access`
3. Usuario autoriza en el navegador
4. Callback recibe código → intercambia por JWT access token + refresh token en `https://auth.openai.com/oauth/token`
5. JWT contiene claims: `chatgpt_account_id`, `chatgpt_plan_type`, email
6. Tokens guardados en JSON: `{ access: "jwt...", refresh: "token...", expires: timestamp }`
7. Las llamadas van a `https://chatgpt.com/backend-api` (endpoint Responses API)
8. Refresh automático cuando el access token expira

**Tokens almacenados por OpenClaw en:** `~/.openclaw/agents/[agent]/agent/auth-profiles.json`

---

## Plan de implementación para Niwa

### Fase 1: OAuth flow genérico en el backend

Crear un módulo `niwa-app/backend/oauth.py` que implemente:

```python
class OAuthFlow:
    """Generic OAuth 2.0 + PKCE flow with local callback server."""
    
    def start(provider: str) -> dict:
        """Returns {auth_url, state, code_verifier} — frontend opens auth_url in new tab."""
        
    def callback(provider: str, code: str, state: str) -> dict:
        """Exchanges code for tokens. Returns {access_token, refresh_token, expires_at, email}."""
        
    def refresh(provider: str, refresh_token: str) -> dict:
        """Uses refresh token to get new access token."""
```

**Providers a soportar:**

| Provider | Authorize URL | Token URL | Client ID | Scopes |
|---|---|---|---|---|
| OpenAI (ChatGPT) | `https://auth.openai.com/oauth/authorize` | `https://auth.openai.com/oauth/token` | `app_EMoamEEZ73f0CkXaXp7hrann` | `openid profile email offline_access` |
| Google (Gemini) | `https://accounts.google.com/o/oauth2/v2/auth` | `https://oauth2.googleapis.com/token` | (requiere crear proyecto GCP) | `https://www.googleapis.com/auth/generative-language` |

Claude no necesita OAuth genérico — ya tiene su propio `setup-token`.

### Fase 2: Endpoints API

```
GET  /api/auth/oauth/start?provider=openai    → {auth_url} (frontend abre en nueva pestaña)
GET  /api/auth/oauth/callback?code=...&state=... → guarda tokens, cierra ventana
POST /api/auth/oauth/refresh?provider=openai  → refresca access token
GET  /api/auth/oauth/status?provider=openai   → {authenticated, email, expires_at}
```

El callback escucha en el propio servidor de Niwa (puerto 28080), no en un puerto separado.

### Fase 3: Token storage

Tabla `oauth_tokens` en schema.sql:

```sql
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider    TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at  TEXT,
    email       TEXT,
    metadata    TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

### Fase 4: Executor integration

En `bin/task-executor.py`, antes de ejecutar el LLM:

```python
def _get_auth_env(provider: str) -> dict:
    """Read fresh tokens from DB, refresh if expired."""
    tokens = _read_oauth_tokens(provider)
    if not tokens:
        return {}
    
    # Auto-refresh if expired
    if tokens["expires_at"] and tokens["expires_at"] < _now_iso():
        tokens = _refresh_oauth_token(provider, tokens["refresh_token"])
    
    if provider == "openai":
        return {"OPENAI_ACCESS_TOKEN": tokens["access_token"]}
    elif provider == "google":
        return {"GOOGLE_ACCESS_TOKEN": tokens["access_token"]}
    return {}
```

### Fase 5: OpenAI Responses API client

Para usar ChatGPT backend en vez de la API pública, necesitamos un cliente custom:

```python
def _call_openai_chatgpt(prompt: str, access_token: str) -> str:
    """Call ChatGPT backend API (not api.openai.com)."""
    url = "https://chatgpt.com/backend-api/conversation"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "action": "next",
        "messages": [{"role": "user", "content": {"content_type": "text", "parts": [prompt]}}],
        "model": "gpt-4o",
    }
    # SSE streaming response...
```

**Alternativa más simple:** usar el CLI de Codex (`codex` de OpenAI) si existe, que ya maneja el auth internamente — similar a cómo usamos `claude -p`.

### Fase 6: Frontend UI

En System > Config > LLM, añadir al selector de auth:

```
Autenticación:
  [x] API Key
  [ ] Setup Token (Claude Pro/Max)
  [ ] OAuth — Iniciar sesión con ChatGPT Plus
  [ ] OAuth — Iniciar sesión con Google
  [ ] Ya autenticado (terminal)
```

Botón "Iniciar sesión" → abre nueva pestaña con el OAuth flow → callback cierra la pestaña y muestra "Autenticado como user@email.com".

---

## Consideraciones

### Riesgos

1. **ChatGPT backend API no es pública** — OpenAI podría cambiarla o bloquear accesos no oficiales
2. **Client ID de OpenClaw** — usar su client ID es un riesgo legal. Habría que registrar uno propio o usar el de Codex CLI
3. **Rate limiting** — el backend de ChatGPT tiene rate limits diferentes a la API
4. **TOS** — usar el backend de ChatGPT de forma programática puede violar los términos de servicio

### Alternativa más segura para OpenAI

En vez del backend de ChatGPT, usar el **Codex CLI** de OpenAI (si existe) que ya maneja OAuth internamente, igual que hacemos con Claude Code CLI. El usuario solo necesita:

1. Instalar Codex CLI
2. Autenticarse una vez (interactivo)
3. Niwa lo usa como `codex -p "prompt"` con el token ya guardado en el sistema

### Prioridad recomendada

1. **Ya hecho**: Claude via setup token
2. **Siguiente**: Investigar si Codex CLI soporta modo `-p` similar a Claude
3. **Si no**: Implementar OAuth flow genérico + ChatGPT backend API (complejo, frágil)
4. **Gemini**: Similar approach — buscar CLI con auth integrado antes de implementar OAuth custom

---

## Archivos a modificar

| Archivo | Cambio |
|---|---|
| `niwa-app/backend/oauth.py` | Nuevo — OAuth flow genérico |
| `niwa-app/backend/app.py` | Endpoints `/api/auth/oauth/*` |
| `niwa-app/db/schema.sql` | Tabla `oauth_tokens` |
| `bin/task-executor.py` | Leer tokens de DB, auto-refresh |
| `niwa-app/frontend/static/app.js` | Botones OAuth en integrations panel |
| `setup.py` | Config keys para OAuth client IDs |

## Referencia: código fuente OpenClaw

- OAuth flow: `/opt/homebrew/lib/node_modules/openclaw/node_modules/@mariozechner/pi-ai/dist/utils/oauth/openai-codex.js`
- Token storage: `~/.openclaw/agents/[agent]/agent/auth-profiles.json`
- Config: `~/.openclaw/openclaw.json` → `auth.profiles`
- API client: `/opt/homebrew/lib/node_modules/openclaw/dist/openai-codex-provider-DgjQM521.js`
