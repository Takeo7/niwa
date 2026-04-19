# FIX-20260419 — Bug 33: detección de credenciales Claude caducadas / inválidas

**Tipo:** FIX (fuera del MVP-ROADMAP, post-MVP)
**Esfuerzo:** M
**Depende de:** ninguna (construye sobre PR-A5, PR-A6, PR-A7)
**Bloquea a:** ninguno — pero desbloquea las pruebas manuales del MVP sin trampear

## Qué

Hoy, si el usuario tiene el binario `claude` instalado pero sus credenciales
(setup-token, OAuth o `~/.claude/.credentials.json`) están caducadas o
mal pegadas, `claude -p --output-format stream-json` sale `exit 0` con
stream **vacío**. El adapter interpreta eso como "ejecución correcta sin
output" y marca la tarea como `hecha`. El usuario ve "completada" y no
hay ningún artefacto ni pista del problema.

Este PR añade **dos capas de detección** que convierten un fallo
silencioso en un fallo visible:

1. **Pre-flight en `/api/readiness`** (capa preventiva).
2. **Defensiva en `ClaudeCodeAdapter._execute`** (capa runtime).

También corrige de paso Bug 17 (indicador `llm_anthropic` mentía cuando
solo había setup-token) porque readiness pasa a ser fuente única de
verdad para el estado del backend.

## Por qué

Testear el MVP manualmente requiere confianza en que "exit 0" = trabajo
hecho. Hoy no lo es. Bug 33 está abierto desde la observación post-PRs
37-41 y es el punto #1 de riesgo real al probar en máquina limpia
(documentado en la auditoría 2026-04-18, respuesta del audit §3.a).

## Contexto técnico

**Ficheros relevantes:**
- `niwa-app/backend/backend_adapters/claude_code.py` — `_execute` ronda
  línea 826-870 es donde se decide outcome.
- `niwa-app/backend/health_service.py` + `app.py` handler de
  `/api/readiness` (añadido en PR-A5).
- `niwa-app/backend/setup.py` detector `detect_claude_credentials()`
  (líneas 3298-3343) — tiene lógica de prioridad pero NO hace smoke
  activo.
- Tabla `oauth_tokens` (provider='anthropic' tras PR-A6) y
  `~/.claude/.credentials.json` como fuentes secundarias.

**Comportamiento upstream a respetar:**
- `claude --version` responde sin red y sin credenciales → usar para
  verificar binario.
- `claude -p --output-format stream-json` con prompt vacío emite al
  menos `system_init` si auth funciona.
- Si auth caducada: exit 0, stderr vacío, stdout vacío (sin eventos).
- Si binario mal: exit != 0 o stderr con "command not found".

## Scope — archivos que toca

- `niwa-app/backend/health_service.py` — nueva función
  `probe_claude_cli(timeout=10)` que clasifica el estado.
- `niwa-app/backend/app.py` — `/api/readiness` llama a `probe_claude_cli`
  y devuelve el campo `claude_probe: {status, detail, checked_at}` en
  `backends[claude_code]`.
- `niwa-app/backend/backend_adapters/claude_code.py` — `_execute` añade
  clasificación `credential_error` con `error_code='empty_stream_exit_0'`
  cuando `exit_code==0 and len(events)==0 and not stderr`.
- `niwa-app/backend/state_machines.py` — permitir transición a
  `waiting_input` desde `en_progreso` con este nuevo error_code (ya
  permitida, solo verificar).
- `niwa-app/frontend/src/features/system/components/AuthPanel.tsx` (o
  equivalente en tu nombre final PR-A6) — mostrar `claude_probe.status`
  como badge dedicado ("vía suscripción · activa" / "credenciales
  caducadas" / etc.).
- `tests/test_claude_adapter_empty_stream.py` (nuevo) — fixture con
  fake claude binary que sale exit 0 sin eventos.
- `tests/test_readiness_probe.py` (nuevo) — smoke con fake claude.
- `docs/BUGS-FOUND.md` — marcar Bug 33 como fixed con referencia al PR.

## Fuera de scope (explícito)

- **Codex/OpenAI:** el mismo patrón defensivo aplicaría, pero este PR
  solo cubre Claude. Abrir FIX hermano si en pruebas se observa.
- **Gemini:** fuera del MVP entero.
- **No tocar** `setup.py::detect_claude_credentials()` — eso es solo
  onboarding inicial, no runtime. El nuevo probe es superior y
  debería reemplazarlo gradualmente en un refactor posterior.
- **No reescribir** `_execute` — añadir una rama de clasificación, no
  refactorizar el método.

## Tests

- **Nuevos:**
  - `tests/test_claude_adapter_empty_stream.py` — 3 casos:
    (1) fake CLI sale exit 0 stream vacío → outcome `credential_error`,
    error_code `empty_stream_exit_0`, task transiciona a `waiting_input`.
    (2) fake CLI sale exit 0 con un `system_init` y nada más → también
    clasificado como `credential_error`. (3) fake CLI funcional → sigue
    `succeeded`.
  - `tests/test_readiness_probe.py` — 4 casos con env injection del PATH
    a fakes distintos: ok, no_cli, credential_missing, credential_expired.
- **Existentes que deben seguir verdes:** `test_claude_adapter_start.py`,
  `test_claude_adapter_integration.py`, `test_service_status_llm_anthropic.py`.
- **Baseline esperada:** `1330 pass + 7 nuevos = 1337 pass / ≤15 failed
  / 0 errors`. Si algún test de `test_service_status_llm_anthropic.py`
  cambia su expectativa por corrección de Bug 17, re-documentarlo.

## Criterio de hecho

- [ ] `GET /api/readiness` con `claude` caducado devuelve
  `backends[claude_code].claude_probe.status == "credential_expired"`.
- [ ] Una tarea ejecutada con `claude` caducado termina en `waiting_input`
  con `run.error_code == "empty_stream_exit_0"` y el mensaje visible
  en la UI dice "revisa credenciales Claude".
- [ ] UI AuthPanel distingue visualmente "activa" de "caducada".
- [ ] `Bug 33` en `BUGS-FOUND.md` tiene la línea `**Estado:** fixed en
  FIX-20260419`.
- [ ] `pytest -q` muestra al menos 1330 pass (no regresión).

## Riesgos conocidos

- **Probe es lento** (spawn subprocess). Cachear resultado 30s en
  memoria (atributo de módulo con timestamp); el probe se refresca al
  llamar `/api/readiness` explícitamente (refresh UI button).
- **Falsos positivos por rate limit transitorio**: si el probe ejecuta
  durante un bloqueo, puede clasificar como `credential_error`. Mitigar
  reintentando 1 vez tras 2s antes de concluir `credential_error`, y
  ampliando la severidad semántica ("quizás_caducada" vs "caducada")
  solo si se considera útil — mantener simple en v1.
- **Ambigüedad con CLI instalado pero binario bloqueado por sandbox
  corporativa**: el probe reporta exit != 0 o timeout. Clasificar como
  `no_cli` con detail "binario presente pero no ejecutable".

## Notas para Claude Code

- Mira primero `tests/fixtures/fake_claude.py` y `fake_claude_slow.py`.
  Añadir `fake_claude_empty_stream.py` siguiendo el mismo patrón.
- Antes de tocar el adapter, reproduce el bug manualmente: mueve
  temporalmente `~/.claude/.credentials.json`, corre `claude -p < /dev/null`
  y observa exit code + stream. Documenta la observación en el PR.
- Usa Codex reviewer antes de abrir el PR (M, no S).
- Commit al abrir PR: 
  ```
  fix: detect claude credential errors as empty stream / exit 0

  - adapter classifies empty-stream exit-0 as credential_error,
    routes task to waiting_input instead of hecha
  - /api/readiness runs claude probe and surfaces status
  - AuthPanel shows subscription status live
  - closes Bug 33, also fixes Bug 17
  ```
