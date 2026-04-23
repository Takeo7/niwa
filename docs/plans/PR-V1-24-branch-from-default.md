# PR-V1-24 — Rama por tarea desde default branch

**Tipo:** FIX (bug menor de workspace)
**Semana:** 6
**Esfuerzo:** S
**Depende de:** ninguna

## Qué

`prepare_task_branch` (PR-V1-08) crea las ramas
`niwa/task-<id>-<slug>` desde el HEAD actual del checkout — la
última rama activa del ejecutor. El resultado: la rama nueva
hereda commits de ramas hermanas de Niwa, no sale limpia desde la
default branch del repo. Fix: ramificar siempre desde la default
branch (`main` o `master` según el repo).

## Por qué

Smoke 2026-04-22: task 12 (pregunta-forzada) se creó cuando el
executor tenía checkout en `niwa/task-11-*`. Resultado: la rama
`niwa/task-12-pregunta-forzada` contenía el commit de LICENSE
(`4d6fb97 niwa: Add MIT LICENSE file`) que pertenecía a la rama
de la task 10. Evidencia:

```
$ git log --all --oneline -15   # en el repo playground
4d6fb97 niwa: Add MIT LICENSE file    ← debería estar solo en task-10
4785ae7 niwa: readme3
43d9a8d init

$ cat LICENSE   # en la rama niwa/task-12-pregunta-forzada
MIT License ...                ← presente porque rama salió desde HEAD
                                 = task-10 commit, no desde master
```

Implicaciones reales:
- Si varias tasks corren en paralelo contra el mismo repo, las
  segundas heredan artefactos de las primeras.
- El PR generado por finalize puede incluir commits de otras
  tasks, ensuciando el diff.
- Si una task espera "empiezo desde master limpio", puede creer
  que el LICENSE ya existe y no crearlo, produciendo
  `no_artifacts` falsamente positivo en E3.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── executor/
│       └── git_workspace.py        # detect default + checkout -b from it
└── tests/
    └── test_git_workspace.py       # +3 cases
```

**Hard-cap: 150 LOC** código + tests.

## Fuera de scope

- No implementar `git remote set-head` ni gestión de remotes
  complejos. Detección local-first.
- No fallback a "cualquier rama con commits"; si no detectamos
  una default, fallamos explícitamente con error claro.
- No cambiar el nombre de las ramas ni el formato del slug
  (eso es otro bug del smoke pero cosmético — post-MVP).

## Contrato tras el fix

### Nueva función: `_detect_default_branch(local_path) -> str`

Orden de detección:

1. `git symbolic-ref refs/remotes/origin/HEAD` → si sale
   `refs/remotes/origin/main` o similar, devolver la parte final.
   Este es el caso más fiable cuando hay remote.
2. Fallback: `git show-ref --verify --quiet refs/heads/main` →
   si existe, devolver `"main"`.
3. Fallback: `git show-ref --verify --quiet refs/heads/master` →
   si existe, devolver `"master"`.
4. Fallback: primera rama listada por `git branch --format='%(refname:short)'`.
5. Si ninguna de las anteriores funciona → `GitWorkspaceError`
   con mensaje "no default branch detected".

### En `prepare_task_branch`

Antes del `checkout -b` para rama nueva:

```python
default_branch = _detect_default_branch(local_path)
_run_git(["checkout", default_branch], cwd=local_path)
_run_git(["checkout", "-b", branch_name], cwd=local_path)
```

Para rama existente (ya exists), sigue con `git checkout <branch>`
sin tocar la default — asumimos que el estado de la rama anterior
es lo que se quiere reanudar.

Idempotencia se mantiene: si la rama existe, no se recrea.

## Tests

- `test_detect_default_prefers_origin_head`: repo con remote y
  `origin/HEAD` apuntando a `main` → detecta `main`.
- `test_detect_default_falls_back_to_main`: repo sin remote, con
  branch `main` → detecta `main`.
- `test_detect_default_falls_back_to_master`: repo sin remote,
  con branch `master` (no `main`) → detecta `master`.
- `test_prepare_branch_from_default_not_current_head`: setup con
  un repo que tiene dos ramas `master` y `feature-a`, checkout
  activo en `feature-a`; `prepare_task_branch` crea
  `niwa/task-N-test` → `git log niwa/task-N-test` contiene solo
  los commits de `master`, NO los de `feature-a`.

### Baseline tras el fix

147 + 4 = **151 passed** (asumiendo 22 y 23 mergeados antes).

## Criterio de hecho

- [ ] `pytest -q` → ≥151 passed, 0 regresiones.
- [ ] Smoke manual: tras merge, reencolar dos tasks en secuencia
      sobre el mismo repo de prueba. Cada una termina en una rama
      limpia que parte de `master`, sin heredar commits de la
      otra. Verificar con
      `git log master..niwa/task-N-<slug>` que solo aparecen
      commits propios de esa task.
- [ ] Codex-reviewer ejecutado.

## Riesgos conocidos

- **Repo con default branch no estándar:** si el usuario usa
  nombres raros tipo `develop` como default, la detección vía
  `origin/HEAD` lo maneja bien. Sin remote, el fallback solo
  cubre `main`/`master`. Aceptable — si alguien usa `develop` sin
  remote, error claro y tendrá que configurar `origin/HEAD`
  manualmente.
- **Working tree modificado durante el switch:** el guard de
  `prepare_task_branch` (PR-V1-08) ya valida tree limpio ANTES
  del switch, así que el `checkout <default>` es seguro.

## Notas para el implementador

- Extender el módulo `git_workspace.py` con `_detect_default_branch`.
- Usar el helper `_run_git` existente para todas las llamadas.
- Los tests pueden usar fixture `git_project` ya existente
  (PR-V1-08) como base.
- Commits sugeridos:
  1. `feat(git_workspace): detect default branch via origin/HEAD + fallbacks`
  2. `feat(git_workspace): create task branch from default, not HEAD`
  3. `test: coverage for default branch detection + isolation`
