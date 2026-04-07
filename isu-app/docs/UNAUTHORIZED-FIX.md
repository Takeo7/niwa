# Fix: "Unauthorized" al cargar webs con SSO

**Fecha:** 2026-03-27
**Subtarea:** 4/4 de "Revisar proyectos/webs que cargan con unauthorized"

---

## Causa raíz

La cookie `desk_session` se establece **sin el atributo `Domain`** en `app.py` (líneas 1895 y 1738). Según RFC 6265, esto hace que la cookie **solo aplique al host exacto** (`desk.yumewagener.com`) y **no se envíe a subdominios** como `invest.yumewagener.com`, `pumicon.yumewagener.com`, etc.

**Flujo del problema:**
1. Usuario inicia sesión en `desk.yumewagener.com` → cookie `desk_session` se guarda solo para ese dominio
2. Usuario accede a `invest.yumewagener.com` → Traefik ejecuta ForwardAuth contra `/auth/check`
3. El navegador NO envía la cookie `desk_session` (dominio diferente)
4. `/auth/check` devuelve 401 → **"unauthorized"**

**Servicios afectados (5):**
- `invest.yumewagener.com` (InvestmentDesk)
- `pumicon.yumewagener.com` (Pumicon)
- `terminal.yumewagener.com` (Terminal)
- `n8n.yumewagener.com` (n8n)
- `trendflow.yumewagener.com` (TrendFlow)

---

## Cambios aplicados

### 1. `frontend/app.js` línea 258 — Cross-origin fetch sin credenciales

**Problema:** La llamada a la API de InvestmentDesk no incluía `credentials: 'include'`, por lo que el navegador no enviaba cookies en la petición cross-origin.

**Cambio:**
```diff
- const resp = await fetch('https://invest.yumewagener.com/api/portfolio');
+ const resp = await fetch('https://invest.yumewagener.com/api/portfolio', { credentials: 'include' });
```

### 2. `backend/trigger_idle_review.py` líneas 37-40 — CORS wildcard inseguro

**Problema:** `Access-Control-Allow-Origin: *` es incompatible con cookies/credenciales (RFC 6454) y es mala práctica.

**Cambio:**
```diff
- self.send_header('Access-Control-Allow-Origin', '*')
  self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
  self.send_header('Access-Control-Allow-Headers', 'Content-Type')
+ self.send_header('Access-Control-Allow-Origin', 'https://desk.yumewagener.com')
+ self.send_header('Access-Control-Allow-Credentials', 'true')
```

---

## Cambios que requieren intervención manual

### CRÍTICO: `backend/app.py` (archivo protegido)

Este es el **fix principal** que resuelve el problema de "unauthorized" en todos los servicios.

**Script automatizado disponible:**
```bash
# Ver qué cambios se harán (sin modificar nada):
bash scripts/fix-cookie-domain.sh --dry-run

# Aplicar el fix (crea backup automático):
bash scripts/fix-cookie-domain.sh
```

**Línea 1895** (login Set-Cookie) — cambiar de:
```python
Set-Cookie: desk_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={ttl_seconds}
```
a:
```python
Set-Cookie: desk_session={token}; Domain=.yumewagener.com; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={ttl_seconds}
```

**Línea 1738** (logout Set-Cookie) — cambiar de:
```python
Set-Cookie: desk_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0
```
a:
```python
Set-Cookie: desk_session=; Domain=.yumewagener.com; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0
```

**Cambios clave:**
- `Domain=.yumewagener.com` — permite que la cookie se envíe a todos los subdominios
- `Secure` — asegura que la cookie solo se transmita por HTTPS

### OPCIONAL: `infra/docker-compose.yml` (archivo protegido)

Añadir `authResponseHeaders` para pasar contexto del usuario a backends:
```yaml
- traefik.http.middlewares.desk-sso.forwardauth.authResponseHeaders=X-Desk-User
```

### OPCIONAL: `infra/VPS-STATE.md`

La documentación (línea 45) ya dice que la cookie tiene `Domain=.yumewagener.com` — será correcto una vez aplicado el fix en app.py.

---

## Verificación post-fix

Una vez aplicados los cambios en `app.py`:

1. Reiniciar el contenedor Desk: `docker compose restart desk`
2. Borrar cookies existentes de `desk.yumewagener.com` en el navegador
3. Iniciar sesión nuevamente en `desk.yumewagener.com`
4. Verificar en DevTools → Application → Cookies que `desk_session` tiene `Domain: .yumewagener.com`
5. Navegar a `invest.yumewagener.com` — debería cargar sin "unauthorized"
6. Repetir con `pumicon`, `terminal`, `n8n`, `trendflow`

---

## Resumen

| Cambio | Archivo | Estado | Impacto |
|--------|---------|--------|---------|
| `credentials: 'include'` en fetch | frontend/app.js | **Aplicado** | Portfolio KPI funciona cross-origin |
| CORS origin específico + credentials | backend/trigger_idle_review.py | **Aplicado** | Seguridad mejorada |
| `Domain=.yumewagener.com` + `Secure` en cookie | backend/app.py | **Script listo** (`scripts/fix-cookie-domain.sh`) | Fix principal — resuelve unauthorized en 5 apps |
| `authResponseHeaders` en Traefik | infra/docker-compose.yml | **Manual requerido** | Opcional — pasa contexto de usuario |
