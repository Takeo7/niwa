# PR-C2 — wire domain save through to Caddyfile + reload

**Hito:** C
**Esfuerzo:** S-M
**Depende de:** ninguna (PR-A5 añadió `/api/hosting/status`, PR-48 el wizard UI)
**Bloquea a:** PR-C3 (health-check de productos asume URL real)

## Qué

Hoy `HostingDomainWizard.tsx` guarda `svc.hosting.domain` vía el
endpoint genérico `POST /api/services/hosting`. Pero
`hosting.generate_caddyfile()` y `hosting.deploy_project()` leen el
dominio del env var `NIWA_HOSTING_DOMAIN` (línea 14 de `hosting.py`),
no del ajuste en DB. Resultado: guardar el dominio desde la UI **no
tiene efecto** hasta reiniciar el proceso con el env var exportado.

PR-C2 cierra ese gap:

1. `generate_caddyfile()` + `deploy_project()` leen el dominio desde
   DB (`svc.hosting.domain`), con fallback al env var para
   retro-compat.
2. Nuevo endpoint `POST /api/hosting/domain` con body
   `{domain, force?}`. Valida DNS + wildcard + HTTP reutilizando los
   probes existentes en `hosting.get_status()`. Si falla alguno y
   `force!=true`, devuelve 400 con el detalle. Si pasa (o force),
   guarda, regenera Caddyfile y dispara `_reload_caddy()`.
3. `HostingDomainWizard.tsx` llama al nuevo endpoint y muestra los
   errores de validación inline, con botón "Guardar de todos modos"
   que reenvía con `force=true`.

## Por qué

Happy path §5 ("cierre del ciclo"): tras desplegar, la UI debe dar
una URL real. Hoy, si el admin sigue el wizard, DNS + records ok,
pero el Caddyfile generado por `deploy_project()` ignora el dominio
y los deploys salen como `localhost:8880/<slug>/`. Sin este PR el
hito C entero no cierra.

## Scope — archivos que toca

- `niwa-app/backend/hosting.py` — reemplazar referencias directas a
  `HOSTING_DOMAIN` por `_current_domain()` (DB con env fallback);
  añadir `save_domain(domain, force=False) -> dict` que consolida
  validate + persist + regenerate + reload.
- `niwa-app/backend/app.py` — nueva ruta `POST /api/hosting/domain`
  (≈15 LOC) + ruta `DELETE /api/hosting/domain` para limpiar
  (≈10 LOC). Delegan en `hosting.save_domain` / `hosting.clear_domain`.
- `niwa-app/frontend/src/shared/api/queries.ts` — hook
  `useSaveHostingDomain({domain, force})` (≈15 LOC).
- `niwa-app/frontend/src/features/system/components/HostingDomainWizard.tsx`
  — `handleSaveDomain` usa el nuevo hook, renderiza errores de
  validación, ofrece "Guardar de todos modos".
- `tests/test_hosting_domain_save.py` (nuevo).

## Fuera de scope (explícito)

- No toca `/api/hosting/status` (ya está bien).
- No ACME ni certs (asume Cloudflare proxy, está en el brief del hito).
- No cambia `_reload_caddy()` (el `pkill -USR1` ya tiene bug anotado
  en comentarios, se arregla en otro PR si molesta).
- No toca `deploy_project()` ni `undeploy_project()` más allá de
  leer el dominio del helper `_current_domain()`.
- No añade migrations nuevas.
- No cambia el endpoint genérico `POST /api/services/hosting` (sigue
  funcionando para `port` y `directory`; sólo añadimos una ruta
  específica para `domain` porque requiere validación y reload).

## Tests

**Nuevos** (`tests/test_hosting_domain_save.py`):

- `test_save_domain_rejects_when_dns_fails_without_force`: POST con
  `_resolve_a_records` mockeado a `[]` → 400 con
  `validation={dns_ok:false, wildcard_ok:false, http_ok:false}`, el
  setting en DB no cambia, `generate_caddyfile` no se llama.
- `test_save_domain_with_force_persists_and_reloads`: igual que
  arriba pero `force=true` → 200, setting actualizado, `reload`
  llamado 1 vez.
- `test_save_domain_happy_path`: DNS + wildcard + HTTP mockeados ok
  → 200, setting guardado, Caddyfile regenerado con
  `*.example.com:8880 {…}`.
- `test_save_domain_rejects_private_host`: DNS resuelve a `10.0.0.5`
  → 400 con `error="private_or_invalid_host"` incluso con
  `force=true` (SSRF defense-in-depth; mantener paridad con el probe
  existente).
- `test_save_domain_rejects_bare_ip`: `domain="8.8.8.8"` → 400 por
  mismo motivo.
- `test_save_domain_requires_admin`: sin auth / con user no-admin →
  401/403.
- `test_generate_caddyfile_uses_db_domain_over_env`: `_current_domain`
  devuelve valor DB aunque env var también esté seteado; el
  Caddyfile contiene el dominio de DB.
- `test_generate_caddyfile_falls_back_to_env`: DB vacía + env var
  `NIWA_HOSTING_DOMAIN=legacy.com` → Caddyfile usa `legacy.com`
  (retro-compat).
- `test_clear_domain_regenerates_path_based_only`: `DELETE` →
  Caddyfile no contiene bloque wildcard, sí el `:8880 {…}`
  path-based.

**Existentes que deben seguir verdes:**
`tests/test_hosting_status_endpoint.py`, `tests/test_deployments_endpoints.py`,
`tests/test_installer_hosting_path.py`, `tests/test_pr55_retry_undeploy_patch.py`,
`tests/test_task_autodeploy_on_success.py`.

**Baseline esperada tras el PR:** `≥1033 pass / 60 failed / 104 errors`
(los tests nuevos son suma pura, no tocan hot paths existentes). Los
errors de colección del baseline no deben moverse.

## Criterio de hecho

- [ ] `curl -X POST /api/hosting/domain -d '{"domain":"x.com"}'` con
      DNS sin resolver devuelve 400 con shape
      `{ok:false, validation:{dns_ok, wildcard_ok, http_ok}, error}`.
- [ ] Mismo POST con `force=true` devuelve 200 y persiste.
- [ ] Tras guardar con validación ok, `cat <CADDYFILE_PATH>` muestra
      `*.x.com:8880 { … }` con cada slug deployado.
- [ ] `deploy_project()` devuelve `url=http://<slug>.x.com:8880`
      cuando el dominio está guardado en DB (aunque
      `NIWA_HOSTING_DOMAIN` esté vacío).
- [ ] El wizard React renderiza los tres check marks (DNS /
      wildcard / HTTP) en rojo cuando el save falla y muestra el
      botón "Guardar de todos modos".
- [ ] `pytest -q` sin regresiones respecto al baseline.
- [ ] Review Codex resuelto (o "LGTM").

## Riesgos conocidos

- **Race de reload:** `_reload_caddy()` usa `pkill -USR1` que puede
  no recargar si Caddy no arrancó con `--watch`. Mitigación: el PR
  no cambia `_reload_caddy`; si el reload falla silenciosamente, el
  admin ve el dominio guardado pero la nueva subdomain no responde
  hasta el próximo deploy. Se documenta en el body del PR como
  limitación conocida y se deja fix para PR aparte.
- **Chicken-and-egg HTTP probe:** recién guardado el dominio, si
  Caddy aún no escucha, `http.ok` es falso. El `force=true` es la
  válvula de escape — el wizard ya muestra el status post-save.
- **Tests frontend:** `HostingDomainWizard.test.tsx` existe;
  actualizar (no crear nuevo) para cubrir la nueva UI de errores.

## Notas para Claude Code

- `_current_domain()` debe ser una función, no una constante, para
  que los tests puedan cambiar el setting en DB y ver el efecto sin
  reload del módulo.
- Reutilizar exactamente `_is_public_hostname`, `_resolve_a_records`,
  `_http_probe` ya existentes. No duplicar lógica.
- `save_domain` debe ser idempotente: llamar dos veces con el mismo
  dominio no debe romper nada.
- Commits pequeños, imperativos, inglés.
- Antes de review: `pytest -q` completo + invocar `codex-reviewer`
  sobre el diff (esfuerzo S-M → se hace).
