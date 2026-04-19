# PR-A7 — OAuth OpenAI end-to-end

**Hito:** A
**Esfuerzo:** M
**Depende de:** PR-A5 (readiness endpoint), PR-A6 (AuthPanel Claude)
**Bloquea a:** ninguno directo (happy path §3 lo necesita para cerrar hito A)

## Qué

Cerrar el loop OAuth OpenAI extremo a extremo — con las piezas que
**ya existen** en el repo — añadiendo sólo lo que falta para el
happy path:

1. **Frontend.** Surfacear la autenticación OpenAI en `AuthPanel.tsx`
   como sección "ChatGPT (suscripción)" al mismo nivel que Claude,
   reutilizando `useOAuthStatus` / `useStartOAuth` /
   `useRevokeOAuth` (`shared/api/queries.ts`).
2. **Scheduler.** Añadir refresher proactivo de tokens OpenAI en
   `SchedulerThread._tick()`: si algún `oauth_tokens` row vence en
   <10 min, invocar `oauth.refresh_access_token()` y persistir el
   nuevo par access/refresh.
3. **Tests.** Cubrir los dos casos anteriores con tests nuevos
   (pytest + vitest) y no regresar la baseline.

## Por qué

Happy path §3 exige suscripción-first para ChatGPT Plus/Pro. Hoy:

- El usuario solo ve ChatGPT OAuth si **expande** el ServiceCard de
  `llm_openai` dentro de la pestaña Servicios — tres clics de
  distancia.
- El refresh de tokens existe **solo lazy**: `_get_openai_oauth_token()`
  en `bin/task-executor.py:832-852` se ejecuta justo antes de lanzar
  el subprocess y refresca con margen 300s. Si hay una tarea larga
  corriendo durante el rollover del expires_at (24h en el caso de
  ChatGPT OAuth), seguimos expuestos a ventanas en las que el
  access_token ya está caducado en la DB y no hay refresh hasta que
  llega la siguiente tarea.

La sección de AuthPanel cierra el gap de UX. El refresher en
scheduler cierra el gap de fiabilidad.

## [Hecho] — inventario de lo que ya existe (no tocar)

Documento esto aquí para que quede claro qué NO hay que reescribir:

- `niwa-app/backend/oauth.py` — completo: PKCE (`generate_pkce`),
  `build_auth_url`, `exchange_code_for_tokens`, `refresh_access_token`,
  `parse_jwt`, `is_token_expired(expires_at, margin_seconds=300)`.
  Provider `openai` cableado (`OPENAI_OAUTH_CONFIG` con `client_id`,
  `authorize_url`, `token_url`, `scopes`).
- `niwa-app/db/migrations/006_oauth_tokens.sql` — tabla
  `oauth_tokens(provider PK, access_token, refresh_token, id_token,
  expires_at, email, account_id, metadata, created_at, updated_at)`
  ya desplegada.
- `niwa-app/backend/app.py` endpoints:
  - GET  `/api/auth/oauth/start?provider=openai` → inicia PKCE
    flow, guarda state+verifier en memoria (`_pending_oauth_flows`).
  - GET  `/api/auth/oauth/callback?code&state` (público) →
    completa el flujo, persiste en `oauth_tokens`.
  - GET  `/api/auth/oauth/status?provider=openai` → devuelve
    `{authenticated, email, expires_at, expired}`, con auto-refresh
    si expirado y hay refresh_token.
  - POST `/api/auth/oauth/revoke` → `DELETE FROM oauth_tokens`.
  - POST `/api/auth/oauth/import` → importa JSON de auth.json
    externo.
- `niwa-app/backend/health_service.py:357-398` — `_summarize_backend`
  ya reporta `has_credential=true` cuando `auth_mode=oauth` y hay
  row en `oauth_tokens` para el provider mapeado (`_SERVICE_OAUTH_PROVIDER`).
- `niwa-app/backend/backend_adapters/codex.py` — docstring declara
  que consume `OPENAI_ACCESS_TOKEN` inyectado por caller.
- `bin/task-executor.py:832-864` — `_get_openai_oauth_token()` /
  `_get_openai_refresh_token()` con margen 300s; inyecta
  `OPENAI_ACCESS_TOKEN` y escribe `auth.json` para Codex CLI.
- `niwa-app/frontend/src/features/system/components/OAuthSection.tsx` —
  UI completa (start, poll, revoke, import) usada desde
  `ServiceCard` para `llm_openai`.
- `niwa-app/frontend/src/shared/api/queries.ts:289-317` — hooks
  `useOAuthStatus / useStartOAuth / useRevokeOAuth / useImportOAuth`.

## Desviación declarada respecto al roadmap

El roadmap (§4 hito A, fila PR-A7) menciona endpoints
`/api/auth/openai/start|callback`. El código actual ya sirve la
misma funcionalidad bajo `/api/auth/oauth/start|callback?provider=openai`
(forma provider-generic) desde PR-49 o anterior. **No voy a crear
alias duplicados**: el endpoint provider-genérico cubre happy path
y el único consumer extra (AuthPanel) usará los mismos hooks que
hoy usa `OAuthSection`. Si el humano prefiere los paths literales
del roadmap, lo declaro y ajusto el brief antes de codear.

## Scope — archivos que toca

### Frontend (Mantine + React Query, ~130 LOC)

- `niwa-app/frontend/src/features/system/components/AuthPanel.tsx` —
  añadir una segunda sección "ChatGPT (suscripción)" debajo de la
  sección Claude existente, dentro del mismo `Card`. Reutiliza
  `useOAuthStatus('openai')`, `useStartOAuth()`, `useRevokeOAuth()`.
  UI: badge de estado, botón "Conectar con ChatGPT", botón
  "Desconectar" cuando autenticado, texto de email si disponible.
  Nada de import JSON ni polling manual — para el botón de inicio,
  `window.open(result.auth_url)` + invalidación de query al
  montarse de nuevo la pestaña (stale time bajo). **No toco**
  `OAuthSection.tsx` ni `ServiceCard.tsx`.
- `niwa-app/frontend/src/features/system/components/AuthPanel.test.tsx` —
  3 casos nuevos (además de los 3 de PR-A6):
  4. "muestra sección ChatGPT con badge 'No conectado' cuando
     `/api/auth/oauth/status?provider=openai` responde
     `{authenticated:false}`".
  5. "click en 'Conectar con ChatGPT' dispara GET
     `/api/auth/oauth/start?provider=openai` y abre el `auth_url`
     recibido (mock de `window.open`)".
  6. "cuando status devuelve `{authenticated:true, email:'x@y'}`
     muestra email + botón 'Desconectar'; click dispara POST
     `/api/auth/oauth/revoke` con `{provider:'openai'}`".

### Backend (Python stdlib, ~70 LOC)

- `niwa-app/backend/scheduler.py` — nueva función
  `_refresh_expiring_oauth_tokens(db_conn_fn)`:
  - `SELECT provider, refresh_token, expires_at FROM oauth_tokens
     WHERE refresh_token IS NOT NULL AND refresh_token != ''`.
  - Para cada row, si `expires_at - now() < 600` (10 min), llama
    `oauth.refresh_access_token(provider, refresh_token)`.
  - Si devuelve éxito, actualiza `oauth_tokens` con el nuevo
    access/refresh/expires_at/updated_at.
  - Si devuelve error, loggea WARNING y deja la row tal cual (el
    lazy refresh en task-executor es el safety net).
- `SchedulerThread._tick()` — al final del loop actual, llamar
  `_refresh_expiring_oauth_tokens(self.db_conn_fn)` con
  `try/except Exception` local para no abortar la vuelta si una
  refresh falla.

### Tests (pytest, ~100 LOC)

- `tests/test_oauth_scheduler_refresh.py` nuevo, con 3 casos:
  - **fresh_token_not_refreshed**: fila con `expires_at = now + 1h`
    → `_refresh_expiring_oauth_tokens` no llama al módulo
    `oauth.refresh_access_token` (mockeado), DB sin cambios.
  - **expiring_token_refreshed**: fila con `expires_at = now +
    120s` → llamada a refresh, mock devuelve nuevo access/refresh/exp,
    row actualizada en DB.
  - **refresh_error_is_logged_and_swallowed**: mock de refresh
    devuelve `{"error": "HTTP 401"}` → DB sin cambios, no raise.
- No se añaden tests E2E nuevos al flujo OAuth (el happy path de
  callback requiere mock HTTP de OpenAI; eso es PR-D1).

## Fuera de scope (explícito)

- No toca `niwa-app/backend/oauth.py` — ya funciona.
- No toca `bin/task-executor.py` — el lazy refresh se queda; el
  scheduler refresher lo complementa, no lo sustituye.
- No crea alias `/api/auth/openai/*`. Usa `/api/auth/oauth/*` con
  `?provider=openai` existente.
- No toca `OAuthSection.tsx` ni `ServiceCard.tsx` — quien quiera
  configurar `auth_method=oauth` en la pestaña Servicios puede
  seguir haciéndolo; es el mismo backend.
- No añade el import JSON ni la pestaña de auth avanzada al
  AuthPanel. El AuthPanel es "suscripción first", no "admin
  panel".
- No añade tests para los endpoints OAuth existentes
  (`/start|callback|status|revoke`). Ya funcionan en prod desde
  PR-49; si faltan, es otro PR (`tests/test_oauth_endpoints.py`
  como PR-S separado).
- No toca migraciones DB. `oauth_tokens` ya está.
- No toca `backend_adapters/codex.py`. Ya consume
  `OPENAI_ACCESS_TOKEN`.

## Tests

- **Nuevos:**
  - `tests/test_oauth_scheduler_refresh.py` — 3 casos arriba.
  - `niwa-app/frontend/src/features/system/components/AuthPanel.test.tsx` —
    3 casos nuevos sumados a los 3 de PR-A6.
- **Existentes que deben seguir verdes:** toda la baseline. En
  especial `test_readiness_endpoint.py` (OAuth afecta `auth_mode`),
  `test_routing_fallback_claude_codex.py`, y los tests de codex
  adapter.
- **Baseline esperada tras el PR:**
  - pytest: `1033 pass + 3 nuevos = 1036 pass` mínimo, fallos /
    errors iguales o inferiores.
  - vitest frontend: suite actual + 3 casos.

## Criterio de hecho

- [ ] `AuthPanel` renderiza DOS secciones: "Claude (suscripción)" y
  "ChatGPT (suscripción)" debajo, dentro del mismo panel en
  `SystemView`.
- [ ] Con `oauth_tokens` sin row openai, la sección ChatGPT
  muestra badge "No conectado" + botón "Conectar con ChatGPT".
- [ ] Click en "Conectar con ChatGPT" llama GET
  `/api/auth/oauth/start?provider=openai`, abre el `auth_url` en
  pestaña nueva, y tras refresco muestra badge "Conectado" +
  email.
- [ ] Botón "Desconectar" llama POST `/api/auth/oauth/revoke` con
  `{provider:"openai"}` y vuelve al estado inicial.
- [ ] `SchedulerThread._tick()` invoca al refresher; tokens con
  `expires_at` a menos de 10 min se refrescan y persisten en la
  misma vuelta.
- [ ] `pytest -q` sin regresiones vs baseline.
- [ ] `cd niwa-app/frontend && npm test -- --run` verde con los
  6 casos (3 previos + 3 nuevos) de `AuthPanel.test.tsx`.
- [ ] Review Codex (esfuerzo M → obligatorio) resuelto.

## Riesgos conocidos

- **Concurrencia refresh.** Si el scheduler refresca al minuto T y
  el task-executor lee la row al minuto T+ε en otra conexión
  SQLite, `_get_openai_oauth_token` puede ver una fila medio
  actualizada. Mitigación: el UPDATE es atómico dentro de una
  transacción; ambos lectores abren sus propias conexiones con el
  `db_conn_fn` actual (SQLite + WAL). Riesgo residual bajo; lo
  documento en el DECISIONS-LOG si pasa algo raro en prod.
- **Expiración del refresh_token sin usar.** Si el refresh_token
  está caducado (no pasa normalmente en 24h pero teóricamente
  podría), OpenAI devuelve 400 al refresh. Mitigación: loggear
  WARNING y seguir; la UI reflejará `authenticated=false` en la
  siguiente llamada a `/status` y el usuario re-autentica.
- **Popup bloqueado.** `window.open(auth_url)` puede caer en el
  pop-up blocker de algunos navegadores. Mitigación: documentar en
  `SystemView` con un `Text size="xs"` debajo del botón — "Si no se
  abre la ventana, tu navegador bloqueó el popup". No añado
  fallback de redirección full-page (eso es otro PR si lo
  pedimos).
- **Scope creep potencial: aliases `/api/auth/openai/*`.** Si el
  review pide esto, paro y hago PR aparte — fuera de A7.

## Notas para Claude Code

- Si al implementar descubres que el scope es mayor del declarado
  (p.ej. `useStartOAuth` no existe con la firma esperada o el
  backend devuelve algo distinto), PARA, reescribe este brief,
  pide re-aprobación.
- Commits pequeños, mensaje imperativo en inglés:
  1. `test: failing cases for OpenAI section in AuthPanel`
  2. `feat(frontend): OpenAI subscription section in AuthPanel`
  3. `test: failing cases for scheduler OAuth refresher`
  4. `feat(scheduler): refresh expiring OpenAI tokens every tick`
- Antes de pedir review: `pytest -q` (baseline no regresa) y
  `npm test -- --run` dentro de `niwa-app/frontend`. Pegar diff
  pass/fail en el PR body.
- Invocar `codex-reviewer` sobre el diff `git diff
  origin/v0.2...HEAD` antes de abrir el PR.
- Rama de trabajo en esta sesión: `claude/senior-engineer-review-Hgl0h`
  (override de la convención `claude/pr-A7-<slug>` por instrucción
  del harness).
