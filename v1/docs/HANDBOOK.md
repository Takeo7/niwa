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

### SSE run events (PR-V1-09)

| Method | Path                            | Return                                      |
|--------|---------------------------------|---------------------------------------------|
| GET    | `/api/runs/{run_id}/events`     | `200` + `text/event-stream` (SSE); `404` JSON si `run_id` no existe |

Transporte unidireccional server→client para que la UI (PR-V1-10) pinte
el stream del adapter en vivo sin polling del CRUD. La implementación
vive en `app/api/runs.py` (router) y `app/services/run_events.py`
(helpers puros + lectores sobre `Session`).

**Formato de cada frame (evento histórico o nuevo):**

```
id: <run_event.id>
event: <run_event.event_type>
data: {"id": 42, "event_type": "assistant", "payload": {...}, "created_at": "2026-..."}
```

`payload_json` de DB se parsea con `json.loads` antes de re-dumpearlo
dentro de `data`, así el cliente recibe un objeto JSON y no una string
escapada.

**Terminación (`eos`):** cuando `Run.status` llega a
`completed|failed|cancelled`, el stream emite un último frame y cierra:

```
event: eos
data: {"run_id": 7, "final_status": "completed", "exit_code": 0, "outcome": "cli_ok"}
```

Antes del `eos` se drenan los eventos pendientes (por si alguno aterrizó
entre el snapshot del estado y la comprobación de terminalidad), así
ningún `run_event` se pierde.

**Comportamiento runs terminales vs vivos:**

- **Terminal** (run ya `completed|failed|cancelled`): emite los
  históricos + `eos` en un solo pase, sin polling.
- **Vivo** (`running`): emite los históricos, luego tail-polls cada
  200 ms (`await asyncio.sleep(0.2)`, no busy-loop) leyendo
  `WHERE id > last_emitted_id ORDER BY id ASC`. Cierra con `eos`
  cuando el estado transiciona a terminal.

**Heartbeat:** cada ~15 s (75 iteraciones del tail × 200 ms) emite
`: heartbeat\n\n` — comentario SSE ignorado por `EventSource` pero
mantiene el keep-alive vivo a través de proxies.

**Sessions SQLAlchemy.** El proyecto usa `Session` sincrono; el generator
async no mantiene una sesión abierta. Cada poll abre una sesión
corta-vida vía `_open_session(request)` (honra
`app.dependency_overrides`, así los tests inyectan la DB in-memory) y la
cierra inmediatamente. Las queries corren bajo `asyncio.to_thread` para
no bloquear el event loop.

**Orden monotónico.** El tail usa `id > last_id` en lugar de `created_at`
para garantizar orden estable aunque dos eventos compartan timestamp
(SQLite con granularidad de segundo).

**404.** Si `run_id` no existe, la respuesta es `404` JSON
(`{"detail": "Run not found"}`) **antes** de iniciar el stream — el
cliente nunca ve un `200` con SSE vacío.

**Headers:** `Content-Type: text/event-stream`, `Cache-Control:
no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no` (hint a
nginx; inofensivo si no hay proxy delante).

**Límites conocidos** (aceptados por el MVP):

- **Sin paginación.** El histórico completo se emite antes del tail;
  para runs de miles de eventos puede tardar. Follow-up si duele.
- **Sin cancel desde UI.** Solo se observa; cancelar runs vivos
  requiere protocolo adapter↔executor que no existe todavía.
- **Sin resume / `waiting_input`.** Clarification round-trip es
  Semana 5.
- **Client disconnect.** Se comprueba `request.is_disconnected()` en
  cada iteración del tail; en el pase histórico inicial el runtime
  cerrará el task cuando el cliente desconecte.

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
`app/executor/git_workspace.py`: **cada task corre en su propia rama
git**, aislando los cambios de Niwa de los del usuario.

**Branch name** — `niwa/task-<task.id>-<slug>`, con slug puro
(`build_branch_name(task)`): lowercase, `[^a-z0-9]+ → -`, strip `-`
inicial/final, truncar a 30, fallback `untitled` si queda vacío. El
brief trae un ejemplo con slug de 25 chars; la regla (30) es la fuente
de verdad, la implementación aplica 30.

**Invariantes** — el path debe ser un repo git
(`git rev-parse --is-inside-work-tree`) con working tree limpio
(`git status --porcelain` vacío). Sin stash automático: el usuario es
responsable de dejar el repo limpio. Si la rama ya existe (reintento),
se hace `git checkout` sin reset — los commits previos se preservan.

**Flujo en `run_adapter`** — crea `Run` + `started`, llama
`prepare_task_branch`. En éxito persiste `task.branch_name` y spawnea
el adapter. En `GitWorkspaceError` escribe `RunEvent(error,
reason="git_setup_failed: ...")`, finaliza con
`outcome='git_setup_failed'`, `exit_code=None`, y **no invoca al
adapter**. Outcomes posibles para `Run`: `cli_ok` /
`cli_nonzero_exit` / `cli_not_found` / `timeout` /
`adapter_exception` / `git_setup_failed`.

**Fuera de scope** — no commit, no push, no PR, no GC de ramas. HEAD
detached y submódulos: aceptable para MVP. Sin protección contra
carrera usuario↔executor en la misma working tree (SPEC §2 asume uso
monousuario).

**Tests** — `tests/test_git_workspace.py` (5 cases) + fixture
`git_project(tmp_path)` en `conftest.py` (repo con commit seed +
`commit.gpgsign=false` local, algunos sandboxes fuerzan gpg) +
`test_executor.py::test_runs_fail_on_git_setup_error` para el outcome
end-to-end. `test_adapter.py` y `test_runs_api.py` migrados a
`git_project`.

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

`/system` llega en PRs posteriores (SPEC §7). El detalle de tarea
(`/projects/:slug/tasks/:id`) se añade en PR-V1-10 y se documenta más
abajo.

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

### Task detail + stream (PR-V1-10)

Ruta `/projects/:slug/tasks/:id` (SPEC §7). Archivos:

- `routes/TaskDetailRoute.tsx` — lee `:id` con `useParams`, parsea a
  número y delega en `TaskDetail`. Invalidos renderizan alerta inline.
- `features/tasks/TaskDetail.tsx` — compone: título (tachado si
  `cancelled`), badge de estado, `branch_name` en `<Code>`, PR link,
  timestamps, descripción, y `TaskEventStream` alimentado por el run
  más reciente. Detecta 404 leyendo `ApiError.status` y muestra "Task
  no encontrada".
- `features/tasks/TaskEventStream.tsx` — hook custom `useEventStream
  (runId)` que abre `new EventSource("/api/runs/:runId/events")`,
  suscribe listeners a los tipos conocidos (`assistant`, `user`,
  `system`, `tool_use`, `tool_result`, `result`, `message`,
  `started`, `completed`, `failed`, `cancelled`, `error`, `unknown`)
  más `eos`, y llama `.close()` explícitamente al recibir `eos` para
  cancelar el auto-reconnect de SSE. Cleanup del `useEffect` cierra
  la conexión al unmount (StrictMode-safe: el doble mount en dev no
  abre dos streams porque cada efecto obtiene su propia instancia y
  la cleanup la cierra). Cada evento es una fila con badge
  `event_type` + hora `HH:MM:SS` + botón "ver payload" que colapsa
  `<Code block>{JSON.stringify}</Code>`. Cuando llega `eos`, banner
  "Run <final_status>" con color por `RunStatus` + exit code +
  outcome. Runs con >1 k eventos no están virtualizados; follow-up
  si aparece.
- `features/tasks/api.ts::useTask(id)` — `GET /api/tasks/{id}`.
  `useLatestRun(taskId)` — `GET /api/tasks/{id}/runs`, devuelve el
  último (o `null` si la lista está vacía → "Run no iniciado").
- `TaskList` es clicable: `<Table.Tr onClick={navigate(...)}>` y el
  icono delete hace `stopPropagation` en su handler para no disparar
  la navegación.

Types en `src/api.ts`: `Run`, `RunStatus`, `RunEvent`, `EosPayload`.
Mirror 1:1 de `backend/app/schemas/run.py` y del payload que
`format_sse_event`/`format_sse_eos` escriben.

**Mock de `EventSource` en tests.** jsdom no lo implementa. En cada
test que lo necesite, `vi.stubGlobal("EventSource", MockEventSource)`
dentro de `beforeEach` + `vi.unstubAllGlobals()` en `afterEach`, no
global vía `setup.ts`. `MockEventSource` es una clase JS mínima con
`addEventListener`/`removeEventListener`/`close` + un helper síncrono
`_emit(eventType, data)` que dispara un `MessageEvent` al listener
registrado. Los tests (`TaskEventStream.test.tsx`) verifican:
renderizado de 3 eventos históricos y cierre explícito al recibir
`eos` con ignorado de emisiones posteriores.

### Tests frontend (actualizado)

Vitest (jsdom). `tests/setup.ts` añade el polyfill de `matchMedia` que
Mantine necesita. `tests/renderWithProviders.tsx` monta
`MantineProvider` + `QueryClientProvider` (retry=false) +
`MemoryRouter`. El mock de `fetch` se hace con `vi.stubGlobal` — Vitest
no pasa por el proxy.

Suite actual (6 casos, 6 passed):

- `ProjectList.test.tsx` — empty state y render de tarjetas.
- `TaskCreateModal.test.tsx` — botón submit deshabilitado con título
  vacío; submit válido llama `POST /api/projects/:slug/tasks` con el
  payload esperado y dispara `onClose`.
- `TaskEventStream.test.tsx` — eventos históricos via `MockEventSource`
  se pintan en la timeline; al recibir `eos` el banner muestra el
  estado final, el mock queda cerrado y emisiones posteriores no
  añaden filas.

### Proxy Vite → backend

`vite.config.ts` declara `server.proxy['/api'] → http://127.0.0.1:8000`.
Así evitamos abrir CORS en FastAPI: el backend mantiene `127.0.0.1` sin
CORS (SPEC §2 — binding local) y el frontend usa rutas relativas
`/api/...` que el dev server tunela.

## Próximos PRs (SPEC §9)

- PR-V1-08: ejecución aislada en rama git por task. Crear/chequear
  `niwa/<task_id>-<slug>`, sandboxear el CLI en ella, post-run con
  diff + commit + push + PR. El adapter actual queda intacto.
- PR-V1-11+: verificación post-run (exit code + artefactos + tests del
  proyecto), triaje planner, modo safe con PR manual (Semana 3 del
  SPEC). El feedback de aprobación humana en UI y el clarification
  round-trip llegan en Semana 5.

Ver `v1/docs/plans/` para los briefs conforme se escriben.
