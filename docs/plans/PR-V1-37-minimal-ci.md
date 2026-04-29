# PR-V1-37 — CI mínimo via GitHub Actions

**Esfuerzo:** S+ (banda calibrada: 130-200 LOC; estimación
pre-impl 80-130 LOC YAML+config)
**Depende de:** PR-V1-36b (mergeado, #151) — AGENTS.md actualizado.

## Qué

Añadir un único workflow GitHub Actions en `.github/workflows/ci.yml`
que en cada `push` a `main` y cada `pull_request` contra `main`
ejecute los dos gates del proyecto:

- `cd backend && pytest -q`
- `cd frontend && npm test`

Si CI falla, mergeo bloqueado (configuración del repo, no del
workflow — el workflow solo reporta status). Si pasa, merge
permitido.

## Por qué

Causa raíz documentada en `FOUND-20260427-process-gap.md`:
durante el ciclo v1.1, los reports de "tests verdes" venían
exclusivamente del sandbox del implementer. PR-V1-FIX-01 destapó
dos rojos que el flow del ciclo no cazó (uno reproducible en
cualquier máquina con git localizado, otro en cualquier
instalación con `~/.niwa/config.toml`). Sin un segundo lector
automático, evidencias contaminadas como las que pasaron en
PR-V1-36 (output sobre working tree con WIP) pueden llegar a
main sin disparar nada.

CI mínimo cierra el agujero. No reemplaza el smoke real ni la
revisión humana — es el guardrail estructural que dice "tests
pasan en máquina limpia con state controlado".

## Scope — archivos que toca

- **`.github/workflows/ci.yml`** (nuevo). Único workflow,
  un único job multi-step:
  1. checkout.
  2. setup-python (Python 3.12 — la versión real en uso a fecha
     de este PR; HANDBOOK aún menciona 3.11+, no se actualiza
     en este PR).
  3. setup-node (Node 20 LTS).
  4. `pip install -e ".[dev]"` en `backend/`.
  5. `pytest -q` en `backend/`.
  6. `npm install` en `frontend/`.
  7. `npm test` en `frontend/`.

  Sin matrix amplia (una versión de Python, una de Node).
  Sin coverage. Sin lint. Sin badges. Sin caching agresivo —
  el caching default de `actions/setup-python` y
  `actions/setup-node` (con `cache: 'pip'` y `cache: 'npm'`)
  basta.

- **`docs/HANDBOOK.md`** (modificado). Añadir nota corta en
  sección "Arranque en dev" o equivalente: "CI ejecuta los
  mismos comandos en cada PR; ver `.github/workflows/ci.yml`."
  ~3-5 LOC, NO reordenar contenido existente, NO modificar
  otras secciones.

## Fuera de scope (explícito)

- **NO** branch protection en `main` (configuración del repo,
  no del workflow; lo gestiona el humano via Settings → Branches
  cuando vea CI estable durante varios PRs).
- **NO** matrix de versiones Python/Node. Una versión de cada
  basta para MVP. Multi-version cuando alguien lo pida.
- **NO** coverage report ni publicación a Codecov.
- **NO** lint job (ruff/eslint). Cuando se añada, PR aparte.
- **NO** Docker build job, **NO** integration tests cross-stack,
  **NO** smoke E2E con Claude CLI real.
- **NO** auto-deploy ni release workflow.
- **NO** modificación de `pyproject.toml` ni de
  `frontend/package.json`. Las deps `[dev]` y de Vitest ya están
  declaradas (PR-V1-FIX-01 las documentó).

## Dependencias nuevas

- Python: ninguna.
- npm: ninguna.
- GitHub Actions: `actions/checkout@v4`, `actions/setup-python@v5`,
  `actions/setup-node@v4`. Versiones mayores explícitas, no
  `@latest`. Estas son convenciones de GitHub, no requieren
  pre-aprobación de proyecto.

## Tests

- **Nuevos:** ninguno (workflow YAML, no es código testable
  unitariamente).
- **Existentes que deben seguir verdes en CI:** baseline backend
  (196 passed, 1 skipped) y frontend (18 passed).
- **Validación del workflow:** cuando se abra el PR, el propio CI
  se ejecuta sobre la rama. Si falla, hay bug en el workflow
  o en el state del repo. Si pasa, validado en sí mismo.

## Criterio de hecho

- [ ] `.github/workflows/ci.yml` existe en la rama.
- [ ] El workflow tiene triggers `push: branches: [main]` y
      `pull_request: branches: [main]`.
- [ ] Job único con steps en el orden declarado arriba.
- [ ] Versiones de actions explícitas (no `@latest`, no `@main`).
- [ ] Setup-python con `python-version: '3.12'` y `cache: 'pip'`.
- [ ] Setup-node con `node-version: '20'` y `cache: 'npm'` (con
      `cache-dependency-path: 'frontend/package-lock.json'`).
- [ ] `working-directory` correctos en steps de backend
      (`backend`) y frontend (`frontend`).
- [ ] HANDBOOK tiene nota corta cross-link al workflow.
- [ ] El propio PR dispara CI; el run pasa verde antes de pedir
      merge.
- [ ] PR body incluye URL del run de CI exitoso (Actions tab).

## Riesgos conocidos

- **Versión de Python equivocada en CI vs local**: si el local
  desarrolla en 3.11 pero CI corre 3.12, deps con
  `requires-python` distinto pueden fallar. Mitigación: el
  pyproject.toml actual de backend declara `requires-python =
  ">=3.11"` (verificable). 3.12 es compatible. Si CI falla por
  esto, **STOP y consulta** — no cambies el pyproject ni el
  workflow sin OK del orquestador.
- **`npm install` vs `npm ci`**: `npm ci` requiere
  `package-lock.json` exacto y es más rápido en CI. Si está
  presente en el repo, usar `npm ci`. Si no, `npm install`. El
  implementer verifica `frontend/package-lock.json` exists antes
  de elegir.
- **Caching pip clave**: `cache: 'pip'` necesita
  `cache-dependency-path` apuntando a `backend/pyproject.toml`
  o a un `requirements.txt`. Si el formato deja warnings en CI,
  iterar.

## Notas para el implementer (Codex Desktop GPT-5.5)

- **AGENTS.md**: hay actualización reciente (PR-V1-36b). Re-léelo
  antes de empezar, especialmente:
  - Bootstrap paso 5: pre-flight working tree limpio + reporta
    SHA del commit medido.
  - LOC counting: `docs/plans/` excluido del cap.
- **FOUND aplicables a este PR:**
  - `docs/plans/FOUND-20260427-process-gap.md` (este PR ataca
    la causa raíz primaria).
  - `docs/plans/FOUND-20260426-loc-cap-pattern.md`,
    `docs/plans/FOUND-20260426-brief-loc-estimation.md`,
    `docs/plans/FOUND-20260426-spec-deviation.md` (contexto
    histórico).
- **Áreas críticas tocadas:** ninguna (`.github/workflows/`
  no está en la lista). Codex review NO obligatorio. El
  orquestador hace review del YAML.
- **Anclaje empírico del brief (lo que el orquestador leyó/
  ejecutó antes de escribir):**
  - `docs/plans/FOUND-20260427-process-gap.md`.
  - `docs/HANDBOOK.md` sección "Arranque en dev" (formato del
    setup actual).
  - Verificación via `mcp__github__get_file_contents` que
    `.github/workflows/` no existe en main (b5703cc verified
    en sesión previa, sigue en main `8665800`).
- **Antes de pushear:**
  - `git status` limpio (per AGENTS.md paso 5).
  - El commit SHA debe ir en el PR body junto a outputs de
    pytest+npm test medidos local.
  - Una vez pusheado, esperar a que CI corra sobre el propio
    PR. Si verde, copiar URL del run al body. Si rojo, **STOP
    y consulta** — no auto-fix sin instrucción.
- **LOC:** YAML cuenta. Cap S+ 130-200 con estimación 80-130.
  HANDBOOK addition ~5 LOC. Total proyectado ~85-135 LOC
  deliverable. Brief metadata (este archivo) ~120 LOC, NO
  cuenta para cap (PR-V1-36b lo formalizó).
