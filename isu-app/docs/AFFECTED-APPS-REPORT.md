# Aplicaciones afectadas por "unauthorized" — Desk SSO

> Subtarea 3/4 de "Revisar proyectos/webs que cargan con unauthorized"
> Fecha: 2026-03-27

---

## Resumen ejecutivo

**5 aplicaciones** están protegidas por el middleware `desk-sso@docker` (Traefik ForwardAuth) y son susceptibles de mostrar "unauthorized" al cargar. La causa raíz es la misma para todas: **la cookie `desk_session` no incluye `Domain=.yumewagener.com`**, por lo que el navegador solo la envía a `desk.yumewagener.com` y no a los subdominios.

---

## Apps afectadas (protegidas por desk-sso)

| # | App | Dominio | Puerto | Compose file | SSO | Estado actual |
|---|-----|---------|--------|-------------|-----|---------------|
| 1 | **InvestmentDesk** | `invest.yumewagener.com` | 127.0.0.1:8090 | `infra/docker-compose.services.yml` | `desk-sso@docker` | **AFECTADA** |
| 2 | **Pumicon** (game-proxy) | `pumicon.yumewagener.com` | proxy→3000 | `infra/docker-compose.services.yml` | `desk-sso@docker` | **AFECTADA** |
| 3 | **Terminal** (terminal-proxy) | `terminal.yumewagener.com` | proxy→7682 | `infra/docker-compose.services.yml` | `desk-sso@docker` | **AFECTADA** |
| 4 | **n8n** | `n8n.yumewagener.com` | 0.0.0.0:5678 | `n8n/docker-compose.yml` | `desk-sso@docker` | **AFECTADA** |
| 5 | **TrendFlow** | `trendflow.yumewagener.com` | 127.0.0.1:8001 | `trendflow/docker-compose.prod.yml` | `desk-sso@docker` | **AFECTADA** |

## Apps NO afectadas

| App | Dominio | Razón |
|-----|---------|-------|
| **Desk** | `desk.yumewagener.com` | Es el auth provider. La cookie se emite para este host, así que siempre la recibe. |
| **Manduka** | `mandukaeat.yumewagener.com` | No usa desk-sso middleware. Auth propia vía Supabase. |
| **Supabase stack** | Solo puertos internos | No expuestos vía Traefik con SSO. |

---

## Patrón común de fallo

Todas las apps afectadas comparten **exactamente el mismo patrón**:

```
1. Usuario inicia sesión en desk.yumewagener.com
   → Cookie: desk_session=<token>; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800
   → SIN Domain → cookie válida SOLO para desk.yumewagener.com

2. Usuario navega a invest.yumewagener.com (o pumicon, terminal, n8n, trendflow)
   → Navegador NO envía cookie desk_session (host diferente, sin Domain compartido)

3. Traefik intercepta → ForwardAuth → GET http://127.0.0.1:8080/auth/check
   → Traefik reenvía headers del navegador (trustForwardHeader=true)
   → Pero los headers NO incluyen Cookie: desk_session (porque el navegador no la envió)

4. /auth/check (app.py:1808-1814) → is_authenticated() = false → 401
   → Response: {"error":"unauthorized"}

5. Traefik devuelve 401 al navegador → usuario ve "unauthorized"
```

### Verificación en código

- **Set-Cookie (login):** `app.py:1895` — `{DESK_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=...` — **no `Domain`**
- **Set-Cookie (logout):** `app.py:1738` — `{DESK_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0` — **no `Domain`**
- **ForwardAuth check:** `app.py:1808-1814` — devuelve 401 con `{"error":"unauthorized"}` si no hay cookie válida
- **Documentación errónea:** `VPS-STATE.md:45` dice `Domain=.yumewagener.com` pero el código real no lo incluye

---

## Detalle por app afectada

### 1. InvestmentDesk (`invest.yumewagener.com`)

- **Tipo de fallo:** ForwardAuth 401 por falta de cookie
- **Middleware:** `desk-sso@docker` (docker-compose.services.yml:24)
- **Fallo adicional:** El frontend de Desk (`app.js:258`) hace `fetch('https://invest.yumewagener.com/api/portfolio')` sin `credentials: 'include'`, por lo que incluso si se arregla la cookie con Domain, las llamadas cross-origin desde app.js seguirán fallando
- **Severidad:** ALTA — la app es completamente inaccesible

### 2. Pumicon (`pumicon.yumewagener.com`)

- **Tipo de fallo:** ForwardAuth 401 por falta de cookie
- **Middleware:** `desk-sso@docker` (docker-compose.services.yml:59)
- **Arquitectura:** game-proxy (socat) → pumicon-serve (node serve estático)
- **Severidad:** ALTA — la app es completamente inaccesible

### 3. Terminal (`terminal.yumewagener.com`)

- **Tipo de fallo:** ForwardAuth 401 por falta de cookie
- **Middleware:** `desk-sso@docker` (docker-compose.services.yml:73)
- **Arquitectura:** terminal-proxy (socat) → servicio en puerto 7682 del host
- **Severidad:** ALTA — la app es completamente inaccesible

### 4. n8n (`n8n.yumewagener.com`)

- **Tipo de fallo:** ForwardAuth 401 por falta de cookie
- **Middleware:** `desk-sso@docker` (labels en el container n8n activo)
- **Nota:** n8n tiene su propia basic auth (`N8N_BASIC_AUTH_ACTIVE=true`), así que incluso si desk-sso pasara, el usuario vería otra pantalla de login
- **Doble auth:** desk-sso ForwardAuth + n8n basic auth — dos barreras
- **Severidad:** ALTA — la primera barrera (desk-sso) bloquea completamente

### 5. TrendFlow (`trendflow.yumewagener.com`)

- **Tipo de fallo:** ForwardAuth 401 por falta de cookie
- **Middleware:** `desk-sso@docker` (docker-compose.prod.yml:31)
- **Severidad:** ALTA — la app es completamente inaccesible

---

## Causa raíz única

**Una sola línea de código** causa el fallo en las 5 apps:

`app.py:1895` — El `Set-Cookie` no incluye `Domain=.yumewagener.com`

Según RFC 6265 §4.1.2.3: una cookie sin atributo `Domain` explícito solo aplica al host exacto que la emitió. No se envía a subdominios.

---

## Cómo reproducir

1. Iniciar sesión en `https://desk.yumewagener.com/login`
2. Verificar que la sesión funciona en desk (acceder a `/api/dashboard` → 200 OK)
3. Abrir nueva pestaña → navegar a `https://invest.yumewagener.com/`
4. **Resultado:** página muestra "unauthorized" (401)
5. Abrir DevTools → Application → Cookies: confirmar que `desk_session` solo existe para `desk.yumewagener.com`, no para `invest.yumewagener.com`
6. Repetir paso 3-4 con pumicon, terminal, n8n, trendflow → mismo resultado

### Reproducción vía curl (desde el servidor)

```bash
# Simular lo que hace Traefik ForwardAuth cuando el navegador NO envía cookie:
curl -s http://127.0.0.1:8080/auth/check
# Resultado esperado: {"error":"unauthorized"} con HTTP 401

# Simular lo que hace Traefik ForwardAuth cuando el navegador SÍ envía cookie:
curl -s -H "Cookie: desk_session=<token_valido>" http://127.0.0.1:8080/auth/check
# Resultado esperado: {"ok": true} con HTTP 200
```

---

## Fix necesario (requiere intervención manual — app.py es archivo protegido)

El fix es añadir `Domain=.yumewagener.com; Secure` a las dos líneas de Set-Cookie en `app.py`:

- **Línea 1895** (login): añadir `Domain=.yumewagener.com; Secure`
- **Línea 1738** (logout): añadir `Domain=.yumewagener.com; Secure`

> **NOTA:** `backend/app.py` es un archivo protegido. Este cambio requiere intervención manual.
