# PR-V1-25 — Promote v1 to root + cleanup legacy + branch switch

**Tipo:** RELEASE (cierre oficial del MVP)
**Semana:** 6 (último PR)
**Esfuerzo:** L (por volumen de borrado, no de diseño)
**Depende de:** PR-V1-22, PR-V1-23, PR-V1-24 mergeados y smoke
final 3/3 verde validado por humano

## Qué

Cierre oficial del MVP Niwa v1. Tres operaciones encadenadas:

1. **Movimiento del workspace** — promover el contenido de `v1/`
   a la raíz del repo, dejando atrás el código de v0.2.
2. **Cleanup legacy** — borrar todos los ficheros y directorios
   de v0.2 que no se portaron a v1.
3. **Switch de ramas en GitHub** — renombrar
   `v0.2 → v0.2-legacy`, `main → main-legacy`, `v1 → main`,
   y cambiar la rama default del repo a la nueva `main`.

## Por qué

El SPEC §9 declara este cierre como criterio de fin de Semana 6.
Hoy `v1` tiene una estructura híbrida: `v1/` con código nuevo +
`niwa-app/`, `bin/`, `servers/`, `setup.py` con código viejo de
v0.2 que sirvió como referencia durante el rewrite. Mantener esa
dualidad post-MVP causa confusión perpetua. Promover el contenido
de v1/ a raíz hace que `main` ofrezca un repo limpio y coherente
con el SPEC.

## Scope — operaciones que ejecuta

### Fase 1 — Movimiento (commit único)

**Mover** todos estos directorios y ficheros de `v1/` a la raíz
con `git mv` para preservar historial:

```
v1/backend/                 → backend/
v1/frontend/                → frontend/
v1/templates/               → templates/
v1/Makefile                 → Makefile
v1/bootstrap.sh             → bootstrap.sh
v1/CLAUDE.md                → CLAUDE.md   (sobrescribe el viejo)
v1/data/.gitkeep            → data/.gitkeep
v1/docs/HANDBOOK.md         → docs/HANDBOOK.md   (nuevo, no
                              portar el viejo)
v1/docs/SPEC.md             → docs/SPEC.md
v1/docs/STATE.md            → docs/STATE.md
v1/docs/plans/              → docs/plans/
v1/docs/adr/                → docs/adr/   (si existe)
```

`v1/` queda vacío y se elimina.

### Fase 2 — Cleanup legacy (commit único)

**Borrar** todos estos ficheros/directorios pre-existentes (eran
v0.2):

```
niwa-app/                   → DELETE entero
bin/                        → DELETE entero
servers/                    → DELETE entero
caddy/                      → DELETE entero
config/                     → DELETE entero
setup.py                    → DELETE
docker-compose.yml.tmpl     → DELETE
docker-compose.advanced.yml → DELETE
niwa                        → DELETE (wrapper script)
niwa.env.example            → DELETE
INSTALL.md                  → DELETE (instrucciones obsoletas)
README.md                   → reescribir con README mínimo de v1
                              (Niwa v1, link a SPEC, install via
                              bootstrap.sh)
tests/                      → DELETE entero (los tests viejos;
                              los de v1 ya viven en backend/tests/)

docs/ARCHITECTURE.md        → DELETE (reemplazado por HANDBOOK)
docs/BUGS-FOUND.md          → DELETE (era v0.2)
docs/DECISIONS-LOG.md       → DELETE (era v0.2)
docs/MVP-ROADMAP.md         → DELETE (era v0.2)
docs/PLAN-AUTH-SUBSCRIPTION.md → DELETE
docs/RELEASE-RUNBOOK.md     → DELETE
docs/SPEC-v0.2.md           → DELETE
docs/state-machines.md      → DELETE (replaced por contratos en
                              backend/app/)
docs/v0.2-scope.md          → DELETE
docs/archive/               → DELETE
docs/adr/                   → preservar SOLO si tiene ADRs
                              relevantes a v1 (revisar caso a caso)
```

**Preservar** (si existe en raíz):

```
.git/                       → obviamente
.gitignore                  → revisar contenido, ajustar para
                              estructura nueva
.claude/                    → preservar (skill/agent definitions
                              del proyecto, codex-reviewer etc)
LICENSE                     → si existe
```

### Fase 3 — README de raíz

Reescribir `README.md` desde cero con un README mínimo:

```markdown
# Niwa

Personal autonomous code agent — turn natural language tasks
into git commits, PRs and deploys via the Claude Code CLI.

**Status:** v1 MVP. Single-user, single-machine.

See `docs/SPEC.md` for the full spec.

## Install

Requires Python 3.11+, Node 22+, git, claude CLI authenticated.

```
git clone https://github.com/takeo7/niwa.git
cd niwa
./bootstrap.sh
niwa-executor start
make dev
```

UI on http://127.0.0.1:5173.

## Architecture

See `docs/HANDBOOK.md`.
```

(El humano puede pulir copy después; este es el mínimo
funcional.)

### Fase 4 — Switch de ramas (post-merge, operacional)

**NO va dentro del PR.** Tras mergear el PR (squash sobre v1),
el orquestador ejecuta vía `gh` API:

```
# 1. Renombrar v0.2 a v0.2-legacy
gh api -X POST /repos/takeo7/niwa/branches/v0.2/rename \
  -f new_name=v0.2-legacy

# 2. Renombrar main a main-legacy
gh api -X POST /repos/takeo7/niwa/branches/main/rename \
  -f new_name=main-legacy

# 3. Renombrar v1 a main
gh api -X POST /repos/takeo7/niwa/branches/v1/rename \
  -f new_name=main

# 4. Cambiar default branch (se hace solo con el rename anterior
#    porque GitHub mueve el default si la rama default se renombra).
#    Verificar:
gh api /repos/takeo7/niwa | jq .default_branch
# debe imprimir "main"
```

Si las APIs MCP de GitHub disponibles no ofrecen `branches/rename`,
el orquestador PARA y lo deja documentado para que el humano lo
haga manualmente desde Settings → Branches en GitHub UI. Es una
operación de 30 segundos.

## Hard-cap

**No aplica el hard-cap normal de 400 LOC.** Este PR es:
- Movimientos (`git mv`) — neutros en LOC.
- Borrados — todos NEGATIVOS en LOC (~30k LOC borradas).
- README nuevo — ~30 LOC añadidas.

El diff neto será gigante en el lado de borrado. Está
explícitamente declarado y aceptado. Codex-reviewer va a tener
poco que decir porque no hay lógica nueva — solo movimientos.

## Fuera de scope

- No tocar el contenido funcional de `v1/backend`, `v1/frontend`,
  `v1/templates`. Solo se mueven, no se modifican.
- No re-mergear nada de v0.2 — todo lo de v0.2 que valía la pena
  ya está portado en v1/ (adapter, schema lessons, fake-CLI
  fixture).
- No actualizar `bootstrap.sh` rutas — el script ya usa
  `${SCRIPT_DIR}/backend` etc.; tras la promoción funcionará igual
  porque está al lado de `backend/` y `frontend/`.
- No tocar `pyproject.toml` — entry point sigue apuntando a
  `app.niwa_cli`.
- No romper la instalación existente del usuario en su Mac. Los
  paths del bootstrap son relativos al script, así que tras
  `git pull origin main` (post-rename) la próxima invocación
  reinstalará todo igual.

## Tests

Sin tests nuevos. Los 151 existentes deben seguir pasando tras la
promoción:

```
cd backend
pytest -q
```

→ 151 passed.

```
cd frontend
npm test -- --run
```

→ 12 passed.

Si algún test falla por path absoluto hardcoded a `v1/`, ese es un
bug en los tests que nunca se debió escribir así (debería ser
relativo a `__file__` o vía fixture). En ese caso, fix-up incluido
en este mismo PR para corregir el path.

## Criterio de hecho

- [ ] El árbol de la rama tras merge tiene la estructura:
      `backend/`, `frontend/`, `templates/`, `Makefile`,
      `bootstrap.sh`, `CLAUDE.md`, `data/`, `docs/`,
      `README.md`, `.claude/`, `.git/`, `.gitignore`. Nada más
      en raíz.
- [ ] `niwa-app/`, `bin/`, `servers/`, `setup.py`,
      `docker-compose*`, `caddy/`, `config/` NO existen.
- [ ] `pytest -q` desde la nueva raíz `backend/` → 151 passed.
- [ ] `npm test -- --run` desde la nueva raíz `frontend/` → 12 passed.
- [ ] `./bootstrap.sh` ejecutado en VM/máquina limpia (con shim
      python3.11 si Mac brew) instala correctamente.
- [ ] Tras el merge, `gh api /repos/takeo7/niwa | jq .default_branch`
      devuelve `"main"`.
- [ ] Las ramas `v0.2-legacy` y `main-legacy` existen en remote y
      contienen el HEAD original de `v0.2` y `main` pre-rename.
- [ ] `README.md` mínimo presente.

## Riesgos conocidos

- **Operaciones de rename via gh API requieren permisos de admin
  del repo.** Si el orquestador no tiene token con esos permisos,
  los renames se pasan al humano. La parte del PR (mover + borrar)
  funciona igual; solo la fase 4 queda manual.
- **Quien tenga clones locales del repo deberá actualizar tracking
  branches.** Comando one-liner para el humano:
  `git fetch origin --prune && git branch -m v1 main &&
   git branch --set-upstream-to=origin/main main`. Documentar en el
   commit message del rename.
- **GitHub Pages / CI configs que apuntaran a `main` legacy se
  romperían.** No hay CI configurado en v1, así que cero impacto
  en MVP. Cuando llegue v1.1 con CI, va al `main` nuevo.

## Notas para el implementador

- Todo el trabajo en una rama `claude/v1-pr-25-promote-and-cleanup`
  desde `origin/v1`.
- **Commits sugeridos** (cada uno verificable por separado):
  1. `chore(release): move v1/ contents to repo root`
  2. `chore(release): delete v0.2 legacy code (niwa-app, bin, servers, setup.py)`
  3. `chore(release): delete v0.2 docs (kept only what v1 uses)`
  4. `docs(release): rewrite README for v1 MVP`
  5. `chore(release): cleanup .gitignore for new structure`
- Tras crear el PR y ANTES de mergearlo, ejecutar `pytest -q` y
  `npm test` localmente para confirmar que ningún path está
  hardcoded.
- Tras mergear, **inmediatamente** ejecutar la fase 4 (renames).
  No dejar el repo en estado intermedio (v1 con todo limpio + main
  obsoleto sigue) porque confunde a otros consumidores.
- Tras los renames, ACTUALIZAR `STATE.md` en el nuevo `main` con:

  ```
  pr_merged: PR-V1-25
  date: <ISO>
  week: 6
  next_pr: (none)
  week_status: MVP-COMPLETE
  blockers: []
  ```

- En el chat, escribir resumen final del MVP: PRs totales,
  semanas, LOC, tests, smoke validado, y "MVP cerrado, listo para
  uso real con el segundo usuario (pareja del autor)."
