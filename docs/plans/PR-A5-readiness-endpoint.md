# PR-A5 — Readiness endpoint + "Qué falta" widget

**Hito:** A
**Esfuerzo:** M
**Depende de:** PR-A4 (mergeado — ya expone `source` y precedencia)
**Bloquea a:** PR-A6 (AuthPanel lee `backends[].auth_mode` desde aquí)

## Qué

Nuevo endpoint `GET /api/readiness` que devuelve, en un solo JSON, el
estado de los componentes que bloquean el happy path del MVP
(docker, db, admin, backends, hosting). Más widget "Qué falta" al
principio de `SystemView` que pinta rojo cada componente no listo y
enlaza a la pestaña correspondiente.

## Por qué

Happy path §1.2: "el usuario ve en la UI qué modelo/backend ejecuta
cada parte, qué falta para estar listo, y puede configurarlo sin
editar ficheros". Hoy no existe ninguna vista agregada: hay
`/api/health/full` (servicios externos), `/api/agents-status`
(agentes), `/api/settings/llm-status` (solo un proveedor), pero no
hay un único sitio que diga "te faltan estas N cosas para poder
ejecutar una tarea end-to-end".

## Contrato del endpoint

`GET /api/readiness` → 200 OK, sin auth extra (ya va detrás de
Basic Auth como el resto de `/api/*`).

```json
{
  "docker_ok": true,
  "db_ok": true,
  "admin_ok": false,
  "admin_detail": "using default credentials (change NIWA_APP_PASSWORD)",
  "backends": [
    {
      "slug": "claude_code",
      "display_name": "Claude Code",
      "enabled": true,
      "has_credential": true,
      "auth_mode": "setup_token",
      "model_present": true,
      "default_model": "claude-sonnet-4-6",
      "reachable": true
    },
    {
      "slug": "codex",
      "display_name": "Codex",
      "enabled": true,
      "has_credential": false,
      "auth_mode": "api_key",
      "model_present": false,
      "default_model": null,
      "reachable": false
    }
  ],
  "hosting_ok": true,
  "hosting_detail": "caddyfile + HOSTING_DOMAIN set",
  "checked_at": "2026-04-19T10:00:00Z"
}
```

### Semántica de cada campo

- `docker_ok`: `True` si el proceso corre dentro de un container
  Docker (`/.dockerenv` existe) **o** si `docker ps` responde
  (host-mode). [Inferido] — la app normalmente corre en container,
  pero el executor corre en host; ambos casos deben dar ok.
- `db_ok`: `SELECT 1` vía `db_conn()` sin excepción.
- `admin_ok`: `NIWA_APP_PASSWORD` distinto de `change-me`/vacío y
  `NIWA_APP_USERNAME` seteado. Reutiliza la misma regla que ya
  aplica `_audit_credential_defaults` (app.py:1042).
- `backends[]`: una entrada por fila activa de `backend_profiles`
  (ya seeded por `seed_backend_profiles`). Para cada una:
  - `slug`, `display_name`, `enabled`, `default_model`,
    `model_present`: leídos directos de la tabla.
  - `auth_mode`: derivado del setting del servicio correspondiente
    (`claude_code` → `svc.llm.anthropic.auth_method`,
    `codex` → `svc.llm.openai.auth_method`). Default `"api_key"`.
  - `has_credential`: según `auth_mode`:
    - `api_key` → `svc.<provider>.api_key` no vacío.
    - `setup_token` → `svc.llm.anthropic.setup_token` no vacío.
    - `oauth` → fila en `oauth_tokens` para ese provider.
  - `reachable`: **best-effort sin red**: `enabled AND
    has_credential AND model_present AND NIWA_LLM_COMMAND no
    vacío`. No hace llamadas salientes (burning tokens en cada
    poll del widget es inaceptable). Se documenta en el comment
    de la función.
- `hosting_ok`: `CADDYFILE_PATH` existe **o** `NIWA_HOSTING_DOMAIN`
  está en env. Razonable para MVP (PR-C2 endurecerá la check).

**Nota sobre `reachable`:** el nombre del roadmap puede sonar a
"pinga el API". Lo interpretamos como "tiene todo lo necesario
para ejecutar una tarea" y lo declaramos en el docstring + en el
body del PR. Si después quieres un `reachable` real vía HTTP, sale
en PR aparte (no es scope de A5).

## Scope — archivos que toca

**Backend (Python):**
- `niwa-app/backend/health_service.py`: añade `fetch_readiness()`
  (~80 LOC) + helpers privados. Reusa `_db_conn`.
- `niwa-app/backend/app.py`:
  - Ruta GET `/api/readiness` → `fetch_readiness()` (3 LOC, misma
    forma que `/api/health/full` en app.py:3779).
  - 1 import en la zona de `from health_service import ...`.

**Tests (Python):**
- `tests/test_readiness_endpoint.py` (nuevo, ~180 LOC). Levanta
  servidor igual que `test_hosting_status_endpoint.py`.

**Frontend (TypeScript):**
- `niwa-app/frontend/src/shared/api/queries.ts`: `useReadiness()`
  hook, `staleTime: 15000`, refetchInterval 30s (misma política
  que `useAgents`).
- `niwa-app/frontend/src/features/system/components/ReadinessWidget.tsx`
  (nuevo, ~120 LOC). Pinta una lista compacta con Mantine
  `Alert`/`Badge` + un item rojo por cada componente no listo.
- `niwa-app/frontend/src/features/system/components/SystemView.tsx`:
  importa `ReadinessWidget` y lo monta encima del `<Tabs>`. +2 LOC.
- `niwa-app/frontend/src/shared/api/types.ts` (si existe): type
  `Readiness`. Si no, va inline en queries.ts.

## Fuera de scope (explícito)

- No añade llamadas salientes a los APIs de Anthropic/OpenAI.
  "Reachability" real es otro PR.
- No cambia la precedencia de credenciales (ya es PR-A4).
- No añade refresco de OAuth (PR-A7).
- No modifica AuthPanel (PR-A6), ni añade la vista "suscripción
  first" que pega setup-token — eso es PR-A6.
- No toca `setup.py::detect_claude_credentials` / `detect_codex_...`.
  El endpoint vive dentro del container, no ve el `~/.claude.json`
  del host. Inferimos credenciales desde la tabla `settings` y
  `oauth_tokens`, que es lo que sí está persistido y disponible.
- No renombra ni borra `/api/settings/llm-status` — sigue siendo
  útil para un solo proveedor.
- No añade paginación / filtros al widget (es fijo).

## Tests

**Nuevos en `tests/test_readiness_endpoint.py`:**

1. `test_readiness_all_ok_returns_green`: seed `backend_profiles`
   claude+codex, inserta en `settings` setup-token + api_key,
   inserta fila en `oauth_tokens`, pone `NIWA_APP_PASSWORD` no
   default, `NIWA_HOSTING_DOMAIN` set. Espera todos los flags
   `True` y cada backend con `has_credential=True`.
2. `test_readiness_missing_admin_password_flags_admin_not_ok`:
   `NIWA_APP_PASSWORD=change-me` → `admin_ok=False` con detail
   legible.
3. `test_readiness_backend_without_credential_is_not_reachable`:
   backend `claude_code` sin setup_token ni api_key →
   `has_credential=False` y `reachable=False`.
4. `test_readiness_codex_oauth_token_counted_as_credential`: seed
   `oauth_tokens(provider='openai')`, `svc.llm.openai.auth_method
   = 'oauth'` → `has_credential=True`.
5. `test_readiness_hosting_detects_domain_env`: `NIWA_HOSTING_DOMAIN
   = example.com` → `hosting_ok=True` aun sin Caddyfile.
6. `test_readiness_hosting_false_when_nothing`: ni domain ni
   caddyfile → `hosting_ok=False`.
7. `test_readiness_db_error_returns_db_ok_false`: monkeypatch
   `db_conn` para que lance → `db_ok=False`, no 500.
8. `test_readiness_does_not_call_external_apis`: el handler no
   hace `urlopen` a dominios externos (patchear `urllib.request.
   urlopen` y afirmar que no se llamó con host != localhost).

**Existentes que deben seguir verdes:**
- `tests/test_hosting_status_endpoint.py` (patrón que copiamos).
- Toda la suite de `test_installer_*`, `test_app_*` si existe.
- Baseline post PR-B2 (último mergeado): `1033+` pass. Tras PR-A5
  deberían ser **+8 pass** aproximadamente.

**Baseline esperada tras el PR:** `≥1041 pass / ≤60 failed /
≤104 errors`.

**Frontend:** no se añaden tests nuevos en PR-A5. El widget se
prueba manualmente con `npm run dev` contra un backend que devuelva
readiness mockeado. [Supuesto] — si el humano quiere vitest para
este widget, lo saco a PR aparte; cada panel actual tiene tests
dispares (ver `DeploymentsPanel.test.tsx` vs `ServicesPanel` sin
test).

## Criterio de hecho

- [ ] `curl -u admin:pw http://localhost:8080/api/readiness` devuelve
  200 + JSON con las 5 claves top-level documentadas arriba.
- [ ] Con `NIWA_APP_PASSWORD=change-me`, `admin_ok=false` y
  `admin_detail` explica el porqué.
- [ ] Cada fila en `backends[]` tiene los 8 campos del schema; sin
  secretos filtrados (api_key enmascarado via `_mask_sensitive` ya
  existente).
- [ ] El endpoint no hace llamadas de red salientes (test #8 lo
  prueba).
- [ ] Widget en `SystemView` pinta rojo los items con `*_ok=false`
  o `backends[].has_credential=false`, verde el resto.
- [ ] `pytest -q` sin regresiones respecto a baseline 1033 pass.
- [ ] Revisión Codex resuelta o "LGTM".
- [ ] `npm run build` en `niwa-app/frontend` sin errores de types.

## Riesgos conocidos

- **`reachable` es heurístico, no una prueba real de red.** Mitigación:
  documentado en docstring + body del PR; PR-A7 puede endurecerlo
  con `ping` al `/v1/models` de cada backend tras persistir OAuth.
- **Mapping slug ↔ service settings es hardcoded.** `claude_code →
  anthropic`, `codex → openai`. Si en el futuro se añade Gemini u
  otro, hay que añadir entrada. Mitigación: función
  `_backend_service_key(slug)` centraliza el mapeo en un solo sitio
  (~5 LOC). Fallar silenciosamente a `api_key + has_credential=false`
  si el slug no está en el mapa — no se rompe nada, solo queda rojo.
- **`docker_ok=True` porque `/.dockerenv` existe no significa que
  `docker run` funciona.** Mitigación: el widget ya tiene
  `docker_ok` binary; si el usuario tiene un Docker broken, lo verá
  al crear la siguiente tarea — PR-A2 ya ataca la ausencia de
  Docker en instalación.
- **Test #8 (no-network) puede ser brittle si alguien añade calls
  a `urllib.request.urlopen` en `health_service`.** Mitigación:
  test patchea solo el `urlopen` importado en `health_service`, no
  el global.

## Notas para Claude Code

- Commits pequeños, mensajes imperativos en inglés:
  1. `test: failing cases for /api/readiness`
  2. `feat(backend): add /api/readiness with readiness widget contract`
  3. `feat(frontend): readiness widget in SystemView`
- Antes de abrir PR: `pytest -q` completo + `npm run build` en
  frontend. Pegar diff pass/fail/error vs baseline 1033 pass.
- Invocar `codex-reviewer` sobre el diff (esfuerzo M, tocamos
  app.py + nuevo handler — bien vale un revisor).
- Si al implementar aparece scope creep (ej. necesidad de un
  endpoint separado para mascarar secretos, o de refactor de
  `fetch_settings`), PARA y reescribe el brief.
