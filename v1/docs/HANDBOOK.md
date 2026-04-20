# Niwa v1 — Handbook

Guía operativa y arquitectural del código dentro de `v1/`. Se actualiza
en cada PR que añade/quita módulo backend, feature frontend, tabla DB o
cambia el pipeline. El SPEC vive en `v1/docs/SPEC.md` — este documento
es el "cómo" práctico, no el "qué" del producto.

## Layout actual (tras PR-V1-06b)

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
│   │   ├── executor/           # echo daemon (polling, core pipeline, CLI)
│   │   └── api/                # HTTP routers + get_session dep
│   ├── alembic.ini
│   ├── migrations/             # env.py con render_as_batch=True
│   │   └── versions/           # initial_schema (9d205b6968c1)
│   ├── tests/                  # pytest + TestClient
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

Un único proceso Python que drena `tasks.status='queued'`. SPEC §9
Semana 1 lo deja en modo *echo*: no hay Claude CLI, no hay rama git, no
hay verificación. El adapter real llega en Semana 2 y sustituye
`run_echo` sin cambiar el resto del pipeline.

### Layout

```
app/executor/
├── __init__.py       # re-exports (claim_next_task, run_echo, process_pending, run_forever)
├── core.py           # pipeline puro sobre Session
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
2. `run_echo(session, task)` → `Run`.
   - Crea `Run` en `running` con `model="echo"`, `artifact_root=""`,
     `started_at=now()`.
   - Escribe `run_event` `started`.
   - Inmediatamente: `Run.status='completed'`, `exit_code=0`,
     `outcome='echo'`, `finished_at=now()`.
   - Escribe `run_event` `completed`.
   - `Task.status='done'`, `completed_at=now()`.
   - Escribe `task_event` `status_changed` `{"from":"running","to":"done"}`.
   - Commit único de toda la transición.
3. `process_pending(session)` → `int`. Loop de 1+2 hasta que
   `claim_next_task` devuelve `None`. Una task = una transacción; si
   `run_echo` peta, rollback de esa iteración y re-raise.

### Estados de run (SPEC §3)

- `queued` → aún sin tocar (default del modelo, no se usa hoy porque el
  executor crea directamente en `running`).
- `running` → recién creado, aún no cerrado.
- `completed` → exit 0, trabajo cerrado. El MVP echo siempre llega aquí.
- `failed` → cualquier condición de evidencia (Semana 3) falló.
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

- PR-V1-07+: adapter Claude Code real (Semana 2) que reemplaza
  `run_echo` y conecta el stream-json a la DB. El cuerpo del pipeline
  (`claim_next_task` + `process_pending`) se mantiene. La UI de detalle
  de tarea (`/projects/:slug/tasks/:id`) llega cuando haya stream real
  que mostrar.

Ver `v1/docs/plans/` para los briefs conforme se escriben.
