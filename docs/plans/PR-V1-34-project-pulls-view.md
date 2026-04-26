# PR-V1-34 — Vista de PRs en proyecto

**Tipo:** FEATURE (UX visibility)
**Esfuerzo:** M
**Depende de:** ninguna (consume `gh` CLI)

## Qué

Pestaña nueva "Pull requests" en el detalle de proyecto. Lista
los PRs abiertos en GitHub que Niwa abrió, con:

- Número del PR (#123) + título.
- Estado (open / merged / closed).
- Fecha de creación.
- Mergeable (yes / no / unknown).
- Checks status (passing / failing / pending / none).
- Botón abrir en GitHub.

Se obtiene vía `gh pr list --json` ejecutado server-side.

## Por qué

Pareja del autor pidió "gestión de ramas y GitHub". Hoy
`task.pr_url` muestra el link al PR pero no su estado. Para ver
si el PR está listo para mergear o si los checks fallan, tiene
que abrir GitHub web. Llevarlo dentro de Niwa cierra el loop sin
salir.

## Scope

```
backend/app/api/projects.py             # +endpoint /pulls
backend/app/services/github_pulls.py    # NUEVO: gh wrapper
backend/tests/test_github_pulls.py      # NUEVO

frontend/src/features/projects/ProjectDetail.tsx  # tab nueva
frontend/src/features/projects/PullsTab.tsx       # NUEVO
frontend/src/features/projects/api.ts             # listPulls
frontend/tests/PullsTab.test.tsx                  # NUEVO
```

**Hard-cap: 300 LOC.**

## Fuera de scope

- **NO mergea** desde la UI. Eso es PR-V1-35.
- No autenticación con GitHub OAuth — usa el `gh` CLI ya
  autenticado, herencia del usuario que corre el backend.
- No actualiza en streaming — refetchInterval cada 60s mientras
  la pestaña está visible.
- No filtros (solo open / closed / all top-level).

## Endpoint

### `GET /api/projects/{slug}/pulls?state=open|closed|all`

1. Lee `project.git_remote`. Si NULL → 200 con array vacío y
   warning JSON `{"warning": "no_remote"}`.
2. Verifica `shutil.which("gh")`. Si no → 503 con
   `{"error": "gh_missing"}`.
3. Detecta el repo desde el remote URL: extrae `owner/repo`
   (regex sobre `git_remote`).
4. Ejecuta `gh pr list --repo <owner>/<repo> --state <state> \
     --json number,title,state,url,mergeable,statusCheckRollup,
            createdAt,updatedAt,headRefName \
     --limit 30`.
5. Filtra a PRs cuya `headRefName` empiece por `niwa/task-` (los
   que abrió Niwa). Si quieres ver todos, pasa
   `?include_all=true` (default false).
6. Devuelve la lista parseada.

Timeout 15s en el subprocess.

## Frontend

### Tab nueva en `ProjectDetail.tsx`

Mantine `Tabs`. Dos tabs hoy: "Tareas" (lo actual) y "Pull
requests".

### `PullsTab.tsx`

Tabla Mantine con columnas: número, título, estado (badge),
mergeable (badge), checks (icono + tooltip), creación, link.

`useQuery` con `refetchInterval: 60000` cuando la tab está
visible (usar `enabled: isTabActive`).

Empty state: "No PRs yet — Niwa opens a PR for each task that
finishes when this project has a `git_remote` configured."

Si el endpoint devuelve `gh_missing`, mostrar mensaje "Install
the GitHub CLI to see PRs: `brew install gh && gh auth login`".

## Tests

Backend:
- `test_list_pulls_filters_to_niwa_branches`: mock subprocess
  con respuesta de 5 PRs, 3 con `headRefName` empezando en
  `niwa/`, 2 no → endpoint devuelve 3.
- `test_list_pulls_returns_warning_when_no_remote`.
- `test_list_pulls_returns_503_when_gh_missing`.

Frontend:
- `test_pulls_tab_renders_table_with_data`.
- `test_pulls_tab_shows_install_message_when_gh_missing`.

## Criterio de hecho

- [ ] Tab "Pull requests" visible en project detail.
- [ ] Lista de PRs abiertos por Niwa con estado correcto.
- [ ] Refetch automático cada 60s mientras la tab está activa.
- [ ] Mensaje claro si `gh` no está instalado.
- [ ] `pytest -q` y `npm test` pasan con +5 nuevos.
- [ ] Codex ejecutado (toca subprocess + UI nueva, merece review).

## Riesgos

- **Permisos del `gh` server-side:** el subprocess hereda las
  credenciales del usuario que corre el backend (el systemd user
  unit). Si el usuario no autenticó `gh`, falla. Documentar.
- **Rate limit de GitHub:** 60 req/h sin auth, 5000/h con auth.
  Con `gh` autenticado y refetch 60s, max 60 req/h por tab
  abierta. OK.
