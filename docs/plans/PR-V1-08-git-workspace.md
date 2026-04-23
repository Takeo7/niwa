# PR-V1-08 — Git workspace: branch per task

**Semana:** 2
**Esfuerzo:** M
**Depende de:** PR-V1-07 mergeado (adapter en su sitio).

## Qué

Antes de que el adapter corra, el executor crea y cambia a una rama
`niwa/task-<id>-<slug>` en `project.local_path`. Guarda
`task.branch_name`. Si el path no es un repo git o la working tree
está sucia, la task termina `failed` con `outcome='git_setup_failed'`
sin llegar a invocar al adapter. **No** hay commit, push ni PR — esos
son finalize (Semana 3/4).

## Por qué

SPEC §1: "Crea rama `niwa/<task-slug>` en el repo del proyecto". §9
Semana 2: "ejecución en rama nueva". Sin este paso, el adapter muta
el working tree sobre la rama que haya (p. ej. `main`), mezclando
cambios del usuario con los de Niwa. Aislar cada task en su rama es
la invariante que hace posible el `finalize` futuro.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── executor/
│       ├── git_workspace.py                  # nuevo, ~100 LOC
│       └── core.py                           # +30 LOC: prepare → run → cleanup
└── tests/
    ├── test_git_workspace.py                 # nuevo, 4 casos
    └── test_executor.py                      # fixtures con git init;
                                              # asserts sobre branch_name
```

**Hard-cap:** 400 LOC netas. Si excedes, PARAS.

## Fuera de scope (explícito)

- **No hay commit al final del run.** Working tree queda con los
  cambios no commiteados en la rama `niwa/...`. PR-V1-11+ (finalize).
- **No hay push al remote.** PR-V1-11+.
- **No se abre PR GitHub.** PR-V1-12+.
- **No hay stash automático.** Si la working tree del proyecto está
  sucia al arrancar la task, se rechaza (`git_setup_failed`). El
  usuario es responsable de dejar su repo limpio antes de encolar
  tareas.
- **No se borra la rama al terminar.** Queda para inspección. La
  gestión de ramas viejas (garbage collection) es follow-up.
- **No se toca `project.git_remote`** — irrelevante en este PR (no
  hay push). Solo se usa `project.local_path`.
- **No hay reintentos.** Si `git_setup` falla, la task termina
  `failed` y no se reencola.
- **No hay branch conflicts.** Si `niwa/task-<id>-<slug>` ya existe
  (reintento manual), se hace `git checkout` de la existente sin
  reset, y se continúa. Documentado.

## Formato del branch name

```
niwa/task-<task.id>-<slug>
```

donde `<slug>` deriva de `task.title`:
- lowercase
- `[^a-z0-9]+` → `-`
- colapsar `-` consecutivos
- strip `-` inicial/final
- truncar a 30 caracteres
- si resulta vacío (título solo símbolos): `<slug>` = `untitled`

Ejemplo: `task.id=42, task.title="Fix: login crashes on empty email"`
→ `niwa/task-42-fix-login-crashes-on-empt`.

El `<task.id>` garantiza unicidad, el slug da legibilidad. Single
fuente de verdad: función `build_branch_name(task) -> str` en
`git_workspace.py`.

## Dependencias nuevas

- Python: **ninguna** (stdlib `subprocess`, `re`).
- npm: **ninguna**.

## Tests

**Nuevos en `v1/backend/tests/test_git_workspace.py`** (4 casos):

1. `test_prepare_task_branch_creates_and_switches` — `tmp_path` con
   `git init` y un commit inicial. Llamar `prepare_task_branch()` →
   verificar que `git branch --show-current` devuelve
   `niwa/task-<id>-<slug>`, y que la función retorna ese string.
2. `test_prepare_reuses_existing_branch` — crear la rama objetivo
   manualmente primero. `prepare_task_branch()` detecta que existe,
   hace `git checkout` sin crear, y retorna el mismo nombre. No
   borra commits existentes en esa rama.
3. `test_prepare_rejects_non_git_dir` — `tmp_path` sin `.git`.
   Llamada lanza `GitWorkspaceError` con mensaje legible. El
   executor lo traduce a `outcome='git_setup_failed'`.
4. `test_prepare_rejects_dirty_working_tree` — repo con fichero
   modificado no commiteado. `prepare_task_branch()` lanza
   `GitWorkspaceError`. **No** hace stash automático.

**Tests de executor actualizados** (`test_executor.py`): los 7 casos
del baseline deben montar un `project.local_path` que sea un git
repo válido (no solo un directorio vacío). Añadir fixture
`git_project(tmp_path)` que hace `git init` + `git config
user.email/name` + commit inicial vacío. Asserts añadidos: tras un
run exitoso, `task.branch_name` contiene el valor esperado; en un
run fallido por `git_setup_failed`, `task.branch_name` queda `None`
y `task.status='failed'` y el adapter **no se invocó**.

**Test nuevo de outcome específico:**
`test_executor.py::test_runs_fail_on_git_setup_error` — project
apuntando a un dir no-git; task encolada; `process_pending` ejecuta
una iteración y la task acaba `failed`, con un `RunEvent` de
`event_type='error'` con payload `{"reason": "git_setup_failed: ..."}`.
El adapter no se spawneó (assert sobre `NIWA_CLAUDE_CLI` no-leído,
o verificación indirecta: `run.model` puede quedar `claude-code` pero
`run.exit_code is None` y no hay evento `started` de la CLI).

**Baseline tras PR-V1-08:**
- Backend: **55 passed** (50 actuales + 4 git_workspace + 1 outcome
  específico). Los 7 de executor se mantienen, ahora con git init.
- Frontend: 4 passed (no tocado).

## Criterio de hecho

- [ ] `v1/backend/app/executor/git_workspace.py` expone
  `prepare_task_branch(local_path, task)` que devuelve el branch
  name, y `GitWorkspaceError` para fallos.
- [ ] `build_branch_name(task)` público (testeable aislado).
- [ ] `run_adapter` llama `prepare_task_branch` antes de spawn.
- [ ] En fallo de git setup: run+task → `failed`,
  `outcome='git_setup_failed'`, `task.branch_name=None`, adapter
  NO se invoca.
- [ ] En éxito: `task.branch_name` persistido antes del run;
  adapter corre con cwd en `project.local_path` (ya está en la rama
  nueva desde el git checkout).
- [ ] `subprocess` calls a git usan `check=True` y capturan stderr
  para mensaje de error legible en `GitWorkspaceError`.
- [ ] `pytest -q` en `v1/backend/` → 55 passed.
- [ ] HANDBOOK actualizado con sección "Git workspace (PR-V1-08)":
  formato branch name, invariantes (repo git + working tree limpio),
  outcomes, reutilización de rama existente.
- [ ] Codex-reviewer ejecutado.

## Riesgos conocidos

- **`git` CLI ausente en el sistema.** Si `git` no está en PATH, el
  adapter nunca se invocará. `prepare_task_branch` debe capturar
  `FileNotFoundError` de `subprocess.run` y mapearlo a
  `GitWorkspaceError("git cli not found in PATH")`.
- **Config de git del executor.** Al crear una rama/commit, git puede
  exigir `user.email`/`user.name`. En este PR **no** hacemos commits,
  solo `checkout`, que no requiere config. Documentar.
- **HEAD detached.** Si el repo del proyecto está en HEAD detached,
  `git checkout -b` parte desde ahí, lo cual puede no ser lo que el
  usuario espera. Aceptable para MVP; documentado en HANDBOOK.
- **Submódulos.** `git checkout -b` no inicializa submódulos. Si el
  proyecto los usa, el adapter verá su estado inicial. Fuera de
  scope del MVP.
- **Carrera entre executor y usuario.** Si el usuario hace `git
  checkout` en la misma working tree mientras el executor corre,
  todo se puede torcer. El MVP no protege contra esto — se asume uso
  monousuario local por diseño (SPEC §2).

## Notas para Claude Code

- Commits sugeridos:
  1. `feat(backend): git workspace module for per-task branches`
  2. `refactor(backend): prepare task branch before adapter spawn`
  3. `test(backend): git workspace unit tests`
  4. `test(backend): executor uses real git fixture`
  5. `docs(v1): handbook git workspace section`
- Usa `subprocess.run([git, ...], cwd=local_path, check=True,
  capture_output=True, text=True)`. No construyas comandos con
  `shell=True`.
- Aísla la invocación de git en un helper `_run_git(args, cwd)` del
  módulo para facilitar mocking/testing.
- `build_branch_name` es pura — no toca disk ni procesos. Test
  unitario dedicado (5 casos: título normal, con símbolos,
  todo-símbolos, muy largo, vacío) — pueden ser todos dentro de
  `test_git_workspace.py::test_build_branch_name_cases`.
- La fixture `git_project` en `conftest.py` o en `test_executor.py`,
  como prefieras; no dupliques la lógica de `git init` en cada test.
- Si algo del SPEC queda ambiguo (p. ej. qué hacer si ya hay otra
  rama `niwa/...` activa), documentar y seguir — no parar.
