# Fix: "Unauthorized" al cargar webs protegidas por desk-sso

## Problema

Las aplicaciones protegidas por el middleware `desk-sso` de Traefik (invest, trendflow, n8n, pumicon, terminal) devuelven "unauthorized" al cargar.

## Causa raiz

La cookie `desk_session` se establece **sin atributo `Domain`**, lo que la convierte en una "host-only cookie" que solo es visible para `desk.yumewagener.com`.

Cuando un usuario accede a `invest.yumewagener.com`:
1. Traefik intercepta la peticion y llama a `http://127.0.0.1:8080/auth/check` (ForwardAuth)
2. El navegador NO envia la cookie `desk_session` porque fue establecida sin `Domain` (solo aplica al host exacto donde se creo)
3. `/auth/check` no encuentra la cookie -> devuelve 401 `{"error":"unauthorized"}`
4. Traefik bloquea el acceso a la app

La variable de entorno `DESK_COOKIE_DOMAIN=.yumewagener.com` existe en `.env.example` pero **nunca se lee ni se usa** en el codigo.

## Evidencia

### Set-Cookie actual (app.py lineas 1738 y 1895):
```python
# Logout (linea 1738):
Set-Cookie: desk_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0

# Login (linea 1895):
Set-Cookie: desk_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={TTL}
```
Ninguno incluye `Domain=.yumewagener.com`.

### ForwardAuth configurado (infra/docker-compose.yml lineas 25-26):
```yaml
traefik.http.middlewares.desk-sso.forwardauth.address=http://127.0.0.1:8080/auth/check
traefik.http.middlewares.desk-sso.forwardauth.trustForwardHeader=true
```

### VPS-STATE.md documenta la intencion:
> Cookie: `desk_session` con `Domain=.yumewagener.com` -- shared across all subdomains

Pero el codigo no implementa esto.

## Fix requerido (INTERVENCION MANUAL en app.py)

### Cambio 1: Leer DESK_COOKIE_DOMAIN (linea ~30, junto a las demas variables)

Agregar despues de la linea 30 (`DESK_SESSION_TTL_HOURS`):
```python
DESK_COOKIE_DOMAIN = os.environ.get('DESK_COOKIE_DOMAIN', '')
```

### Cambio 2: Incluir Domain en Set-Cookie de login (linea 1895)

Cambiar:
```python
return self._redirect('/', headers={'Set-Cookie': f'{DESK_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={DESK_SESSION_TTL_HOURS * 3600}'})
```

Por:
```python
domain_part = f'; Domain={DESK_COOKIE_DOMAIN}' if DESK_COOKIE_DOMAIN else ''
return self._redirect('/', headers={'Set-Cookie': f'{DESK_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={DESK_SESSION_TTL_HOURS * 3600}{domain_part}'})
```

### Cambio 3: Incluir Domain en Set-Cookie de logout (linea 1738)

Cambiar:
```python
return self._redirect('/login', headers={'Set-Cookie': f'{DESK_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0'})
```

Por:
```python
domain_part = f'; Domain={DESK_COOKIE_DOMAIN}' if DESK_COOKIE_DOMAIN else ''
return self._redirect('/login', headers={'Set-Cookie': f'{DESK_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{domain_part}'})
```

### Cambio 4: Asegurar DESK_COOKIE_DOMAIN en el entorno de produccion

En `infra/.env` (o el .env de produccion), agregar:
```
DESK_COOKIE_DOMAIN=.yumewagener.com
```

## Notas adicionales

- El punto inicial en `.yumewagener.com` es necesario para que la cookie aplique a todos los subdominios
- Si `DESK_COOKIE_DOMAIN` no esta definido, el comportamiento es identico al actual (host-only), lo cual es correcto para desarrollo local
- Tras aplicar el fix, los usuarios necesitaran hacer login de nuevo para obtener una cookie con el `Domain` correcto
- No se requieren cambios de CORS ya que Traefik ForwardAuth opera a nivel de servidor (no del navegador)
- `SameSite=Lax` es compatible con este enfoque ya que las peticiones de navegacion top-level si envian cookies
