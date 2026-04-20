# Niwa v1 — Handbook

Guía operativa y arquitectural del código dentro de `v1/`. Se actualiza
en cada PR que añade/quita módulo backend, feature frontend, tabla DB o
cambia el pipeline. El SPEC vive en `v1/docs/SPEC.md` — este documento
es el "cómo" práctico, no el "qué" del producto.

## Layout actual (tras PR-V1-08)

```
v1/
├── backend/                    # FastAPI app (Python 3.11+)
│   ├── app/
│   │   ├── __init__.py         # __version__
│   │   ├── main.py             # FastAPI factory, /api/health, api_router
│   │   ├── config.py           # ~/.niwa/config.toml loader
│   │   ├── db.py               # SQLAlchemy engine + Base + FK PRAGMA
│   │   ├── models/             # ORM models (SPEC §3)
│   │   ├── schemas/            # Pydantic v2 wire shapes
│   │   ├── services/           # pure functions over Session
│   │   ├── adapters/           # Claude Code CLI wrapper (stream-json parser)
│   │   ├── executor/           # daemon (polling, pipeline, git workspace,
│   │   │                       # CLI entrypoint)
│   │   └── api/                # HTTP routers + get_session dep
│   ├── alembic.ini
│   ├── migrations/             # env.py con render_as_batch=True
│   │   └── versions/           # initial_schema (9d205b6968c1)
│   ├── tests/                  # pytest + TestClient
│   │   └── fixtures/
│   │       └── fake_claude_cli.py  # stream-json emitter (replaces real claude)
│   └── pyproject.toml
├── frontend/                   # React 19 + Vite + Mantine v7
│   ├── src/
│   │   ├── main.tsx            # MantineProvider + Notifications +
│   │   │                       # QueryClient + BrowserRouter
│   │   ├── App.tsx             # <Routes> → / and /projects/:slug
│   │   ├── api.ts              # apiFetch + wire types
│   │   ├── shared/
│   │   │   └── AppShell.tsx    # header + <Outlet/>
│   │   ├── routes/             # route wrappers (ProjectsRoute,
│   │   │                       # ProjectDetailRoute)
│   │   └── features/
│   │       ├── projects/       # list, create modal, detail, hooks
│   │       └── tasks/          # list, create modal, hooks (+ polling)
│   ├── tests/                  # vitest + @testing-library/react
│   │   ├── setup.ts            # jsdom matchMedia polyfill
│   │   ├── renderWithProviders.tsx
│   │   ├── ProjectList.test.tsx
│   │   └── TaskCreateModal.test.tsx
│   ├── index.html
│   ├── vite.config.ts          # proxy /api → :8000 + vitest config
│   └── package.json
├── data/                       # SQLite dev DB vive aquí
├── docs/
│   ├── SPEC.md                 # contrato del producto
│   ├── HANDBOOK.md             # este documento
│   └── plans/                  # un brief por PR
└── Makefile                    # install | dev | test | clean
```

## Arranque en dev

```sh
cd v1
make install     # pip install -e .[dev] + npm install
make dev         # uvicorn :8000 + vite :5173
make test        # pytest + vitest
```

El backend bindea a `127.0.0.1` (SPEC §2: sin auth, acceso local). El
frontend proxea `/api/*` al backend, así `fetch('/api/health')`
funciona igual en dev y en build.

## Config

`app/config.py` carga `~/.niwa/config.toml` (o la ruta en
`NIWA_CONFIG`). Si no existe, valores por defecto:

- `server.host = 127.0.0.1`
- `server.port = 8000`
- `database.path = v1/data/niwa-v1.sqlite3`

## DB y migraciones

Declarative `Base` vive en `app/db.py`. Cada modelo se registra
importando `app.models`, que a su vez importa `Base` y los cinco
ficheros en `app/models/`. Alembic apunta a la misma metadata vía
`migrations/env.py`. `render_as_batch=True` porque SQLite no soporta la
mayoría de `ALTER TABLE` — cada cambio de schema recrea la tabla en
una copia.

`app/db.py` registra un listener `connect` sobre `Engine` que emite
`PRAGMA foreign_keys=ON` en cada conexión SQLite. Sin ese PRAGMA las
FKs se ignoran silenciosamente y las CASCADE/RESTRICT declaradas no
surten efecto.

### Data model (SPEC §3)

Las cinco tablas viven en `app/models/` y se crean juntas en la
migración `9d205b6968c1_initial_schema`:

- **`projects`** — repos sobre los que Niwa opera. Columnas clave:
  `slug` (único), `kind` (CHECK en `web-deployable|library|script`),
  `autonomy_mode` (CHECK `safe|dangerous`, default `safe`).
- **`tasks`** — unidades de trabajo. FK a `projects` con CASCADE;
  `parent_task_id` self-FK opcional para subtareas del triaje-split.
  `status` con CHECK sobre los siete estados del SPEC.
- **`task_events`** — log append-only por tarea. FK a `tasks` CASCADE.
  `kind` con CHECK sobre los cinco tipos de evento del SPEC.
  `payload_json` como `TEXT` serializado por el caller.
- **`runs`** — intentos de ejecución de una tarea. FK a `tasks`
  CASCADE. `status` con CHECK sobre los cinco estados del SPEC.
  `artifact_root` obligatorio (cwd absoluto del CLI).
- **`run_events`** — stream de eventos del CLI por run. FK a `runs`
  CASCADE. `payload_json` como `TEXT`.

Todos los timestamps (`created_at`, `updated_at`) usan
`server_default=func.now()` y `updated_at` además `onupdate=func.now()`.

Manda la declaración de las tablas con `cd v1/backend && alembic
upgrade head`; la reversión es `alembic downgrade base`.

## Tests

- **Backend:** `cd v1/backend && pytest -q` (fixture `client` monta
  `TestClient` sobre `app.main:app`).
- **Frontend:** `cd v1/frontend && npm test` (vitest + jsdom). Suite
  actual: 4 casos (`ProjectList.test.tsx` × 2 + `TaskCreateModal.test.tsx`
  × 2). El helper `renderWithProviders` monta `MantineProvider` +
  `QueryClientProvider` (retry=false) + `MemoryRouter` para aislar los
  componentes del router/fetch global. Ver "Tests frontend" más abajo
  para el detalle.

## API

Las rutas HTTP se montan bajo `/api` desde `app/api/__init__.py`. Cada
recurso tiene su propio módulo (un `APIRouter`) que re-exporta
`router`; el router raíz `api_router` los incluye. La dependencia
compartida `get_session` vive en `app/api/deps.py` y los tests la
sobrescriben vía `app.dependency_overrides` para inyectar una DB
aislada en memoria.

### `projects`

| Method | Path                       | Return                     |
|--------|----------------------------|----------------------------|
| GET    | `/api/projects`            | `200` + `list[ProjectRead]`, orden `created_at` ASC |
| POST   | `/api/projects`            | `201` + `ProjectRead`; `409` si `slug` duplicado; `422` si payload inválido |
| GET    | `/api/projects/{slug}`     | `200` + `ProjectRead`; `404` si no existe |
| PATCH  | `/api/projects/{slug}`     | `200` + `ProjectRead`; `422` si se intenta tocar `slug`; `404` si no existe |
| DELETE | `/api/projects/{slug}`     | `204` sin cuerpo; `404` si no existe |

Schemas en `app/schemas/project.py`. `slug` valida `^[a-z0-9-]+$`,
3-40 chars; `kind` ∈ `{web-deployable, library, script}`;
`autonomy_mode` ∈ `{safe, dangerous}` con default `safe`; `deploy_port`
en rango 1024-65535 si se proporciona. Renombrar slug = borrar y
recrear.

### `tasks`

| Method | Path                                  | Return                                                                                 |
|--------|---------------------------------------|----------------------------------------------------------------------------------------|
| GET    | `/api/projects/{slug}/tasks`          | `200` + `list[TaskRead]`, orden `created_at` ASC con tie-breaker por `id`; `404` si el slug no existe |
| POST   | `/api/projects/{slug}/tasks`          | `201` + `TaskRead` en `status="queued"`; `404` si el slug no existe; `422` si payload inválido |
| GET    | `/api/tasks/{task_id}`                | `200` + `TaskRead`; `404` si no existe                                                  |
| DELETE | `/api/tasks/{task_id}`                | `204` sin cuerpo; `404` si no existe; `409` si `status in (running, waiting_input)`     |

Schemas en `app/schemas/task.py`. `TaskCreate` acepta solo `title`
(1-200 chars) y `description` opcional (hasta 10 000 chars); todos los
demás campos (`status`, `branch_name`, `pr_url`, `pending_question`,
timestamps) los gestiona el servicio o el executor en PRs futuros. La
creación transita de `null → queued` en un solo commit que escribe
dos `task_events`: `created` con el título y `status_changed` con
`payload_json='{"from":null,"to":"queued"}'`. `DELETE` depende de las
FKs CASCADE declaradas en PR-V1-02 para limpiar `task_events`, `runs`
y `run_events`.

`GET /api/tasks/{id}` es deliberadamente global (no scoped a
proyecto) — SPEC §7 muestra la URL con slug pero la API solo necesita
el id, la UI se lleva el slug como contexto.

### `runs` (read-only)

| Method | Path                            | Return                                      |
|--------|---------------------------------|---------------------------------------------|
| GET    | `/api/tasks/{task_id}/runs`     | `200` + `list[RunRead]` (orden `created_at` ASC); `404` si `task_id` no existe |

Schema en `app/schemas/run.py`. `RunRead` expone las columnas de la tabla
`runs`. Los runs los crea el executor; no hay `POST /runs` (y no lo habrá:
lanzar un run = crear/encolar una task).

## Executor

Un único proceso Python que drena `tasks.status='queued'`. Desde PR-V1-07
el pipeline spawnea el CLI real de Claude Code vía `app.adapters`
(ver sección "Adapter Claude Code" más abajo). La forma del pipeline
(`claim_next_task` → `run_*` → escrituras a `run_events` + `task_events`)
se mantiene idéntica a la de PR-V1-05: solo cambian las entrañas del
`run_*` por-tarea, que pasa de un echo sintético a streamear el CLI.

### Layout

```
app/executor/
├── __init__.py       # re-exports (claim_next_task, run_adapter, process_pending, run_forever)
├── core.py           # pipeline puro sobre Session (usa ClaudeCodeAdapter + git_workspace)
├── git_workspace.py  # prepare_task_branch + build_branch_name (PR-V1-08)
├── runner.py         # loop de polling (SessionLocal + sleep)
└── __main__.py       # `python -m app.executor` (argparse: --once / --interval / --verbose)
```

### Pipeline

1. `claim_next_task(session)` → `Task | None`.
   - `BEGIN IMMEDIATE` para grabbing del reserved lock SQLite antes del
     `UPDATE`. Sin `FOR UPDATE` (SQLite no lo soporta).
   - `UPDATE tasks SET status='running' WHERE id=? AND status='queued'`.
     Si afecta 0 filas, otro executor ganó → devuelve `None`.
   - Escribe `task_event` `status_changed` `{"from":"queued","to":"running"}`.
   - Commit antes de devolver para liberar el lock rápido.
2. `run_adapter(session, task)` → `Run`.
   - Resuelve `artifact_root = project.local_path` (cadena vacía si el
     proyecto no existe, por ahora).
   - Crea `Run` en `running` con `model="claude-code"`,
     `started_at=now()`, `artifact_root=<project.local_path>`.
   - Escribe `run_event` `started` y commitea.
   - **PR-V1-08:** llama `prepare_task_branch(local_path, task)` y
     persiste `task.branch_name`. En `GitWorkspaceError` escribe
     `run_event` `error` con `reason="git_setup_failed: ..."`,
     finaliza con `outcome='git_setup_failed'` y **no** invoca al
     adapter. Ver §"Git workspace (PR-V1-08)".
   - Spawnea el adapter; cada `AdapterEvent` del stream-json se
     persiste como `run_event` con su propio commit (batch por evento;
     afinar a batch por N eventos es un tunable para un PR posterior).
   - Al terminar el stream, llama a `adapter.wait()` para cerrar el
     proceso y fijar `outcome` según `exit_code`.
   - Mapea `outcome` a estado terminal vía `_finalize`:
     - `cli_ok` + `exit_code == 0` → `run.status='completed'`,
       `task.status='done'`, `task.completed_at=now()`, `run_event`
       `completed`.
     - cualquier otro outcome (`cli_nonzero_exit`, `cli_not_found`,
       `timeout`, `adapter_exception`, `git_setup_failed`) →
       `run.status='failed'`, `task.status='failed'`, `run_event`
       `failed`.
   - Excepciones del adapter se capturan (nunca dejan el run en
     `running`): se escribe un `run_event` `error` con el mensaje y el
     outcome queda `adapter_exception`.
3. `process_pending(session)` → `int`. Loop de 1+2 hasta que
   `claim_next_task` devuelve `None`. Una task = una transacción; si
   `run_adapter` peta, rollback de esa iteración y re-raise.

### Estados de run (SPEC §3)

- `queued` → aún sin tocar (default del modelo, no se usa hoy porque el
  executor crea directamente en `running`).
- `running` → recién creado, aún no cerrado.
- `completed` → exit 0 y `outcome='cli_ok'`, trabajo cerrado.
- `failed` → el CLI salió con exit ≠ 0, el binario no se encontró, el
  timeout global disparó, o el adapter crasheó (ver tabla de outcomes
  en "Adapter Claude Code").
- `cancelled` → el usuario abortó (endpoint dedicado, futuro PR).

### CLI

```
python -m app.executor --once              # drain y salir
python -m app.executor                      # loop, interval=5s
python -m app.executor --interval 0.5       # loop rápido para dev
python -m app.executor --verbose            # log DEBUG
```

El daemon **no** se respawnea solo — cuando haya systemd unit (bootstrap,
Semana 4) será `Restart=on-failure`. En este PR, cualquier excepción mata
el proceso y el operador lo relanza.

### Timestamps

`started_at`, `finished_at` de `Run` y `completed_at` de `Task` se fijan
con `datetime.now(timezone.utc)` desde `services/runs.py` — **no** con
`func.now()`. SQLite `CURRENT_TIMESTAMP` es de granularidad 1 s y los
tests (y el ordering futuro de runs) necesitan microsegundos.

## Adapter Claude Code (PR-V1-07)

Encapsula el `subprocess.Popen` del CLI de Claude Code y el parser de
su stream-json. Vive en `app/adapters/claude_code.py` y es
**DB-agnóstico**: produce objetos Python; quien persiste es el executor
(`core._write_event`).

### Contrato del stream

Formato esperado: una línea JSON por evento en stdout. Cada línea se
parsea a un `AdapterEvent`:

```
@dataclass(frozen=True)
class AdapterEvent:
    kind: str                  # raw "type" del JSON; "unknown" si no viene
    payload: dict[str, Any]    # el JSON entero, sin tocar
    raw_line: str              # línea original (stripped) para debug
```

Reglas del parser:

- Líneas vacías o que no son JSON válido → warning de log y se descartan
  (no rompen el stream). Útil para logs de progreso mixtos que el CLI
  pueda escribir por error.
- Líneas cuyo JSON no es un objeto (array, número suelto…) → se
  descartan igual.
- El flush final de buffer sin `\n` al cerrar stdout se procesa como
  una línea más, para no perder el último evento.

### Outcomes (4)

La propiedad `adapter.outcome` queda fijada en uno de estos valores al
terminar `iter_events()` + `wait()`:

| Outcome             | Se fija cuando                                                            | Run status |
|---------------------|---------------------------------------------------------------------------|------------|
| `cli_ok`            | `iter_events` drenó stdout limpio y `proc.wait()` devolvió `0`.           | `completed` |
| `cli_nonzero_exit`  | `iter_events` drenó stdout limpio y el exit code fue distinto de `0`.     | `failed` |
| `cli_not_found`     | `cli_path` es `None`, no existe en disco, o `Popen` levanta `FileNotFoundError`. | `failed` |
| `timeout`           | El deadline global del adapter (ver env vars) se rebasó; `SIGTERM` + 5 s grace + `SIGKILL`. | `failed` |

Además, `executor.core.run_adapter` captura excepciones inesperadas del
adapter y fija `outcome='adapter_exception'` (también mapeado a
`failed`) escribiendo un `run_event` `error` con el mensaje truncado —
el run nunca queda atascado en `running`.

### Timeout, stderr, drenaje

- `selectors.DefaultSelector` sobre `proc.stdout` para que el polling
  respete el deadline global sin bloquear en `read()`.
- stderr se drena en un hilo daemon a un buffer de 64 KB con rotación
  (descarta bytes viejos al rebosar) para evitar el deadlock clásico
  de pipe-full del CLI.
- `_terminate()` envía `SIGTERM`, espera 5 s, y escala a `SIGKILL` si
  el proceso sigue vivo.

### Env vars

| Variable              | Default                | Uso                                         |
|-----------------------|------------------------|---------------------------------------------|
| `NIWA_CLAUDE_CLI`     | `shutil.which('claude')` | Ruta absoluta al binario. Tests la apuntan al fake. |
| `NIWA_CLAUDE_TIMEOUT` | `1800` (s)             | Deadline global en segundos. Parseable como `float`; valores inválidos caen al default con warning. |

### Fake CLI en tests

`v1/backend/tests/fixtures/fake_claude_cli.py` es un script Python
ejecutable que imita el contrato del CLI real: acepta el prompt por
stdin, escribe una secuencia configurable de líneas JSON en stdout, y
sale con el código que le indique la fixture. Se activa en los tests
apuntando `NIWA_CLAUDE_CLI` al path del fake antes de invocar el
executor, de modo que **todo el pipeline ejerce el código de producción**
— el único mock es el binario externo.

Cubre los 4 outcomes con combinaciones de args: stream normal + exit 0,
stream + exit 1, no-existe (apuntando a path inválido), y prompt que
duerme más que el timeout.

## Git workspace (PR-V1-08)

Antes de spawnear el adapter, `run_adapter` llama a
`prepare_task_branch(project.local_path, task)` en
`app/executor/git_workspace.py`. Esto garantiza que **cada task corre en
su propia rama git** y no mezcla cambios del usuario con los de Niwa.

### Formato del branch name

```
niwa/task-<task.id>-<slug>
```

`<slug>` deriva de `task.title` con la función pura
`build_branch_name(task)`:

1. lowercase;
2. `[^a-z0-9]+` → `-`;
3. strip leading/trailing `-`;
4. truncar a 30 caracteres;
5. si resulta vacío (título solo símbolos) → `untitled`.

El `task.id` garantiza unicidad entre tasks del mismo proyecto; el slug
da legibilidad.

> Nota: el brief (docs/plans/PR-V1-08) trae un ejemplo trabajado con 25
> chars en el slug; la regla literal "truncar a 30" es la fuente de
> verdad y la implementación aplica 30. La discrepancia se flagea aquí
> para que un futuro PR alinee el ejemplo si se prefiere.

### Invariantes

`prepare_task_branch` exige dos cosas sobre `project.local_path`:

1. **Es un repo git** (`git rev-parse --is-inside-work-tree` == `true`).
   Bare repos y directorios planos son rechazados.
2. **Working tree limpio** (`git status --porcelain` vacío). No hay
   stash automático — la responsabilidad es del usuario: si el repo
   está sucio cuando encola la task, la task falla.

Si la rama `niwa/task-<id>-<slug>` **ya existe** (p. ej. reintento
manual tras un `git_setup_failed`), se hace `git checkout` sin reset y
se reutiliza. Los commits previos en esa rama se preservan.

### Outcomes y flujo en el executor

`run_adapter` en `app/executor/core.py`:

1. Crea `Run` + `RunEvent(started)`.
2. Llama `prepare_task_branch`. En éxito persiste `task.branch_name`.
3. En fallo (`GitWorkspaceError`) escribe `RunEvent(error)` con
   `payload_json={"reason": "git_setup_failed: <mensaje>"}`, finaliza
   con `outcome='git_setup_failed'`, `run.exit_code=None`, y **NO
   invoca al adapter**.
4. En éxito spawnea el adapter como antes.

Outcomes posibles para un `Run` tras este PR:

- `cli_ok` / `cli_nonzero_exit` / `cli_not_found` / `timeout` /
  `adapter_exception` (del adapter, ver §Adapter).
- `git_setup_failed` (de `prepare_task_branch`).

### Fuera del scope de este PR

- **No hay commit al final del run.** El working tree queda con los
  cambios de Niwa no commiteados. PR-V1-11+ (finalize).
- **No hay push al remote.** PR-V1-11+.
- **No se abre PR GitHub.** PR-V1-12+.
- **No hay garbage collection** de ramas viejas.
- **HEAD detached** en el proyecto: `git checkout -b` parte desde donde
  esté. Aceptable para MVP.
- **Submódulos**: `git checkout -b` no los inicializa.
- **Carrera usuario vs executor** en la misma working tree: sin
  protección — uso monousuario local por diseño (SPEC §2).

### Tests

- `tests/test_git_workspace.py` (5 cases): `build_branch_name` table,
  creates+switches, reuses existing, rejects non-git, rejects dirty.
- `tests/test_executor.py::test_runs_fail_on_git_setup_error`: outcome
  end-to-end con project apuntando a directorio no-git.
- La fixture `git_project(tmp_path)` vive en `conftest.py` y crea un
  repo con un commit seed + `commit.gpgsign=false` local (algunos
  sandboxes fuerzan gpg globalmente).
- `test_executor.py` happy-path assert `task.branch_name ==
  build_branch_name(task)` para confirmar la persistencia.
- Tests de `test_adapter.py` y `test_runs_api.py` migrados a
  `git_project` en lugar de `tmp_path` crudo.

## Frontend

React 19 + Vite + Mantine v7 + TanStack Query + React Router 7. No hay
state manager global: React Query hace de caché servidor-side y Mantine
maneja el UI state (forms, modals, notifs).

### Shell y rutas (PR-V1-06a)

`src/main.tsx` monta de fuera a dentro: `MantineProvider` →
`Notifications` → `QueryClientProvider` → `BrowserRouter`. `App.tsx`
declara rutas dentro de `shared/AppShell.tsx` (header "Niwa v1" +
`<Outlet/>`):

- `/` → `features/projects/ProjectList.tsx` — cards + botón "Nuevo
  proyecto" que abre `ProjectCreateModal`. Empty state literal
  `"No projects yet"` (los tests dependen del string).
- `/projects/:slug` → `features/projects/ProjectDetail.tsx` — nombre +
  kind + bloque de tareas (lista embebida + botón "Nueva tarea").

`features/projects/api.ts` expone `useProjects`, `useProject(slug)` y
`useCreateProject` sobre `/api/projects`; la mutation invalida
`["projects"]` al ganar y notifica éxito/error (409 → "el slug ya
existe").

El detalle de tarea (`/projects/:slug/tasks/:id`) y `/system` llegan en
PRs posteriores (SPEC §7).

### Tasks UI (PR-V1-06b)

`features/tasks/` cuelga del detalle de proyecto con tres piezas:

- `TaskList.tsx` — tabla de tareas (título, badge de estado, fecha,
  botón delete). Empty state literal `"No tasks yet"`. El color del
  badge se mapea en un `STATUS_COLOR` local a `TaskList`, no en
  `api.ts`, porque es pura decisión de render.
- `TaskCreateModal.tsx` — modal Mantine con `title` (requerido,
  1-200 chars) y `description` (textarea autosize, opcional). El
  botón "Crear" está `disabled` hasta que `form.isValid("title")`
  devuelve `true`; el submit hace `POST /api/projects/:slug/tasks`
  vía `useCreateTask`, muestra toast y cierra el modal.
- `features/tasks/api.ts` — hooks `useTasks(slug, { enablePolling })`,
  `useCreateTask(slug)`, `useDeleteTask(slug)`.

Reglas de la capa de datos:

1. **Polling condicional.** `useTasks` pasa `refetchInterval` como
   función del `QueryState`: devuelve `false` mientras `data` esté
   `undefined` (cold start) o la lista no tenga ninguna tarea en
   `queued|running|waiting_input`; devuelve `2000` ms cuando sí la
   tiene. El helper puro `hasInFlightTask(tasks)` vive en
   `src/api.ts` y lo comparten futuros consumidores (spinners, etc.).
   La opción `enablePolling:false` está para permitir desactivar el
   timer desde tests sin mockear el hook.
2. **Create → refetch inmediato.** `useCreateTask` invalida
   `["tasks", slug]` en `onSuccess`, no depende de la ventana de 2 s
   del polling.
3. **Delete con 409.** El botón solo se pinta para estados
   `inbox|queued|done|failed|cancelled` (helper `isTaskActive` en
   `src/api.ts`). Si el backend igualmente responde `409` (porque la
   tarea transicionó a `running|waiting_input` entre render y click),
   se muestra un toast legible y se invalida la query
   (`onSettled`, tanto en success como error) para que la UI refleje
   el estado real.

### Tests frontend (actualizado)

Vitest (jsdom). `tests/setup.ts` añade el polyfill de `matchMedia` que
Mantine necesita. `tests/renderWithProviders.tsx` monta
`MantineProvider` + `QueryClientProvider` (retry=false) +
`MemoryRouter`. El mock de `fetch` se hace con `vi.stubGlobal` — Vitest
no pasa por el proxy.

Suite actual (4 casos, 4 passed):

- `ProjectList.test.tsx` — empty state y render de tarjetas.
- `TaskCreateModal.test.tsx` — botón submit deshabilitado con título
  vacío; submit válido llama `POST /api/projects/:slug/tasks` con el
  payload esperado y dispara `onClose`.

### Proxy Vite → backend

`vite.config.ts` declara `server.proxy['/api'] → http://127.0.0.1:8000`.
Así evitamos abrir CORS en FastAPI: el backend mantiene `127.0.0.1` sin
CORS (SPEC §2 — binding local) y el frontend usa rutas relativas
`/api/...` que el dev server tunela.

## Próximos PRs (SPEC §9)

- PR-V1-08: ejecución aislada en rama git por task. Crear/chequear
  `niwa/<task_id>-<slug>`, sandboxear el CLI en ella, post-run con
  diff + commit + push + PR. El adapter actual queda intacto.
- PR-V1-09+: UI de detalle de tarea (`/projects/:slug/tasks/:id`)
  consumiendo los `run_events` del stream real, feedback de aprobación
  humana, y verificación post-run (Semana 3 del SPEC).

Ver `v1/docs/plans/` para los briefs conforme se escriben.
