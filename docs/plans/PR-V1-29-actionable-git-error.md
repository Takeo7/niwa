# PR-V1-29 — `git_setup_failed` con mensaje accionable

**Tipo:** UX FIX
**Esfuerzo:** S
**Depende de:** ninguna

## Qué

Mejorar el mensaje de error que devuelve `_detect_default_branch`
en `backend/app/executor/git_workspace.py` cuando no encuentra
ninguna rama default. Hoy dice:

> "no default branch detected"

Eso no es accionable. Cambiarlo a un texto que diga al usuario
qué hacer:

> "no default branch detected: the repo has no `main`/`master`
> branch and no `origin/HEAD`. Run `git remote set-head origin -a`
> if it's a clone, or `git commit -m init` if it's a new repo."

## Por qué

Smoke real 2026-04-25 con la pareja del autor: una task falló
con `git_setup_failed: no default branch detected`. El mensaje
no le dijo qué hacer; el autor tuvo que diagnosticar a mano.

## Scope

```
backend/app/executor/git_workspace.py    # mensaje extendido
backend/tests/test_git_workspace.py       # +1 caso si aplica
```

**Hard-cap: 50 LOC.**

## Contrato

Reemplazar la línea 141:

```python
raise GitWorkspaceError("no default branch detected")
```

Por:

```python
raise GitWorkspaceError(
    "no default branch detected: the repo has no `main`/`master` "
    "branch and no `origin/HEAD`. Run `git remote set-head origin -a` "
    "if it's a clone, or `git commit -m init` if it's a new repo."
)
```

El `outcome=git_setup_failed` se mantiene; solo cambia el `error`
del RunEvent.

## Tests

Ajustar el test existente que asserte el mensaje (si existe), o
añadir uno: setup con repo sin commits ni branches → mensaje
contiene `git remote set-head origin -a`.

## Criterio de hecho

- [ ] El error_payload del RunEvent tras un git_setup_failed
      por falta de default branch contiene la sugerencia exacta.
- [ ] `pytest -q` pasa.
- [ ] Codex skip OK por ser S.
