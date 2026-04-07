# Auditoría de Proxies y CORS — Desk

> Subtarea 2/4 de "Revisar proyectos/webs que cargan con unauthorized"
> Fecha: 2026-03-27

---

## 1. Mapa del flujo de peticiones HTTP

```
                        INTERNET
                           │
                     ┌─────▼──────┐
                     │   Traefik   │  (host network, :80 → :443 redirect)
                     │  LetsEncrypt│  TLS termination
                     └──────┬──────┘
                            │
         ┌──────────────────┼────────────────────────┐
         │                  │                         │
    ┌────▼────┐     ┌───────▼──────┐          ┌──────▼──────┐
    │  Desk   │     │ invest.yume… │          │ pumicon,    │
    │ :8080   │     │ :8090        │          │ terminal,   │
    │ (Flask) │     │ (Investment  │          │ n8n, etc.   │
    │         │     │  Desk)       │          │             │
    └────┬────┘     └──────────────┘          └─────────────┘
         │
         ├── /auth/check  ◄── Traefik ForwardAuth (desk-sso middleware)
         ├── /login        (form POST → Set-Cookie)
         ├── /api/*        (requiere desk_session cookie)
         └── /static/*     (sin auth)
```

### Flujo de autenticación SSO via Traefik ForwardAuth

1. Usuario accede a `invest.yumewagener.com` (o pumicon, terminal, n8n)
2. Traefik intercepta → ejecuta middleware `desk-sso@docker`
3. ForwardAuth envía petición a `http://127.0.0.1:8080/auth/check`
   - Traefik opera en `network_mode: host`, por lo que 127.0.0.1:8080 llega al contenedor `desk`
   - Traefik reenvía headers del cliente original (incluido `Cookie`) gracias a `trustForwardHeader=true`
4. `/auth/check` en app.py lee la cookie `desk_session`, verifica HMAC → responde 200 o 401
5. Si 401 → Traefik devuelve 401 al navegador (el usuario ve "unauthorized")

### Flujo de la petición cross-origin del frontend

1. `app.js` en `desk.yumewagener.com` hace `fetch('https://invest.yumewagener.com/api/portfolio')`
2. Es una petición **cross-origin** (desk → invest)
3. El navegador NO envía cookies a invest a menos que `credentials: 'include'` esté en el fetch
4. Actualmente **NO** se usa `credentials: 'include'` en esa llamada

---

## 2. Puntos donde headers de Authorization/Cookie pueden perderse

### PUNTO CRÍTICO 1: Cookie `desk_session` sin `Domain` — NO se comparte entre subdominios

**Archivo:** `backend/app.py:1895`
```
Set-Cookie: desk_session=<token>; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800
```

**Problema:** La cookie se establece **sin atributo `Domain`**. Según la especificación RFC 6265, una cookie sin `Domain` explícito se aplica SOLO al host exacto que la emitió (`desk.yumewagener.com`). **No se envía a subdominios** como `invest.yumewagener.com`, `pumicon.yumewagener.com`, etc.

**Sin embargo:** El documento `VPS-STATE.md:45` afirma que la cookie tiene `Domain=.yumewagener.com` — **esto es incorrecto**, el código real no incluye `Domain`.

**Impacto:** Traefik ForwardAuth funciona porque la petición a `/auth/check` es interna (Traefik → localhost:8080 con los headers originales del navegador reenviados). Cuando un usuario visita `invest.yumewagener.com`, el navegador SÍ envía la cookie `desk_session` en la petición original a `invest.yumewagener.com`... **solo si la cookie tiene el Domain correcto**. Sin Domain, la cookie solo se envía a `desk.yumewagener.com`.

**Flujo real con ForwardAuth:**
- Usuario visita `https://invest.yumewagener.com/`
- Navegador envía headers a Traefik, incluyendo `Cookie: desk_session=xxx` **solo si la cookie aplica a invest.yumewagener.com**
- Traefik ForwardAuth reenvía estos headers a `http://127.0.0.1:8080/auth/check`
- **Si la cookie no se envió (porque falta Domain), ForwardAuth recibe 401 → "unauthorized"**

> **ESTE ES PROBABLEMENTE EL ORIGEN DEL PROBLEMA "unauthorized" AL CARGAR WEBS.**

### PUNTO CRÍTICO 2: Logout cookie tampoco tiene Domain

**Archivo:** `backend/app.py:1738`
```
Set-Cookie: desk_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0
```
Mismo problema: sin `Domain`, el logout no limpia cookies en subdominios (si se arreglara el login para incluir Domain).

### PUNTO 3: Petición cross-origin sin `credentials: 'include'`

**Archivo:** `frontend/app.js:258`
```javascript
const resp = await fetch('https://invest.yumewagener.com/api/portfolio');
```

Esta llamada cross-origin (de desk.yumewagener.com a invest.yumewagener.com) no incluye `credentials: 'include'`, por lo que:
- El navegador **no envía cookies** con esta petición
- Si InvestmentDesk requiere auth, fallará

### PUNTO 4: Traefik ForwardAuth no configura `authResponseHeaders`

**Archivos:** `infra/docker-compose.yml:25-26`
```yaml
- traefik.http.middlewares.desk-sso.forwardauth.address=http://127.0.0.1:8080/auth/check
- traefik.http.middlewares.desk-sso.forwardauth.trustForwardHeader=true
```

No se configura `authResponseHeaders`. Esto significa que si `/auth/check` quisiera devolver headers personalizados (ej: `X-User`, `X-Email`) para que el servicio backend los reciba, no llegarían. Actualmente no es un problema funcional, pero limita la escalabilidad del SSO.

---

## 3. Problemas encontrados en CORS

### Problema A: `trigger_idle_review.py` usa `Access-Control-Allow-Origin: *`

**Archivo:** `backend/trigger_idle_review.py:38`
```python
self.send_header('Access-Control-Allow-Origin', '*')
self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
self.send_header('Access-Control-Allow-Headers', 'Content-Type')
```

- Usa wildcard `*` para Allow-Origin
- **No incluye `Access-Control-Allow-Credentials: true`**
- Según la especificación, `Allow-Origin: *` con `Allow-Credentials: true` es inválido (el navegador lo rechaza)
- Si el frontend enviara `credentials: 'include'`, el servidor debería responder con el origin exacto, no `*`
- Actualmente este endpoint se llama desde `app.js:1582` como ruta relativa (`/api/trigger/idle-review`), así que pasa por Traefik → desk-trigger container. La petición es same-origin desde `desk.yumewagener.com`, por lo que CORS no aplica. **El CORS de trigger_idle_review.py es innecesario pero no dañino en el flujo actual.**

### Problema B: Backend principal (app.py) no tiene headers CORS

El servidor Flask en `app.py` no incluye ningún header `Access-Control-Allow-*`. Cualquier petición cross-origin directa al backend Desk será bloqueada por el navegador. Esto afecta si otros subdominios intentan llamar APIs de desk directamente.

---

## 4. Resumen de hallazgos

| # | Severidad | Problema | Archivo | Impacto |
|---|-----------|----------|---------|---------|
| 1 | **ALTA** | Cookie `desk_session` sin `Domain=.yumewagener.com` | `app.py:1895` | Subdominios SSO no reciben la cookie → **"unauthorized"** |
| 2 | **ALTA** | Cookie de logout sin Domain | `app.py:1738` | Logout incompleto en subdominios |
| 3 | **MEDIA** | fetch cross-origin sin `credentials: 'include'` | `app.js:258` | Portfolio API falla silenciosamente si invest requiere auth |
| 4 | **BAJA** | ForwardAuth sin `authResponseHeaders` | `docker-compose.yml:25-26` | No pasa info de usuario a backends protegidos |
| 5 | **BAJA** | CORS `Allow-Origin: *` en trigger | `trigger_idle_review.py:38` | Sin impacto actual, pero mala práctica |
| 6 | **INFO** | VPS-STATE.md dice que cookie tiene `Domain=.yumewagener.com` pero el código no lo incluye | `VPS-STATE.md:45` vs `app.py:1895` | Documentación inconsistente |

---

## 5. Recomendaciones

### R1. Añadir `Domain=.yumewagener.com` a la cookie de sesión (REQUIERE CAMBIO EN app.py — ARCHIVO PROTEGIDO)

El cambio necesario en `app.py` sería:
```python
# Línea ~1895 (login):
Set-Cookie: desk_session={token}; Path=/; HttpOnly; SameSite=Lax; Domain=.yumewagener.com; Max-Age=...

# Línea ~1738 (logout):
Set-Cookie: desk_session=; Path=/; HttpOnly; SameSite=Lax; Domain=.yumewagener.com; Max-Age=0
```

> **NOTA:** `app.py` es un archivo protegido. Este cambio requiere intervención manual.

### R2. Añadir `Secure` a la cookie

Dado que todo el tráfico va por HTTPS (Traefik con LetsEncrypt), la cookie debería incluir `Secure` para evitar que se envíe por HTTP accidental:
```
Set-Cookie: desk_session=...; Path=/; HttpOnly; SameSite=Lax; Domain=.yumewagener.com; Secure; Max-Age=...
```

### R3. Añadir `credentials: 'include'` en fetch cross-origin de app.js

```javascript
// Línea ~258:
const resp = await fetch('https://invest.yumewagener.com/api/portfolio', {
  credentials: 'include'
});
```

### R4. Corregir documentación VPS-STATE.md

Actualizar línea 45 para reflejar el estado actual (sin Domain) o actualizarla después de aplicar R1.

### R5. Considerar `SameSite=None` si se usa `credentials: 'include'` cross-origin

Si se implementan R1+R3, y el frontend en desk hace fetch con credentials a invest, la cookie necesita `SameSite=None; Secure` para que el navegador la envíe en peticiones cross-site. `SameSite=Lax` no envía cookies en peticiones cross-origin iniciadas por JavaScript (fetch/XHR). Sin embargo, con ForwardAuth de Traefik esto no aplica porque la validación la hace Traefik internamente.

---

## 6. Diagrama de decisión para el fix

```
¿El problema "unauthorized" ocurre al navegar directamente a invest/pumicon/terminal/n8n?
  │
  ├─ SÍ → La cookie desk_session no se envía al subdominio
  │        → FIX: Añadir Domain=.yumewagener.com a Set-Cookie (R1)
  │
  └─ NO (solo falla en llamadas API cross-origin desde JS)
           → FIX: Añadir credentials:'include' + CORS headers (R3)
```

**Hipótesis principal:** El escenario más probable para el "unauthorized" reportado es que los usuarios navegan directamente a subdominios protegidos (invest, pumicon, terminal, n8n), el navegador no envía la cookie desk_session porque no tiene Domain, Traefik ForwardAuth recibe 401 del /auth/check, y el usuario ve "unauthorized".
