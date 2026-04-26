# PR-V1-35 — Botón merge en vista de PRs

**Tipo:** FEATURE (UX action)
**Esfuerzo:** S
**Depende de:** PR-V1-34

## Qué

En la vista de PRs (PR-V1-34), añadir un botón "Merge" en cada
fila que sea mergeable. Al click, llama un endpoint que ejecuta
`gh pr merge <number> --squash --delete-branch` server-side.

## Por qué

Cierra el loop de "ver y actuar sobre PRs sin salir de Niwa".
Hoy en modo `safe`, Niwa abre el PR y el humano va a GitHub a
mergearlo manualmente. Botón inline ahorra el viaje.

## Scope

```
backend/app/api/projects.py        # +endpoint /pulls/<number>/merge
backend/app/services/github_pulls.py  # +merge_pull
backend/tests/test_github_pulls.py    # +2 casos

frontend/src/features/projects/PullsTab.tsx   # botón merge
frontend/tests/PullsTab.test.tsx              # +1 caso
```

**Hard-cap: 100 LOC.**

## Endpoint

### `POST /api/projects/{slug}/pulls/{number}/merge`

Body opcional:
```json
{ "method": "squash" }   // squash (default) | merge | rebase
```

1. Verifica que el project tiene `git_remote` y `gh` está disponible.
2. Detecta `owner/repo` desde el remote.
3. Ejecuta `gh pr merge <number> --repo <owner>/<repo> \
     --<method> --delete-branch --auto`.
4. Si `--auto` falla (no hay branch protection), retry sin `--auto`.
5. Devuelve 200 con `{"merged": true, "method": "squash"}` o
   error con detalle.

Errores:
- 404: PR no existe.
- 409: PR no es mergeable (conflicts, checks failing).
- 503: `gh` missing.
- 502: subprocess crash o timeout.

## Frontend

En cada fila de la tabla, si `mergeable === "MERGEABLE"`:

- Botón "Merge" pequeño (Mantine `Button` size xs).
- onClick → confirmación inline ("Merge with squash?") o sin
  confirmación si autonomy_mode del proyecto es dangerous.
- Mientras corre, botón disabled con loader.
- Si OK, toast verde + invalidación de la query → la fila
  desaparece (porque ya está merged y filtramos por state=open).
- Si fail, toast rojo con mensaje del backend.

## Tests

Backend:
- `test_merge_pull_calls_gh_with_squash`.
- `test_merge_pull_409_when_not_mergeable`: mock subprocess que
  devuelve error específico.

Frontend:
- `test_merge_button_disabled_for_non_mergeable_pulls`.

## Criterio de hecho

- [ ] Botón visible solo en PRs mergeables.
- [ ] Click ejecuta merge real, refetcha la lista.
- [ ] Errores gestionados con toasts.
- [ ] `pytest -q` y `npm test` pasan.

## Notas

Si el orquestador implementa esto antes de PR-V1-34, depende
explícitamente del endpoint de listing — no marshear sin él.
