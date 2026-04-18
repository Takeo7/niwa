# PR-A4 — Reorder credential precedence: subscription > CLI session > API key

**Hito:** A
**Esfuerzo:** S
**Depende de:** ninguna
**Bloquea a:** PR-A5 (readiness widget muestra `auth_mode` derivado)

## Qué

Cambia la precedencia que `detect_claude_credentials()` y
`detect_codex_credentials()` (ambas en `setup.py`) aplican al resolver
qué credencial "gana". Hoy la env `ANTHROPIC_API_KEY` puede tapar un
login de Claude CLI (`~/.claude.json`) — y la env `OPENAI_ACCESS_TOKEN`
tapa el OAuth de ChatGPT Plus/Pro (`~/.codex/auth.json`). Tras el
cambio, la suscripción es siempre la fuente primaria; API key queda
como último fallback.

## Por qué

Happy path §1.3 declara "Auth prioriza suscripciones": Claude Pro/Max
(setup-token) y ChatGPT Plus/Pro (OAuth) son el camino por defecto.
Esta inversión de precedencia es precondición de `/api/readiness`
(PR-A5) para poder declarar `auth_mode` honestamente por backend.

## Scope — archivos que toca

- `setup.py` (`detect_claude_credentials`, `detect_codex_credentials`):
  reordena bloques para que la suscripción gane antes que la API key.
- `tests/test_pr11_quick_install.py` (`TestCredentialDetection`):
  añade los 3 casos de conflicto (subscription+api_key presentes).
  Los tests existentes sin conflicto no cambian.
- `bin/task-executor.py:925-934`: solo lo **revisamos** — la inyección
  de env al subprocess no cambia orden; seguimos poniendo API keys
  con `if key_name not in run_env` y tokens sin condición. Si
  detectamos que ambas conviven en env, el CLI de Claude ya prefiere
  `CLAUDE_CODE_OAUTH_TOKEN` sobre `ANTHROPIC_API_KEY` [Inferido — no
  reverificado en esta sesión].

## Interpretación de "suscripción > sesión CLI > API key"

Mapeo aplicado (aprobado en chat):

**Claude:**
1. Suscripción: `CLAUDE_CODE_OAUTH_TOKEN` (setup-token pegado desde la
   web de Anthropic).
2. Sesión CLI: `~/.claude.json` (login interactivo persistido por el
   CLI).
3. API key: `ANTHROPIC_API_KEY`.

**Codex:**
1. Suscripción: `~/.codex/auth.json` con `auth_mode=chatgpt_oauth`
   (ChatGPT Plus/Pro vía OAuth PKCE, persistido por el CLI).
2. Sesión CLI: `OPENAI_ACCESS_TOKEN` env (token OAuth efímero,
   asumimos origen interactivo).
3. API key: `OPENAI_API_KEY`.

## Fuera de scope (explícito)

- No toca la lógica de consumo de credenciales en
  `bin/task-executor.py` ni en los adapters
  (`backend_adapters/claude_code.py`, `codex.py`).
- No añade nuevos campos al retorno de los detectores (`source`,
  `detail`, `authenticated`, `cli` se mantienen).
- No añade refresco de OAuth ni validación remota — eso es PR-A7.
- No expone la precedencia al usuario en la UI — eso es PR-A5/A6.

## Tests

**Nuevos (3 casos de conflicto pedidos por el roadmap):**

- `test_claude_config_file_wins_over_api_key`: `~/.claude.json` +
  `ANTHROPIC_API_KEY` → `source == "~/.claude.json"`.
- `test_claude_setup_token_wins_over_config_and_api_key`:
  `CLAUDE_CODE_OAUTH_TOKEN` + `~/.claude.json` + `ANTHROPIC_API_KEY`
  → `source == "env:CLAUDE_CODE_OAUTH_TOKEN"`.
- `test_codex_auth_json_wins_over_api_key`: `~/.codex/auth.json` +
  `OPENAI_API_KEY` → source apunta a `auth.json`.
- (Extra) `test_codex_auth_json_wins_over_access_token`:
  `~/.codex/auth.json` + `OPENAI_ACCESS_TOKEN` → source apunta a
  `auth.json`, para bloquear el caso inverso.

**Existentes que deben seguir verdes:**

- `tests/test_pr11_quick_install.py::TestCredentialDetection::*` —
  todos los casos sin conflicto (solo una fuente presente) no cambian
  su resultado. `test_claude_env_token_preferred_over_config_file`
  sigue cubriendo token > config.
- Baseline general: `1033 pass / 60 failed / 104 errors / 87 subtests
  pass` (228s).

**Baseline esperada tras el PR:** `≥1037 pass` (4 tests nuevos) /
`≤60 failed` / `≤104 errors`.

## Criterio de hecho

- [ ] `detect_claude_credentials()` con ambos `~/.claude.json` y
  `ANTHROPIC_API_KEY` en env devuelve `source == "~/.claude.json"`.
- [ ] `detect_codex_credentials()` con `~/.codex/auth.json` y
  `OPENAI_API_KEY` devuelve source apuntando al `auth.json`.
- [ ] Los 4 tests nuevos pasan.
- [ ] `pytest -q tests/test_pr11_quick_install.py` verde.
- [ ] `pytest -q` sin regresiones respecto al baseline.
- [ ] Review Codex resuelto o "LGTM" (esfuerzo S; invocación
  opcional, la haré igual por tocar setup.py).
- [ ] Ningún cambio de comportamiento en `bin/task-executor.py`.

## Riesgos conocidos

- **Falsos positivos silenciosos con `~/.claude.json` vacío o
  corrupto**: hoy basta con que el archivo exista para marcar
  `authenticated=True`. Tras el cambio eso le gana a una API key
  real. No lo corrijo aquí (es otra cosa) pero lo dejo anotado por si
  quieres un FIX separado.
- **Tests en CI que dependan de env con API key presente**:
  verificaré con `pytest -q` completo antes del PR.

## Notas para Claude Code

- Commits pequeños, mensajes imperativos en inglés:
  1. `test: failing cases for credential precedence`
  2. `fix: prefer subscription over api key in credential detectors`
- Antes de pedir review: `pytest -q` completo y pegar diff
  pass/fail/error respecto al baseline en el PR body.
- Codex reviewer invocado igualmente (superficie setup.py sensible).
