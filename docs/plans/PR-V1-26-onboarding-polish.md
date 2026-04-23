# PR-V1-26 — Onboarding polish para install fresca

**Tipo:** FIX (fricciones de install descubiertas en smoke post-release)
**Semana:** 6 (último PR real del MVP)
**Esfuerzo:** S
**Depende de:** PR-V1-25 mergeado + rename de ramas hecho

## Qué

Cerrar los cinco bloqueadores duros que Claude Code identificó
en el smoke de install fresca del 2026-04-22 (ver reporte
completo del humano con 12 fricciones). Objetivo: que una persona
nueva que clona el repo hoy pueda llegar a "primera task
ejecutándose" sin pedir ayuda.

## Por qué

Smoke de install fresca en `~/Documents/niwa-fresh` detectó que
la pareja del autor (usuario nuevo) no podría completar el
onboarding sin fricción. Al menos uno de estos cinco bloqueadores
dispara en cada install:

1. `python3 vs python3.11` en macOS con brew — bootstrap pide
   `python3` pero brew instala `python3.11`.
2. `niwa-executor` no está en el PATH tras bootstrap — queda en
   el venv que el usuario no ha activado.
3. README no explica cómo instalar y autenticar el Claude CLI.
4. README no menciona `gh` como prereq.
5. README no documenta cómo crear el primer proyecto en la UI.

Sin estos cinco fix, el criterio de éxito del SPEC §10 ("autor y
pareja usan Niwa") no se cumple.

## Scope — archivos que toca

```
bootstrap.sh              # fix python3.11 detection + final message
README.md                 # rewrite onboarding sections
backend/tests/test_bootstrap.py   # regression: python3.11 preferred
```

**Hard-cap: 200 LOC** (mayoría doc).

## Fuera de scope — follow-ups para v1.1

Fricciones 3, 7, 8, 9, 10, 11, 12 del reporte. Se anotan como
FOUND en `docs/plans/FOUND-20260422-onboarding.md` (un commit
separado en este PR) para no perderlos, pero NO se arreglan aquí:

- 7 (`niwa-executor stop` no para `make dev`): rediseño de
  control, no-trivial.
- 8 (no per-clone): by-design decision, deferrable.
- 9 (plist huérfano al mover): `niwa-executor doctor` futuro.
- 10 (`make dev` foreground): añadir nota breve al README basta
  como parche; el fix "real" es un `make dev-daemon` con nohup,
  v1.1.
- 11 (footer del bootstrap con path absoluto): se arregla en este
  mismo PR junto a 3, son ambos el mismo mensaje → lo incluyo en
  scope (trivial, ~5 LOC).
- 12 (DB compartida entre clones vía `~/.niwa/`): doc de una
  línea al README basta por ahora. Lo incluyo en scope (trivial).

Los genuinamente diferidos son 7, 8, 9, 10 — se anotan en FOUND.

## Contrato tras el fix

### 1. `bootstrap.sh` — detección de Python

Reemplazar el bloque actual de preconditions:

```bash
_require python3
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || _die "python 3.11+ required, found $(python3 --version 2>&1)"
```

Por:

```bash
# Prefer python3.11 explicitly — brew on Apple Silicon installs the
# 3.11 keg but does NOT expose it as "python3", only "python3.11".
# Falling back to "python3" keeps Linux default installs working.
if command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    _die "python 3.11+ required: install python@3.11 (brew) or python3.11 (apt)"
fi
"${PYTHON_BIN}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || _die "python 3.11+ required, found $(${PYTHON_BIN} --version 2>&1)"
```

Y sustituir `python3 -m venv` por `"${PYTHON_BIN}" -m venv` en el
paso 3.

### 2. `bootstrap.sh` — mensaje final accionable

Reemplazar el footer:

```
Next (delivered in PR-V1-15):
  macOS:  launchctl load /Users/.../Library/LaunchAgents/com.niwa.executor.plist
  Linux:  systemctl --user enable --now niwa-executor
```

Por:

```
Niwa v1 bootstrap complete.

  config:  ~/.niwa/config.toml
  db:      ~/.niwa/data/niwa-v1.sqlite3
  venv:    ~/.niwa/venv

Next steps:

  source ~/.niwa/venv/bin/activate
  niwa-executor start          # daemon arranca al login
  make dev                     # backend :8000 + frontend :5173

Open http://127.0.0.1:5173 once dev is running.
Read README.md → "First project" for how to create your first task.
```

### 3. `README.md` — prereqs completos

Sección "Install" reescrita con prereqs enumerados con comandos,
no lista genérica:

````markdown
## Install

Tested on macOS and Linux. Requires:

- Python 3.11+ — `brew install python@3.11` (macOS) or
  `sudo apt install python3.11 python3.11-venv` (Ubuntu).
- Node.js 22+ — `brew install node@22` (macOS) or
  https://nodejs.org (Linux).
- git.
- Claude Code CLI authenticated:
  `npm install -g @anthropic-ai/claude-code && claude`
  then `/login` inside the TUI.
- GitHub CLI (optional, needed to auto-open PRs):
  `brew install gh && gh auth login`.

Then:

```
git clone https://github.com/Takeo7/niwa.git
cd niwa
./bootstrap.sh
source ~/.niwa/venv/bin/activate
niwa-executor start
make dev
```

Backend on :8000, frontend on :5173. Open
http://127.0.0.1:5173 once both are up.

> **Note on dev mode:** `make dev` runs backend + frontend in
> the foreground of the terminal where you invoked it. Closing
> that terminal stops them. For persistent dev use tmux, nohup
> or `caffeinate -s`. A `make dev-daemon` target is planned for
> v1.1.

> **Single instance:** the bootstrap installs into `~/.niwa/`
> and registers a single launchd/systemd service. Running
> Niwa from multiple clones simultaneously is not supported —
> the second clone overwrites the service file of the first.
````

### 4. `README.md` — sección "First project"

Nueva sección tras "Install":

```markdown
## First project

Niwa works on existing git repos. Point it at one.

1. Pick a repo you want to experiment with. It **must** be a
   git repo with a clean working tree (no uncommitted changes).
   Niwa creates per-task branches via `git checkout -b
   niwa/task-<id>-<slug>` from the default branch (`main` /
   `master`); it never touches your default directly.

2. Open http://127.0.0.1:5173 and click "New project". Fill:
   - **slug** — short identifier, lowercase, e.g. `playground`.
   - **name** — human-readable label.
   - **kind** — `library`, `web-deployable`, or `script`.
     `library` runs the project's tests on completion;
     `web-deployable` additionally exposes it at
     `/api/deploy/<slug>/`; `script` skips the test step.
   - **local_path** — absolute path to the repo on your disk,
     e.g. `/Users/you/repos/myproject`.
   - **git_remote** — optional. If set and `gh` is installed,
     Niwa opens a PR automatically when each task finishes.
   - **autonomy_mode** — `safe` (default, Niwa opens PR, you
     merge) or `dangerous` (Niwa auto-merges after verify).

3. Click into the project and hit "New task". Describe the work
   in natural language. Task flows through: triage → execute →
   verify → finalize (commit + push + PR).

4. Watch the run stream in the task detail. A task that ends
   with Claude asking you something parks in `waiting_input`
   — respond in the UI and the executor resumes the session.
```

### 5. Notas defensivas cortas al README

Añadir al final, antes de "Architecture":

```markdown
## Known limitations (v1.0)

- DB lives in `~/.niwa/data/niwa-v1.sqlite3` and is shared
  across all clones on the same user account. For isolated
  testing use a separate user.
- `bootstrap.sh` on macOS with brew requires `python3.11`
  available; the script picks it automatically.
- `niwa-executor stop` stops the launchd/systemd service but
  does not kill `make dev` — use Ctrl-C in the terminal where
  you launched it.

See v1.1 roadmap in `docs/FOUND-20260422-onboarding.md`.
```

### 6. `docs/plans/FOUND-20260422-onboarding.md`

Un fichero nuevo con las 4 fricciones diferidas (7, 8, 9, 10)
como follow-up v1.1. Copia el reporte del smoke con una línea
por friction.

### 7. Regression test

`backend/tests/test_bootstrap.py` — nuevo fichero con un caso:

```python
def test_bootstrap_prefers_python311(tmp_path, monkeypatch):
    """Ensure bootstrap picks python3.11 before python3 when both exist."""
    # Create fake binaries in tmp_path with predictable version output.
    # Source the bootstrap preconditions block with PATH overridden.
    # Assert that PYTHON_BIN resolves to python3.11.
```

(Implementación exacta la decide el sub-agente — basta con que el
test falle pre-fix y pase post-fix.)

## Criterio de hecho

- [ ] Install fresca en VM/directorio limpio: `./bootstrap.sh`
      SIN shim manual (brew con python@3.11 disponible) completa
      sin errores.
- [ ] Mensaje final del bootstrap menciona `source venv + niwa-executor
      start + make dev`. No menciona PR interna.
- [ ] README tiene prereqs enumerados con comandos literales,
      sección "First project", "Known limitations".
- [ ] `pytest -q` → baseline + test bootstrap passing.
- [ ] Claude Code reejecuta el smoke 2 (fresh install) y confirma
      que los 5 bloqueadores están cerrados. Las 4 fricciones
      diferidas siguen presentes pero documentadas.
- [ ] Codex-reviewer ejecutado.

## Riesgos conocidos

- **Detección de python puede sorprender en sistemas muy
  minimalistas** (Alpine, containers sin python3.11): el fallback
  a `python3` genérico lo cubre. Si ni existe `python3` falla con
  mensaje claro.

## Notas para el implementador

- El README es texto — no metas features ni cambios de
  funcionalidad. Solo docs y el fix de `bootstrap.sh`.
- El commit de `FOUND-...md` va por separado (commit doc, no
  código).
- Commits sugeridos:
  1. `fix(bootstrap): prefer python3.11 over python3 when available`
  2. `fix(bootstrap): actionable final message instead of internal PR refs`
  3. `docs(readme): complete prereqs + first project walkthrough`
  4. `docs(readme): known limitations section`
  5. `docs(plans): FOUND-20260422 list of v1.1 onboarding followups`
  6. `test(bootstrap): regression for python3.11 preference`
