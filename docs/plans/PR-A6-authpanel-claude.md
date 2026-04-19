# PR-A6 — AuthPanel React "suscripción-first" para Claude

**Hito:** A
**Esfuerzo:** M
**Depende de:** PR-A5 (readiness endpoint)
**Bloquea a:** PR-A7 (OAuth OpenAI usa el mismo panel)

## Qué

Añadir un componente nuevo `AuthPanel.tsx` en la vista Sistema que
presenta la autenticación de Claude con **setup-token primero** y
la API key relegada a fallback secundario. Pegar el token llama al
endpoint existente `POST /api/settings/llm/setup-token`; el panel
muestra un badge "Autenticado vía suscripción" cuando el token está
guardado, leyendo el estado de `/api/readiness` (entry del backend
`claude_code`).

## Por qué

MVP happy path §3 exige suscripción-first. Hoy el usuario que solo
tiene plan Claude Pro tiene que expandir el ServiceCard de Anthropic
dentro de la pestaña Servicios, cambiar un selector de auth_method
a "setup_token" y pegar el valor en un campo sensitive. Sin guía
visual. Este PR surfacea el camino recomendado en la primera
pantalla de Sistema.

## Scope — archivos que toca

- `niwa-app/frontend/src/features/system/components/AuthPanel.tsx`
  (nuevo) — sección "Claude (suscripción)" con textarea para
  setup-token, botón "Aplicar token", badge de estado, y un
  disclosure colapsado "¿Solo tienes API key?" que dirige al
  ServiceCard existente (no duplica input).
- `niwa-app/frontend/src/features/system/components/SystemView.tsx`
  — montar `<AuthPanel />` entre `<ReadinessWidget />` y `<Tabs>`.
- `niwa-app/frontend/src/shared/api/queries.ts` — añadir hook
  `useApplyClaudeSetupToken()` que hace `POST
  /api/settings/llm/setup-token` y devuelve `{ok, message?, error?}`.
  Invalida la query de readiness al completarse.
- `niwa-app/frontend/src/features/system/components/AuthPanel.test.tsx`
  (nuevo) — render básico, submit del token, assert de POST y de
  invalidación.

## Fuera de scope (explícito)

- No toca `OAuthSection.tsx` ni añade OpenAI (eso es PR-A7).
- No cambia el backend: `apply_setup_token` y la readiness ya
  existen; no se mueven fields ni claves de settings.
- No elimina ni oculta el ServiceCard de Anthropic. El usuario
  avanzado sigue pudiendo configurarlo ahí.
- No porta más cosas del legacy `frontend/static/app.js` aparte del
  flujo de `applySetupToken()` / aplicar setup-token.
- No toca i18n global — textos directos en castellano como el resto
  de SystemView actual.
- No añade validación extra del token más allá de la que ya hace el
  backend (prefijo `sk-ant-`).

## Tests

- **Nuevos:** `AuthPanel.test.tsx` con 3 casos:
  1. Render inicial: si `/api/readiness` devuelve claude backend con
     `has_credential=false`, se muestra badge "No autenticado" y el
     input de token visible.
  2. Submit OK: pegar token `sk-ant-oat01-abc`, click "Aplicar",
     mock de fetch responde `{ok:true, message:...}`; assert que el
     hook llamó a `POST /api/settings/llm/setup-token` con `{token:
     "sk-ant-oat01-abc"}` y que la query de readiness se invalidó.
  3. Submit error: mock responde `{ok:false, error:"Invalid
     token..."}`; se muestra el mensaje de error en rojo y el botón
     vuelve a estar activo.
- **Existentes que deben seguir verdes:** toda la suite frontend
  (vitest en `niwa-app/frontend`) y la baseline pytest actual
  (`1038 pass / 60 failed / 100 errors / 87 subtests pass` post-A5
   — valor que se confirma antes de empezar a tocar código).
- **Baseline esperada tras el PR:** frontend vitest +3 tests nuevos;
  pytest sin cambios (el PR no toca Python).

## Criterio de hecho

- [ ] `SystemView` renderiza un panel "Claude (suscripción)" visible
  inmediatamente debajo del widget de readiness.
- [ ] Con `svc.llm.anthropic.setup_token` vacío, el panel muestra
  input + botón "Aplicar token" + badge "No autenticado".
- [ ] Pegar un token `sk-ant-oat01-...` válido y pulsar "Aplicar"
  dispara `POST /api/settings/llm/setup-token`, muestra notificación
  de éxito, y tras el refetch el badge pasa a "Autenticado vía
  suscripción".
- [ ] Un token inválido devuelve el mensaje de error del backend
  visible en el panel (no solo toast).
- [ ] El disclosure "¿Solo tienes API key?" se colapsa por defecto
  y, al abrirse, muestra un `Text` con link a la pestaña Servicios
  → Anthropic (sin input).
- [ ] `pytest -q` sin regresiones vs baseline.
- [ ] `cd niwa-app/frontend && npm test -- --run` pasa incluyendo
  los 3 casos nuevos.
- [ ] Review Codex (esfuerzo M → obligatorio) resuelto.

## Riesgos conocidos

- **Duplicación de fuente de verdad con ServiceCard.** ServiceCard
  de `llm_anthropic` y el nuevo AuthPanel leen y escriben la misma
  clave `svc.llm.anthropic.setup_token`. Mitigación: ambos
  invalidan las mismas queries (readiness + services) al escribir;
  el ServiceCard muestra el valor enmascarado que devuelve el
  backend. No se cachea nada en AuthPanel.
- **`/api/readiness` aún no tiene test para el campo `auth_mode`
  del backend `claude_code`.** Si PR-A5 no lo expone bajo ese
  nombre, el panel podría mostrar estado incorrecto. Mitigación:
  antes de implementar, verificar en caliente el JSON real que
  devuelve `/api/readiness` y ajustar el mapping. Si hay
  discrepancia → parar y avisar.
- **React Query cache stale.** Si la mutation no invalida
  `["readiness"]`, el badge queda desfasado. Mitigación: test (2)
  cubre exactamente esto.

## Notas para Claude Code

- Si al implementar descubres que el scope es mayor del declarado,
  PARA, reescribe este brief, pide re-aprobación.
- Commits pequeños, mensaje imperativo en inglés.
- Antes de pedir review: correr `pytest -q` (baseline no regresa)
  y `npm test -- --run` dentro de `niwa-app/frontend`; pegar el
  diff de pass/fail en el PR description.
- Invocar `codex-reviewer` sobre el diff antes de abrir el PR.
