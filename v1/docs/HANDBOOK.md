# Niwa v1 — Handbook

Guía operativa y arquitectural del código dentro de `v1/`. Se actualiza
en cada PR que añade/quita módulo backend, feature frontend, tabla DB o
cambia el pipeline. El SPEC vive en `v1/docs/SPEC.md` — este documento
es el "cómo" práctico, no el "qué" del producto.

## Layout actual (tras PR-V1-11c)

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
│   │   ├── verification/       # evidence-based run verifier (PR-V1-11a/11b/11c)
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

### Permissions model (PR-V1-20)

`DEFAULT_ARGS` incluye `--dangerously-skip-permissions` de forma
incondicional desde PR-V1-20. El CLI de Claude en modo headless
(`-p --output-format stream-json`) pide aprobación interactiva en
cada `Write`/`Edit`/`Bash`/`MultiEdit`, pero el canal stream-json no
tiene por dónde enviarla, así que sin el flag todo `tool_use` se
auto-deniega y la task termina `verification_failed` con
`error_code=no_artifacts` (bug observado en el smoke real del
2026-04-22). El flag no es configurable — es siempre activo, tanto
en el adapter del executor como en el que `triage.triage_task`
spawnea.

La seguridad del modelo vive *fuera* del adapter: cada task corre en
una rama aislada `niwa/task-N-<slug>` (PR-V1-08), con guard de tree
limpio antes de arrancar, y la diferencia real entre modos vive en
`finalize.py` — `autonomy_mode="safe"` abre PR para revisión humana
(PR-V1-13), `"dangerous"` auto-mergea con `gh pr merge --squash`
(PR-V1-16). `autonomy_mode` sigue controlando **solo** ese gate de
post-finalize, nunca los permisos del CLI. Ejecutar sin permisos
dentro del workspace aislado es coherente con ese diseño, y cualquier
canal de aprobación interactivo queda fuera del MVP.

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

**Branch base (PR-V1-24)** — para una **rama nueva**, el módulo hace
`git checkout <default>` *antes* del `git checkout -b`, de modo que la
task siempre parte limpia desde la default branch del repo y no hereda
commits de ramas hermanas de Niwa. La default branch se resuelve por
`_detect_default_branch(local_path)` en este orden: `git symbolic-ref
refs/remotes/origin/HEAD` → `refs/heads/main` → `refs/heads/master` →
primera rama listada por `git branch --format=%(refname:short)` →
`GitWorkspaceError("no default branch detected")`. La rama
**existente** mantiene su estado previo (idempotencia): solo se hace
`git checkout <branch>` sin tocar la default.

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

## Verification core (PR-V1-11a / extendido en 11b / completado en 11c)

Implementación del contrato **evidence-based** del SPEC §5. Un run ya
no se marca `done` solo porque el CLI devolvió `exit 0`: pasa por un
verifier que corre los chequeos E1..E5 en orden y deja la evidencia
serializada en `run.verification_json`.

**Estado actual tras 11c:** E1 + E2 + E3 + E4 + E5 son reales. El
contrato §5 del SPEC queda cerrado: si un run llega a `verified` es
que el adapter salió limpio, el stream terminó bien, hay artefactos
en cwd, nada se escribió fuera, y los tests del proyecto (si existen)
pasaron. La forma del `VerificationResult` y la integración en el
executor no cambiaron entre 11a → 11c — sólo se rellenan slots del
`evidence`.

### Módulo `app/verification/`

- `models.py` — `@dataclass(frozen=True) VerificationResult(passed,
  outcome, error_code, evidence)`. Evidence es JSON-serializable; la
  owning invariant vive en el orquestador.
- `stream.py` — E2. `check_stream_termination(events, *, evidence=None)
  -> (error_code, pending_question)`. Ignora lifecycle
  (`started`/`completed`/`failed`/`error`). PR-V1-21 reescribe la
  lógica: el Claude CLI real **siempre** emite un `result` al final,
  así que no basta con mirar el último evento semántico. PR-V1-21b
  añade dos señales estructurales por delante del fallback de texto
  para cubrir casos donde el texto libre miente (imperativo al final,
  `AskUserQuestion` tool nativo denegado por la CLI). Orden de
  evaluación:
    * **Señal 1 — `AskUserQuestion` tool_use (primaria).** Escanea
      todos los eventos buscando bloques `tool_use` con
      `name=="AskUserQuestion"` tanto top-level (shape legacy / fake
      CLI) como embebidos en `assistant.message.content[]` (shape CLI
      real). Devuelve `("needs_input", questions[0].question)`. Si
      `evidence` dict viene kwarg y el tool_use trae `options`, los
      deja en `evidence["ask_user_question_options"]` para que
      `verify_run` los persista en `run.verification_json`.
    * **Señal 2 — `permission_denials` (secundaria).** Último evento
      `result` con `permission_denials[].tool_name=="AskUserQuestion"`
      también es needs_input determinista. Cubre el caso donde la CLI
      denegó el tool antes de emitirlo como evento.
    * **Señal 3 — fallback heurístico de texto.** Walk-back al último
      `assistant`. Sin eventos semánticos o sin ningún `assistant` →
      `("empty_stream", None)`. Último `assistant` sin texto (solo
      `tool_use` blocks) → `("tool_use_incomplete", None)`. Texto
      que acaba en `?` / `?` → `("needs_input", text)` (PR-V1-19 lo
      aparca en `waiting_input`). Texto que NO acaba en `?` pero
      algún párrafo (split `\n\n`) sí → también `needs_input` (caza
      cierres tipo "Let me know which direction you'd like." después
      de listar preguntas numeradas). Otro caso → `(None, None)`.
- `artifacts.py` — E3+E4 (PR-V1-11b).
  `check_artifacts_in_cwd(cwd, evidence)` pre-valida que la cwd exista
  (si no → `error_code="cwd_missing"` fail duro) y después shellea
  `git status --porcelain`; ≥1 línea → pasa.
  `check_no_artifacts_outside_cwd(session, run, cwd, evidence)` replay
  `run_events` inspeccionando **ambos** formatos de `tool_use` que
  emite Claude: top-level `event_type="tool_use"` (legacy / fake CLI)
  y bloques embedded en `event_type="assistant"` →
  `payload.message.content[]` con `type=="tool_use"` (la forma real
  del CLI tras `FIX-20260420` en v0.2). Filtra `name ∈ {Write, Edit,
  MultiEdit, NotebookEdit}` y chequea que todo `file_path` absoluto
  sea subpath del `cwd.resolve()`.
- `core.py` — orquestador `verify_run(session, run, task, project,
  cwd, *, adapter_outcome, exit_code)`. Corre E1 → E2 → E3 → E4 → E5
  y cortocircuita al primer fallo. El timeout de E5 está hardcoded en
  `_TESTS_TIMEOUT_S = 300` (follow-up: env var
  `NIWA_VERIFY_TESTS_TIMEOUT`).
- `tests_runner.py` — E5 (PR-V1-11c). `detect_test_runner(cwd,
  project) -> TestRunnerChoice | None` + `run_project_tests(choice,
  *, timeout=300) -> TestRunResult`.
- `__init__.py` — re-exports `verify_run` + `VerificationResult`.

### E1 — exit code

- `adapter_outcome == "cli_ok"` + `exit_code == 0` → OK.
- `adapter_outcome == "cli_nonzero_exit"` → `error_code="exit_nonzero"`.
- `cli_not_found`/`timeout`/`adapter_exception` → bypass del verifier
  (ver siguiente sección).

### Integración en el executor

`executor/core.py::run_adapter` llama `verify_run` **entre**
`adapter.wait()` y `_finalize` **solo cuando** el adapter reportó
`cli_ok`. Fallos previos (`cli_nonzero_exit`, `cli_not_found`,
`timeout`, `adapter_exception`, `git_setup_failed`) propagan su
outcome sin tocar el verifier — la evidencia sería
contradictoria ("verificó algo que no se ejecutó").

`_finalize` acepta ahora `error_code: str | None` (kwarg). Cuando
no-None, escribe un `TaskEvent(kind="verification",
payload_json={"error_code": ..., "outcome": ...})` en la misma
transacción que el `status_changed`.

### Outcomes y mapeo a `run.status`

| adapter_outcome        | verifier                   | run.outcome            | run.status  | task.status |
|------------------------|----------------------------|------------------------|-------------|-------------|
| `cli_ok` + E1..E5 OK   | pass                       | `verified`             | `completed` | `done`      |
| `cli_ok` + E1 fail     | E1                         | `verification_failed`  | `failed`    | `failed`    |
| `cli_ok` + E2 fail     | E2                         | `verification_failed`  | `failed`    | `failed`    |
| `cli_ok` + E3 fail     | E3                         | `verification_failed`  | `failed`    | `failed`    |
| `cli_ok` + E4 fail     | E4                         | `verification_failed`  | `failed`    | `failed`    |
| `cli_ok` + E5 fail     | E5                         | `verification_failed`  | `failed`    | `failed`    |
| `cli_nonzero_exit`     | bypass                     | `cli_nonzero_exit`     | `failed`    | `failed`    |
| `cli_not_found`        | bypass                     | `cli_not_found`        | `failed`    | `failed`    |
| `timeout`              | bypass                     | `timeout`              | `failed`    | `failed`    |
| `adapter_exception`    | bypass                     | `adapter_exception`    | `failed`    | `failed`    |
| (pre-adapter)          | bypass                     | `git_setup_failed`     | `failed`    | `failed`    |

Éxito es **solo** `outcome == "verified"`. Cualquier otro valor falla
el run y la task.

### error_codes (vocabulario actual)

- E1: `exit_nonzero`, `adapter_failure` (stub — 11a reserva el código;
  el bypass del verifier hace que hoy no se emita).
- E2: `empty_stream`, `tool_use_incomplete`, `question_unanswered`.
- E3: `no_artifacts`, `cwd_missing` (la cwd del run no existe —
  normalmente bug del executor/operator, no se skipea).
- E4: `artifacts_outside_cwd`.
- E5: `tests_failed` (exit ≠ 0), `tests_timeout` (>300 s sin devolver
  control), `tests_runner_missing` (el binario resuelto — `make`,
  `npm`, `sys.executable` — no existe/no es ejecutable en el host).
  Skip vacío (no hay runner detectado) pasa E5 con
  `evidence.test_reason` = `"no_test_script_detected"` |
  `"kind_script"`.

### Evidence shape (estable)

```json
{
  "adapter_outcome": "cli_ok",
  "exit_code": 0,
  "exit_ok": true,
  "significant_event_count": 3,
  "stream_terminated_cleanly": true,
  "git_available": true,
  "artifacts_count": 2,
  "artifacts_outside_cwd": false,
  "tool_use_writes_scanned": 1,
  "tool_use_writes_absolute": 0,
  "tests_ran": true,
  "test_tool": "pytest",
  "test_exit_code": 0,
  "test_duration_s": 3.21,
  "test_output_tail": "... tail of stdout+stderr, ≤4 KB ..."
}
```

Si E5 se skipea (no runner detectado o `kind=script`): `tests_ran:
false` + `test_reason: "no_test_script_detected" | "kind_script"` en
lugar de los campos `test_*`. Ante fallo incluye también `error_code`:
E4 añade `offending_paths: ["/tmp/leak.txt"]` con el primer offender;
E3 deja `artifacts_count: 0`; E5 mantiene `test_tool` /
`test_exit_code` / `test_output_tail` para diagnóstico. PR-V1-21b
añade `ask_user_question_options: [{label, description}, ...]` cuando
la señal 1 de E2 dispara con opciones estructuradas — hoy la UI sigue
pintando Textarea libre (follow-up para renderizarlas como botones).

### Tests

- `tests/verification/test_stream.py` — 12 casos unitarios del E2
  analyzer: los 4 de PR-V1-11a (result/success, question trailing,
  tool_use trailing, empty stream), 3 de PR-V1-21 (result-after-
  assistant-question, answer-after-assistant, plumbing-only) y 5 de
  PR-V1-21b (AskUserQuestion tool_use, permission_denials,
  imperative-closing paragraph scan, Spanish ¿?, y el false-negative
  controlado de `?` dentro de inline-code).
- `tests/verification/test_artifacts.py` — 6 casos unitarios de E3+E4
  (dirty cwd pasa, clean cwd falla `no_artifacts`, path absoluto fuera
  top-level `tool_use` falla `artifacts_outside_cwd`, cwd no-git skip
  graceful, cwd inexistente falla `cwd_missing`, `tool_use` embedded
  en `assistant.message.content[]` con path fuera falla
  `artifacts_outside_cwd` — regresión del blocker del codex review).
- `tests/test_verification_integration.py` — 3 casos E2E: happy con
  `FAKE_CLAUDE_TOUCH` + stream `result/success` → `verified`; sad con
  assistant trailing `?` → `verification_failed` +
  `TaskEvent(kind='verification')`; sad con `tool_use` Write a
  `/tmp/...` → `verification_failed` con
  `error_code="artifacts_outside_cwd"`.
- Legacy migrado: `test_adapter.py`, `test_executor.py`,
  `test_runs_api.py` — asserts que miraban el outcome final del Run
  pasan de `cli_ok` a `verified`. Los happy-path ahora necesitan
  `FAKE_CLAUDE_TOUCH` (una vez por run; `{pid}` substituido por el
  pid del fake) para que E3 vea dirty tree. El
  `test_process_pending_multiple_tasks` usa un `git_project` por
  task (no comparte el fixture global) porque una vez que E3 corre
  `git status --porcelain`, el árbol sucio de la 1ª task rompería
  `prepare_task_branch` en la 2ª. Los que inspeccionan
  `adapter.outcome` (interna) **no** cambian: siguen siendo `cli_ok`
  porque el adapter lo escribe antes del verify.
- Fake CLI (de 11a): env `FAKE_CLAUDE_TOUCH` (lista separada por `:`,
  substituye `{pid}`) para que el fake escriba artefactos durante la
  ejecución.

### Tests del módulo (tras 11c)

- `tests/verification/test_tests_runner.py` — 3 casos: `npm test`
  passes (con skip graceful si `npm` no está en el sandbox),
  pytest failure (detect+run sobre `pyproject.toml` + `test_dummy.py`
  assert False), no test script detected (`tmp_path` vacío +
  `kind="library"` → `detect_test_runner` devuelve `None`).

## Verification artifacts (PR-V1-11b)

### Diseño E3 — `check_artifacts_in_cwd`

Pre-check: si la cwd no existe como directorio, **fail duro** con
`error_code="cwd_missing"` + `evidence.cwd_exists=False`. El
`FileNotFoundError` de `subprocess.run` es ambiguo (cubre tanto "git
no instalado" como "cwd no existe"), así que sin el pre-check un cwd
roto se confundía con un skip graceful y pasaba vacuamente. Un cwd
inexistente siempre apunta a bug del executor/operator.

Si la cwd existe: un único `subprocess.run(["git", "status",
"--porcelain"], cwd=cwd, check=True, capture_output=True, text=True)`
sobre la cwd del adapter (= `project.local_path`, ya verificada como
repo limpio por el workspace prep en 11-08). Contamos líneas no
vacías; `≥1` → pasa con `evidence.artifacts_count = N`. `0` →
`error_code="no_artifacts"`.

Si el subprocess falla con `fatal: not a git repository` (o `git` no
está en PATH), **skip graceful**: `evidence.git_available = False` y
devolvemos `True` sin emitir `error_code`. Esto evita romper runs en
proyectos `kind=script` que aún no estén versionados. 11c usará ese
flag para decidir si puede asumir repo git al chequear E5.

### Diseño E4 — `check_no_artifacts_outside_cwd`

Replay de los `RunEvent` del run, ordenados por `id`. El helper
interno `_iter_tool_use_payloads(session, run)` produce payloads
desde **dos orígenes**:

- **Top-level**: filas con `event_type == "tool_use"` — la forma
  legacy que emiten `fake_claude.py` y algunos tests unitarios.
  Yield directo del `payload`.
- **Embedded**: filas con `event_type == "assistant"` cuyo
  `payload.message.content` es una lista; para cada bloque con
  `type == "tool_use"` yield del propio bloque. Este es el formato
  **canónico** que emite el CLI real de Claude, documentado en v0.2
  `FIX-20260420` (`niwa-app/backend/backend_adapters/claude_code.py`).
  Omitir este camino era el bug que codex marcó como blocker en el
  review de 11b: en producción E4 no veía ninguna escritura y pasaba
  vacuamente.

Para cada payload (venga del origen que venga), misma lógica:

1. Filtra `payload.name ∈ {Write, Edit, MultiEdit, NotebookEdit}`.
   `Bash` queda fuera — ver "known limitations" abajo.
2. Extrae `file_path` de `payload.input.file_path`. Fallback para
   `NotebookEdit`: `input.path` o `input.notebook_path`.
3. Si `file_path` es relativo → se asume relativo a la cwd del
   adapter → acepta.
4. Si absoluto: `Path(file_path).resolve().relative_to(cwd.resolve())`.
   Raises `ValueError` → fail `artifacts_outside_cwd`,
   `evidence.offending_paths = [file_path]` (primer offender, raw sin
   resolver para que coincida con el payload del stream).

Contadores en evidence: `tool_use_writes_scanned` (todos los writes
candidatos de ambos orígenes combinados), `tool_use_writes_absolute`
(sólo los absolutos).

### Known limitations (aceptadas, MVP)

- **`Bash` tool_use**: no se detectan escrituras vía shell. Parsear
  shell arbitrario es overkill para el MVP y fácilmente evadible con
  `sh -c`. 11c o posterior podrá añadir snapshot hash del cwd si
  resulta necesario en la práctica.
- **Symlinks**: `Path.resolve()` los sigue. Si la cwd es un symlink
  apuntando fuera de su parent, o el CLI escribe a un symlink que
  apunta fuera del cwd, el juicio final depende del resolve. No
  reintentamos con lógica especial.
- **Paths relativos a raíces ajenas (`~`, `$HOME`)**: `Path.is_absolute`
  los reporta como no absolutos, así que los aceptamos. Claude Code
  emite paths relativos a la cwd que le pasamos, así que esto sólo
  afectaría si el adapter futuro se saltara esa convención.
- **Submodules en `git status --porcelain`**: cada submódulo cuenta
  como una línea. Aceptable para "existen artefactos".
- **Commit futuro**: si algún día el finalize commitea automáticamente,
  el árbol quedaría limpio y E3 fallaría. Hoy el adapter no commitea
  — cuando esto cambie, E3 deberá mirar también
  `git log HEAD_original..HEAD`. Documentado para 11c+.

Ambos reemplazan los placeholders con valores reales y añaden nuevos
`error_code` sin modificar la forma de `VerificationResult` ni la
integración en el executor.

## Verification tests runner (PR-V1-11c)

E5 cierra el capítulo §5 del SPEC: **si el proyecto tiene tests, se
corren y deben pasar antes de marcar el run como `verified`**. Vive
en `app/verification/tests_runner.py` y lo invoca `verify_run` sólo
después de que E1..E4 hayan pasado.

### Detectores — orden y razones de skip

`detect_test_runner(cwd, project) -> TestRunnerChoice | None`
resuelve en este orden:

1. `project.kind == "script"` → `None` (skip por diseño; ad-hoc
   scripts no llevan suite). El orquestador setea
   `evidence.test_reason = "kind_script"`.
2. `cwd/Makefile` con regla `^test\s*:(?!=)` (regex sobre el fichero,
   sin invocar `make`; la lookahead descarta variable-assignments tipo
   `test := foo`) → `TestRunnerChoice(cmd=["make","test","-s"],
   tool="make", cwd=...)`.
3. `cwd/package.json` con `scripts.test` no vacío (parse JSON) →
   `cmd=["npm","test","--silent"], tool="npm"`.
4. `cwd/pyproject.toml` (parse con `tomllib`, stdlib 3.11+) con
   `[tool.pytest*]` o `pytest` dentro de
   `[project.optional-dependencies].test` →
   `cmd=[sys.executable,"-m","pytest","-q"], tool="pytest"`
   (usamos `sys.executable` y no la cadena `"python"`: hosts minimal /
   Debian modernos sólo traen `python3`).
5. Ninguno → `None`; orquestador setea
   `evidence.test_reason = "no_test_script_detected"`.

Prioridad Makefile > npm > pytest: si un repo lleva los tres (poco
común pero posible), Makefile gana porque suele ser el entrypoint
consolidado del proyecto.

### Ejecución y timeout

`run_project_tests(choice, *, timeout=300) -> TestRunResult` envuelve
`subprocess.run(..., capture_output=True, text=True, timeout=300)`:

- Éxito (`exit_code == 0`) → `passed=True`; E5 pasa.
- Exit no cero → `passed=False`, orquestador devuelve
  `error_code="tests_failed"`.
- `TimeoutExpired` → `timed_out=True`, `exit_code=None`; orquestador
  devuelve `error_code="tests_timeout"`. `subprocess.run` ya mata el
  proceso. Capturamos el stdout/stderr parcial de la excepción para
  el tail.
- `FileNotFoundError` / `PermissionError` / `OSError` al lanzar el
  proceso (binario del runner ausente) → `passed=False`,
  `exit_code=None`, `timed_out=False`, `output_tail` con
  `"<ExceptionType>: <msg>"`. El orquestador lo mapea a
  `error_code="tests_runner_missing"` — distinto de `tests_failed`
  para que el operador sepa que el problema es la toolchain, no los
  tests. Sin esta captura la excepción escapaba `verify_run` y dejaba
  el run wedged en `running`.

Timeout **hardcoded** a 300 s por ahora. Follow-up:
`NIWA_VERIFY_TESTS_TIMEOUT` env var — documentado como riesgo del
brief 11c.

### `output_tail`

Los últimos 4 KB de `stdout + stderr` concatenados se guardan en
`evidence.test_output_tail`. Suficiente para reconocer qué test falló
(pytest imprime el summary al final; jest/vitest idem) sin inflar la
DB. No parseamos salida para extraer "test X failed" — el brief lo
descarta como over-engineering para el MVP.

### Known limitations (aceptadas)

- **`npm install` / `pip install` previos**: E5 no instala
  dependencias. Si el proyecto las necesita y faltan, el subprocess
  falla y el run queda `tests_failed` con el ImportError/stacktrace
  en `test_output_tail`. El usuario debe tener el proyecto listo
  antes de encolar tasks — regla operativa, no bug.
- **Suite grande**: 300 s es arbitrario. Un proyecto con suite lenta
  hoy falla con `tests_timeout`. Env var `NIWA_VERIFY_TESTS_TIMEOUT`
  queda como follow-up explícito.
- **Sólo Makefile / npm / pytest**: Ruby, Go, Rust, etc. son
  follow-up. `detect_test_runner` devuelve `None` y E5 pasa vacuo.
  Más detectores se añaden sin tocar el orquestador — sólo el orden
  de reglas en `detect_test_runner`.
- **Una sola ejecución por run**: todos los tests o nada. Subset
  filtering (`-k`, `--only-affected`) queda fuera del MVP.
- **Sin streaming a la UI**: el stdout del subprocess se captura
  entero antes de devolver. Tests largos no muestran progreso en
  vivo. Aceptable dado el cap de 300 s.
- **`npm test --silent`**: el flag reduce ruido de npm pero no del
  test runner que invoque (p. ej. vitest). El tail de 4 KB basta.

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

## Triage module (PR-V1-12a)

Módulo plano `app/triage.py` con una sola responsabilidad: decidir
binariamente si una task se ejecuta directa o se parte en subtasks
(SPEC §1, paso 1). Una llamada LLM, sin estado, sin DB.

**Contrato público:**

- `TriageDecision` — dataclass frozen con `kind` (`"execute"` |
  `"split"`), `subtasks: list[str]` (vacía sii `kind=="execute"`),
  `rationale: str`, `raw_output: str` (texto del último evento, solo
  debug).
- `TriageError(Exception)` — fallo del adapter, JSON ausente o
  inválido, o shape incoherente (p.ej. `execute` con subtasks).
- `triage_task(project, task) -> TriageDecision` — spawnea
  `ClaudeCodeAdapter` con el prompt, drena `iter_events()` en memoria
  (NO persiste `run_events` — triage no es un Run almacenado), llama
  `wait()`, valida `outcome=="cli_ok" and exit_code==0`, extrae el
  texto del último `result` o `assistant`, parsea y valida shape.
  `adapter.close()` corre siempre en `finally`.

**Prompt** — template en el módulo, se abre con la frase literal
`"You are a triage agent for Niwa."` (keyword fijo; el fake CLI de
12b lo usará para keyword-dispatch). Pide salida JSON en fence
```json``` con tres campos: `decision`, `subtasks`, `rationale`.

**Parser JSON (`_parse_triage_json`)** — dos ramas: primero
`re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)`; si no
matchea, fallback stack-based balanced-match del primer `{...}`
respetando comillas y escapes. Si ninguna rama encuentra objeto,
`TriageError`.

**Integración en el pipeline** — en PR-V1-12b. Tras el merge de 12a
el módulo existe y tiene unit tests verdes, pero **no se invoca desde
`app/executor/`**. Queda como código vivo-sin-uso hasta que 12b lo
enchufe a `run_adapter` (decidiendo antes de spawnear el adapter
principal).

**Tests** — `tests/test_triage.py` (4 cases) mockea
`ClaudeCodeAdapter` via monkeypatch sin extender el fake CLI: un
`_FakeAdapter` con `iter_events`/`wait`/`outcome`/`exit_code`/`close`
scripteados. Cubre execute-en-fence, split-en-fence, JSON pelado sin
fence (rama fallback), y error informativo cuando el CLI responde sin
JSON.

## Triage executor integration (PR-V1-12b)

`executor/core.py → process_pending` ahora llama a `triage_task` para
cada task reclamada, antes de tocar el adapter o el git workspace.
El pipeline por iteración es:

```
claim_next_task → triage_task → {split | execute | triage_failed}
```

**Rama `execute`** — `decision.kind == "execute"`: la task sigue el
flujo existente (`run_adapter`, que contiene `prepare_task_branch` +
spawn del CLI + `verify_run`). Ningún cambio de estado extra.

**Rama `split`** — `decision.kind == "split"`: `_apply_split(session,
task, decision)` crea una `Task` por cada `decision.subtasks[i]`
(`parent_task_id=parent.id`, `status="queued"`, `project_id=
parent.project_id`, `description=""`), hace `session.flush()` para
materializar `id`s, marca el parent `done` con `completed_at=now`, y
escribe dos `task_events`:

- `kind="message"` con `payload = {"event":"triage_split",
  "subtask_ids":[...],"rationale":...}`. **Esto es la resolución Opción B**:
  SPEC §3 no incluye `triage_split` en el enum `task_events.kind`, así
  que el marker vive dentro del payload del `message` en lugar de
  requerir migración de schema.
- `kind="status_changed"` con `{"from":"running","to":"done"}`.

No se crea `Run` para el parent — split corta el pipeline antes de
`run_adapter`. Las subtasks quedan `queued` y se drenan en la(s)
siguiente(s) iteración(es) del loop de `process_pending`.

**Rama `triage_failed`** — `triage_task` lanza `TriageError`:
`_finalize_triage_failure` sintetiza un `Run(status="failed",
model="claude-code", outcome="triage_failed", exit_code=None,
started_at=finished_at=now, artifact_root=project.local_path)` y
escribe dos `run_events` (`error` con `{"reason": str(exc)[:500]}`
y `failed` para el lifecycle terminal). La task pasa a `failed` sin
`completed_at`, y se escriben dos `task_events`:
`kind="verification"` (`{"error_code":"triage_failed",
"outcome":"triage_failed"}`) y `kind="status_changed"` (`running`
→ `failed`).

**Riesgo de recursión** — las subtasks entran al queue y pasan por
triage otra vez. Si el LLM vuelve a splitear, se genera un árbol.
Asumido como riesgo conocido del MVP (SPEC §4 no añade contador de
profundidad). En tests, el fake CLI emite el JSON de split solo una
vez por proceso (ver siguiente sección) para poder cerrar el drain.

**Fake CLI keyword-dispatch** — `tests/fixtures/fake_claude_cli.py`
lee el prompt del stdin. Si contiene el literal `"triage agent for
Niwa"`:

- Con `FAKE_CLAUDE_TRIAGE_JSON` seteado y `FAKE_CLAUDE_TRIAGE_MARKER`
  apuntando a un path, la primera llamada emite el JSON scripteado
  envuelto en una fence `` ```json `` y crea el marker. Las siguientes
  emiten el payload neutro (`execute` con subtasks vacío). Esto
  acota la recursión split en el test integration.
- Sin marker, emite `FAKE_CLAUDE_TRIAGE_JSON` (o el default execute)
  en cada llamada.

Cuando el prompt NO contiene el keyword, el fake cae a la ruta
existente (`FAKE_CLAUDE_SCRIPT` + `FAKE_CLAUDE_EXIT` + touches), así
que los tests legacy siguen funcionando sin cambios — salvo los que
rompen el CLI antes de llegar al adapter principal (ej.
`test_runs_fail_on_git_setup_error`, `test_adapter_binary_missing_
fails_fast`): estos reciben la fixture compartida
`stub_triage_execute` de `conftest.py` que patchea
`app.executor.core.triage_task` para devolver un `TriageDecision`
neutro, evitando que el fallo fictício ocurra ya en la fase de
triage.

## Safe mode finalize (PR-V1-13)

Tras `verify_run` aprobar (outcome `verified`), el executor invoca
`finalize_task(session, run, task, project)` (módulo
`v1/backend/app/finalize.py`) **antes** de `_finalize(...,
outcome="verified")`. La función es **best-effort**: nunca lanza; cada
paso fallido queda en `FinalizeResult.commands_skipped` y se loggea a
nivel `warning`/`info`. Si lanza una excepción catastrófica no-
subprocess, el executor la loggea con `logger.exception` y continúa
igualmente con `_finalize` — la task nunca se queda atascada en
`running` por culpa del finalize.

### Pipeline (en orden, cortocircuita en cada paso)

1. **Commit.** `git status --porcelain`; si vacío →
   `commands_skipped=["nothing_to_commit"]`, siguientes pasos saltados.
   Si hay cambios: `git add -A` + `git commit -m "<subject>" -m
   "<body>"`. Los flags **inline** `-c user.email="niwa@localhost" -c
   user.name="Niwa"` evitan depender de config global — una máquina
   fresca produce commit válido sin `git config --global`. Subject
   truncado a 60 chars (`niwa: <title[:60]>`); body = descripción +
   `"\n\nNiwa task #<id>"`.
2. **Push** (solo si commit OK). Skip con `"no_remote"` si
   `project.git_remote is None` o con `"no_branch"` si
   `task.branch_name` está vacío. Si no: `git push -u origin
   <branch_name>` (asume el remote `origin` seteado por el usuario al
   clonar — no se auto-detecta el nombre del remote). Fallo →
   `"push_failed: ... rc=... stderr=..."`.
3. **PR** (solo si push OK). Skip con
   `"gh_missing: run 'gh pr create --head <branch>' ..."` si
   `shutil.which("gh")` devuelve None. Si no: `gh pr create --title
   <title[:70]> --body <body> --head <branch>` con `cwd=local_path`.
   `gh` no se comprueba autenticado previamente — si `gh auth login`
   falta, el comando falla con rc≠0 y caemos al log manual. El base
   branch del PR lo resuelve `gh` automáticamente del remote default.
4. **Captura URL.** `gh pr create` imprime la URL en stdout. Escaneamos
   cada línea y la primera que matchee `^https?://` (case-insensitive)
   se persiste en `task.pr_url` con un `session.commit()` extra. Si
   stdout salió 0 pero no contiene URL → `"gh_pr_create_no_url: ..."`
   en `commands_skipped` y `pr_url=None` (no renderizamos links
   basura).

### `FinalizeResult`

```python
@dataclass(frozen=True)
class FinalizeResult:
    committed: bool
    pushed: bool
    pr_url: str | None
    pr_merged: bool = False            # PR-V1-16: True sólo si dangerous
                                       # mode corrió gh pr merge con rc=0
    commands_skipped: list[str]        # reasons acumulativas
```

### Comportamiento sin `remote` / sin `gh`

- **Sin remote.** Task termina `done`, commit local en la rama
  `niwa/task-<id>-<slug>`, `pr_url=None`. Usuario puede abrir el
  remote a mano y reintentar push.
- **Sin `gh` (pero con remote).** Task termina `done`, push realizado,
  `pr_url=None`, `commands_skipped` trae el comando manual
  (`gh pr create --head ...`) que el usuario puede copiar.
- **`gh pr create` falla** (no autenticado, base mismatch, etc.).
  Task termina `done`, push realizado, `pr_url=None`, stderr
  capturado + comando manual en `commands_skipped`.

### Fuera de scope (PR-V1-13)

- **Autonomy `dangerous` / auto-merge:** añadido en PR-V1-16
  (sección siguiente).
- **UI del `pr_url`:** el detalle de task ya tiene la columna; el
  render del link es follow-up.
- **No hay force-push**, ni amend, ni retries. Carrera con push
  manual del usuario a la misma rama queda no protegida (asumimos
  uso monousuario — MVP).

### Tests

- `tests/test_finalize.py` — 5 casos unit que mockean
  `subprocess.run` vía `monkeypatch`. El helper `_mock_cmd` dispatcha
  por el primer argv token (``git``/``gh``), saltando los ``-c
  key=val`` inline para matchear el subcomando real.
- `tests/test_executor.py::test_process_pending_finalizes_verified_run_with_gh_stub`
  — integration E2E: `finalize_task` monkeypatcheado a un spy que
  escribe `task.pr_url`; verifica que el executor sólo lo invoca
  tras verify passes.

## Dangerous mode (PR-V1-16)

Cierra Semana 4 del SPEC §9: activa el brazo
`autonomy_mode="dangerous"` del SPEC §1/§4 añadiendo un paso 5
opcional a `finalize_task` y un banner rojo en
`/projects/:slug`.

### Flow (paso 5, tras PR creado)

Si y sólo si los tres checks se cumplen tras el paso 4 del safe
mode:

1. `pr_url` no-None (hubo `gh pr create` exitoso con URL válida).
2. `project.autonomy_mode == "dangerous"` (default es `"safe"`;
   `getattr` con fallback por si la columna falta en tests de
   fixture viejos).
3. `shutil.which("gh") is not None`.

Entonces `finalize_task` dispara:

```
gh pr merge <pr_url> --squash --delete-branch
```

con `cwd=project.local_path` y timeout 30 s (el mismo helper
`_run_cmd` que el resto del pipeline).

- `rc == 0` → `FinalizeResult.pr_merged = True`, log
  `"auto-merged PR for task_id=..."` a `niwa.finalize`. El PR queda
  merged y la rama remota borrada.
- `rc != 0` → `pr_merged = False`, entry en `commands_skipped`:
  `"gh_pr_merge_failed: <stderr[:500]> (manual: gh pr merge
  <pr_url> --squash --delete-branch)"`. Task sigue `done`: el
  trabajo está committeado, pusheado y PR creado; sólo el merge
  automático falló.

Si `autonomy_mode == "safe"` → **no-op** sin log; `pr_merged`
queda `False` por default. No se intenta el merge ni se añade
entry a `commands_skipped`. Comportamiento idéntico al previo a
este PR.

### `FinalizeResult.pr_merged`

Campo booleano nuevo con default `False`. Vive sólo en memoria y
logs — **no hay columna DB** para `pr_merged` ni `pr_merged_at`
en `tasks`. El hecho de que el PR esté cerrado se recupera a
posteriori consultando `task.pr_url` contra la API de GitHub; MVP
asume que no lo necesitamos persistido.

### Banner UI

`ProjectDetail.tsx` renderiza encima del título un `Alert` rojo
con `color="red"`, `variant="filled"`, título `"Dangerous mode"`
e icono `IconAlertTriangle`:

> Runs auto-merge PRs without review. Review carefully before
> enabling.

Sólo aparece cuando `project.autonomy_mode === "dangerous"`. El
badge rojo "dangerous" junto al slug sigue visible en cualquier
modo — el banner es la señal *loud*, el badge es recordatorio
silencioso. Ambos coexisten por diseño.

**No hay toggle UI** para cambiar `autonomy_mode` desde el detalle
— se edita vía `PATCH /api/projects/{slug}` o DB directa. Añadir
un toggle exigiría confirm modal + mutation y queda como
follow-up.

### Seguridad — decisiones clave

- **`--squash` hardcoded.** El SPEC no especifica estrategia y MVP
  no expone preferencia por proyecto. Follow-up si el usuario
  pide `--rebase`/`--merge` sería una columna
  `autonomy_merge_strategy`.
- **`--delete-branch` hardcoded.** Cada task usa su propia rama
  `niwa/task-<id>-<slug>`; dejar la rama viva post-merge no tiene
  utilidad y acumula ruido.
- **No hay undo.** Un merge exitoso es irreversible desde Niwa.
  Si verify pasó pero el merge rompe el target branch (conflicto
  con otro PR mergeado entre verify y merge, por ejemplo), la
  responsabilidad es del humano. MVP no comprueba protected
  branches ni status checks.
- **Race con humano.** Si el usuario mergea/cierra el PR a mano
  antes de que llegue finalize, `gh pr merge` devuelve rc≠0 con
  stderr del estilo "pull request already merged"; caemos al
  log sin drama.
- **`gh` missing tras pr_create.** Improbable (lo acabamos de
  invocar) pero defensivo: el check de `shutil.which("gh")` se
  repite por si el binario desapareció.

### Tests

- `tests/test_finalize.py::test_dangerous_mode_runs_gh_pr_merge`
  — dangerous + `gh pr create` OK + `gh pr merge` rc=0 →
  `pr_merged=True`, sin entry de fail, y el argv exacto
  `["gh","pr","merge",<url>,"--squash","--delete-branch"]` se
  verifica contra la lista de calls del mock.
- `tests/test_finalize.py::test_safe_mode_skips_auto_merge` —
  safe + PR creado → `pr_merged=False` y cero calls con prefijo
  `gh pr merge`.
- `tests/test_finalize.py::test_dangerous_mode_merge_failure_logs_manual_command`
  — dangerous + merge rc=1 con stderr → `pr_merged=False`,
  entry `"gh_pr_merge_failed: ..."` que incluye el stderr y la
  flagline `--squash --delete-branch`.
- `frontend/tests/ProjectDetail.test.tsx` — dos casos:
  dangerous muestra el banner ("Dangerous mode" + texto del body),
  safe no lo renderiza. `fetch` se stubbea con `vi.stubGlobal`.

## Bootstrap (PR-V1-14)

`v1/bootstrap.sh` deja la máquina lista para correr Niwa v1 en un
tirón, sin wizard interactivo. SPEC §6 lo declara como canal único
de instalación.

### Flow (en orden)

1. **Preconditions fail-fast.** Al arrancar se loggea
   `checking preconditions: python3 (>=3.11), npm, git` y se
   verifica cada tool con `command -v`. `python3` se chequea además
   con `python3 -c 'import sys; sys.exit(0 if sys.version_info >=
   (3, 11) else 1)'`. Si cualquiera falta el script `exit 1` con
   mensaje legible prefijado `[niwa-bootstrap] ERROR:`.
2. **Layout.** `mkdir -p ${HOME}/.niwa/{logs,data}` (idempotente).
3. **Venv.** `${HOME}/.niwa/venv` creado solo si no existe su
   `bin/python`; `pip install --upgrade pip` siempre.
4. **Backend editable.** `pip install -e v1/backend[dev]` desde el
   venv. Re-run reconcilia deps sin borrar.
5. **Frontend.** `cd v1/frontend && npm install --silent`, saltable
   con `NIWA_BOOTSTRAP_SKIP_NPM=1` (tests usan este skip para no
   gastar CI en npm).
6. **Migrations.** `alembic -x db_url=sqlite:///<HOME>/.niwa/data/niwa-v1.sqlite3 upgrade head`
   desde `v1/backend`. `env.py` (PR-V1-02) consume el `-x db_url`.
7. **Config (preserva).** Si `${HOME}/.niwa/config.toml` existe, se
   deja intacto. Si no, se renderiza desde
   `v1/templates/config.toml.tmpl` sustituyendo `{{CLAUDE_CLI_PATH}}`
   (`command -v claude || echo claude`) y `{{HOME}}` con `sed`.
8. **Service file (write-only).** Según `uname -s`:
   - `Darwin` → `${HOME}/Library/LaunchAgents/com.niwa.executor.plist`
     desde `v1/templates/com.niwa.executor.plist.tmpl`.
   - `Linux` → `${HOME}/.config/systemd/user/niwa-executor.service`
     desde `v1/templates/niwa-executor.service.tmpl`.
   - Otros → `exit 1`.
   Se renderiza con `sed` sustituyendo `{{CLAUDE_CLI_PATH}}`,
   `{{HOME}}`, `{{REPO_DIR}}`, `{{VENV_PYTHON}}`. El fichero se
   sobrescribe en cada run (template siempre fresco). **El script
   NO carga ni arranca el servicio** — `launchctl load` /
   `systemctl --user enable` son trabajo de PR-V1-15 (launcher CLI).
9. **Resumen final** en stdout con paths de `config`, `db`, `venv`,
   `service`, y el comando sugerido para el launcher.

### Templates

Los tres templates viven en `v1/templates/` para evitar heredocs
gigantes en bash:

- `config.toml.tmpl` — defaults de SPEC §2/§6 (claude.cli,
  claude.timeout=1800, db.path, executor.poll_interval_seconds=5).
- `com.niwa.executor.plist.tmpl` — launchd plist con `KeepAlive` y
  `RunAtLoad`, `NIWA_CLAUDE_CLI` + `NIWA_CONFIG_PATH` en
  `EnvironmentVariables`.
- `niwa-executor.service.tmpl` — systemd user unit, `Type=simple`,
  `Restart=on-failure`, `WantedBy=default.target`.

Sustitución con `sed -e "s|PLACEHOLDER|value|g"`: usamos `|` como
delimitador para que los paths con `/` no necesiten escaping.

### Env vars

- `NIWA_BOOTSTRAP_SKIP_NPM=1` — salta `npm install`. Se usa en
  `tests/test_bootstrap.py` para no tirar `npm` en subprocess.
- `HOME` — base de todo lo que escribe el script. Los tests crean
  un `HOME` aislado vía `tmp_path`.

### Tests

`tests/test_bootstrap.py` (5 casos) invoca `bash bootstrap.sh` con
`subprocess.run(..., timeout=300)`:

1. `test_bootstrap_script_is_executable` — sanity: existe y tiene
   bit `+x`.
2. `test_fresh_install_creates_layout_and_config` — HOME vacío →
   venv/python, logs, DB migrada, config sin literales `{{...}}`,
   service file en la ruta de la plataforma (`Darwin` vs `Linux`).
3. `test_rerun_is_idempotent` — dos runs seguidos; el sentinel
   escrito a `config.toml` entre runs sobrevive al segundo; DB
   intacta.
4. `test_missing_python_fails_fast` — `PATH` restringido al dir de
   `bash` → exit code ≠ 0 y la palabra `python` aparece en la
   salida (gracias al log de preconditions).
5. `test_config_substitution_replaces_placeholders` — ni
   `{{CLAUDE_CLI_PATH}}` ni `{{HOME}}` quedan como literal en el
   `config.toml` post-bootstrap.

### Idempotencia

- `venv/`: se crea solo si falta el `bin/python`; `pip install -e`
  reconcilia cada run.
- `config.toml`: jamás se toca si existe (user-editable source of
  truth; SPEC §2 "no config vía UI").
- Service file: se reescribe siempre — template fresco con los
  paths actuales es lo correcto si el repo se ha movido.
- `alembic upgrade head`: no-op si ya estamos en `head`.

### No cargar el servicio

La separación entre "escribir el unit" (PR-V1-14) y "cargarlo +
helper CLI" (PR-V1-15) evita que el bootstrap deje un daemon
corriendo sin que el usuario haya visto primero la UI. PR-V1-15
añade `niwa-executor [start|stop|status]` que abstrae
`launchctl`/`systemctl --user`.

## Executor launcher (PR-V1-15)

`niwa-executor` es el wrapper CLI sobre el service file que
escribió PR-V1-14. Vive en `v1/backend/app/niwa_cli.py`, stdlib
puro (`argparse`, `subprocess`, `pathlib`, `platform`,
`sys`, `os`). Se registra como entry point en
`v1/backend/pyproject.toml`:

```toml
[project.scripts]
niwa-executor = "app.niwa_cli:main"
```

Tras `pip install -e v1/backend` dentro de `~/.niwa/venv` (lo que
hace `bootstrap.sh`), `~/.niwa/venv/bin/niwa-executor` queda en
PATH.

### CLI reference

```
niwa-executor start          # load + start (idempotente)
niwa-executor stop           # stop + unload
niwa-executor restart        # reload del service file
niwa-executor status         # exit code mapeado a estado
niwa-executor logs [--follow] [--lines N]   # tail del log
```

- `--lines`/`-n` default 50.
- `--follow`/`-f` invoca `tail -f`; hereda stdio del padre para
  que `Ctrl-C` mate el tail hijo.

### Dispatch por OS

`platform.system()` decide el backend:

| Subcomando | Darwin | Linux |
|------------|--------|-------|
| `start`    | `launchctl load -w <plist>` | `systemctl --user enable --now niwa-executor.service` |
| `stop`     | `launchctl unload -w <plist>` | `systemctl --user disable --now niwa-executor.service` |
| `restart`  | `launchctl kickstart -k gui/<uid>/com.niwa.executor` | `systemctl --user restart niwa-executor.service` |
| `status`   | `launchctl list com.niwa.executor` | `systemctl --user status niwa-executor.service` |

Exit codes de `status` se propagan tal cual:

- macOS `launchctl list <label>` → 0 si cargado, 113 si no.
- Linux `systemctl --user status` → 0 si active, 3 si inactive.

Otro OS (e.g. `Windows`) → exit 1 con mensaje `Unsupported OS`.

Binario ausente (p. ej. `launchctl` en un Linux) → exit 127 con
`command not found: <tool>`.

### Paths canónicos

- `NIWA_HOME` = `$NIWA_HOME` env (override para tests) o
  `~/.niwa`.
- Log: `$NIWA_HOME/logs/executor.log` — escrito por launchd /
  systemd según el service file. Crece indefinidamente (rotate
  queda follow-up).
- macOS plist: `~/Library/LaunchAgents/com.niwa.executor.plist`,
  label `com.niwa.executor`.
- Linux unit: `niwa-executor.service` bajo
  `~/.config/systemd/user/`.

Si `start`/`restart` corren en macOS y el plist no existe, el CLI
sale 1 con `service file missing at <path>; run v1/bootstrap.sh
first` — la pista concreta para el usuario.

### Arranque al boot/login

Ni el CLI ni `bootstrap.sh` cargan el servicio por sí solos. Una
vez el usuario corre `niwa-executor start`:

- macOS: `launchctl load -w` pone el plist en la queue del user
  launchd; al siguiente login el plist se carga solo porque el
  template declara `RunAtLoad=true` + `KeepAlive`.
- Linux: `systemctl --user enable --now` arranca ya y crea el
  symlink en `default.target.wants/`; en cada login systemd-user
  rehidrata el unit.

Para ejecuciones headless en Linux (ssh sin sesión gráfica), el
usuario necesita `loginctl enable-linger <user>` una vez; si no,
`systemctl --user` falla sin `XDG_RUNTIME_DIR`.

### Re-install tras PR-V1-15

Los usuarios que corrieron `bootstrap.sh` antes de este PR tienen
el paquete `niwa-v1-backend` instalado sin el entry point. Tienen
que re-ejecutar el bootstrap (que hace `pip install -e` sobre un
paquete ya instalado, refrescando metadata) para que
`~/.niwa/venv/bin/niwa-executor` aparezca.

### Known deprecations

- `launchctl load -w` está deprecated en macOS 10.11+ a favor de
  `launchctl bootstrap gui/<uid> <plist>`. El MVP usa `load`
  porque sigue funcionando en todas las versiones target; si Apple
  lo retira en una versión futura, migrar a `bootstrap`/`bootout`
  es un follow-up aislado al dispatcher de `cmd_start`/`cmd_stop`.
- `kickstart -k` requiere macOS 10.10+; asumido como precondición.
- Sin sesión GUI activa, `gui/<uid>/<label>` puede fallar; el
  fallback manual es `niwa-executor stop && niwa-executor start`.

### Tests

`tests/test_niwa_cli.py` (10 casos, cero subprocess reales):

1. `test_start_macos_calls_launchctl_load` — plist presente →
   `launchctl load -w <plist>`.
2. `test_start_linux_calls_systemctl_enable_now` — argv
   completo verificado.
3. `test_start_macos_fails_when_plist_missing` — exit 1 y
   mensaje "service file missing"; nunca llama a subprocess.
4. `test_stop_dispatches_correct_cmd_per_platform` —
   parametrizado Darwin/Linux.
5. `test_status_returns_subcmd_exit_code` — exit 3 del stub se
   propaga.
6. `test_logs_missing_file_returns_1` — log ausente → exit 1
   con mensaje útil.
7. `test_logs_invokes_tail_with_lines` — `--lines 100` → argv
   `["tail", "-n", "100", <path>]`. `--follow` NO testeado para
   evitar `tail -f` colgante.
8. `test_unsupported_os_returns_1` — `platform.system` →
   `"Windows"`.
9. `test_run_captures_file_not_found_returns_127` —
   `subprocess.run` lanza `FileNotFoundError` → exit 127.

Aislamiento: `monkeypatch.setenv("NIWA_HOME", tmp_path)` +
`importlib.reload(app.niwa_cli)` para que las constantes de
módulo vean el env var. `platform.system` y `subprocess.run`
mockeados, never spawning.

## Deploy local (PR-V1-17)

Handler estático en el propio backend FastAPI que sirve el output
de build de cualquier proyecto `kind="web-deployable"`. Cierra el
hito de Semana 5 del SPEC §9 — "deploy a
`localhost:PORT/<slug>`" — sin spawn de procesos, sin reverse
proxy y sin gestión de puertos por proyecto.

### URL y contrato

```
GET /api/deploy/{slug}/              → dist/index.html (SPA entry)
GET /api/deploy/{slug}/{path:path}   → dist/<path>
```

- Resuelve `Project` por `slug` en DB. 404 si no existe o si
  `kind != "web-deployable"` (mismo 404 silencioso para `library`
  y `script`, aunque el repo tenga `dist/`).
- Empty path o directorio → `dist/index.html`.
- File no existente bajo `dist/` → 404.
- Content-Type por extensión vía `FileResponse` (FastAPI). No hay
  gzip, ni cache headers, ni ETag: MVP.

Ruta final bajo el router raíz `api_router` (prefix `/api`), por
consistencia con el resto del backend; el frontend Vite ya
proxea `/api/*`.

### Traversal guard

```python
dist = (Path(project.local_path) / "dist").resolve()
target = (dist / path).resolve() if path else dist / "index.html"
if target.is_dir():
    target = target / "index.html"
try:
    target.resolve().relative_to(dist)
except ValueError:
    raise HTTPException(404, "Not found")
```

- `Path.resolve()` colapsa `..` **y** sigue symlinks. Un symlink
  dentro de `dist/` que apunte fuera del árbol resuelve a ruta
  absoluta externa; `relative_to(dist)` lanza `ValueError` y la
  respuesta es 404 sin leer el file.
- El test de traversal envía `%2E%2E/%2E%2E/secret.txt` codificado
  para que httpx no normalice el `..` antes de llegar a FastAPI.

### Known limitations (aspiracional para v1.1)

- **`project.deploy_port` no se usa.** La columna sigue en schema
  pero el MVP ignora su valor; el servicio queda siempre bajo
  `localhost:<main_port>/api/deploy/<slug>/`. Per-port/subdominio
  se introducirá con Caddy/Cloudflare en v1.1 (SPEC §8, punto 2).
- **No spawn de procesos.** El proyecto no corre su propio server;
  Niwa solo sirve lo que el build dejó en `dist/`.
- **No build automático post-verify.** El usuario/task ejecuta
  `npm run build` (o equivalente) aparte; `finalize.py` **no**
  dispara deploy (el brief lo excluye explícitamente).
- **No reverse proxy** a un daemon del proyecto. Solo static.
- **No auth, no gzip, no cache-control.** Binding local (SPEC §2).
- **No UI del link de deploy.** `ProjectDetail.tsx` podría mostrar
  `http://localhost:<port>/api/deploy/<slug>/` como follow-up.

### Tests

`tests/test_deploy_api.py` (5 casos): index fallback, asset
bajo `dist/assets/`, 404 por slug desconocido, 404 por
`kind=library`, 404 por traversal sin fugar el fichero externo.
Fixture shared `client` + `tmp_path` para montar el árbol
`dist/` por test.

## Readiness (PR-V1-18)

Salud del stack local expuesta en un endpoint read-only y una página
UI. Se invoca manualmente — sin polling — para que el usuario sepa
si falta `gh`, si `claude` no está en PATH, o si la DB no responde
antes de lanzar un task.

### Endpoint

`GET /api/readiness` → `app/api/readiness.py`. Síncrono (FastAPI
lo corre en el threadpool), compone 4 helpers puros de
`app/services/readiness_checks.py`:

- `check_db_via_session(session)` — `SELECT 1` contra la `Session`
  inyectada por el DI graph (`Depends(get_session)`). Usa la misma
  DB que el resto del request: evita crear el fichero SQLite como
  side-effect del health probe y respeta los overrides de tests.
- `check_claude_cli(cli)` — `shutil.which(cli or "claude")`. Solo
  presencia. **No** corre `claude whoami` ni subcomandos (brief
  explícito: hit de red, lento).
- `check_git()` — `subprocess.run(["git", "--version"])` con
  `timeout=5`. Captura `stdout` en `details.version`.
- `check_gh()` — `shutil.which("gh")`. No `gh auth status`
  (también red); si falta, devuelve `details.hint` con el install
  hint para que el frontend no tenga que hardcodear copy.

Cada helper devuelve `(ok: bool, details: dict)` y es best-effort:
si el probe crashea, `ok=False` y `details["error"]` carga el
mensaje. Response Pydantic `ReadinessResponse(db_ok, claude_cli_ok,
git_ok, gh_ok, details)` con `details` anidado.

### Qué no cubre (explícito)

- **No systemd/launchd check.** Lo cubre `niwa-executor status`
  desde PR-V1-15; duplicarlo en readiness complica el check sin
  valor nuevo.
- **No disk free.** Cosmético, follow-up.
- **No auth check** del backend — binding local (SPEC §2).
- **No auth de `gh`/`claude`.** `status` de `gh` requiere red y
  puede tardar; `claude whoami` lo mismo. Readiness queda en
  "hay binario y DB responde".
- **No check del proyecto deployado** `/api/deploy/<slug>/`.
- **No endpoint "reparar".** Read-only estricto.

### Frontend `/system`

`src/routes/SystemRoute.tsx` + hook `useReadiness()`. `useQuery`
**sin** `refetchInterval` — el brief fencea el polling automático
para que la página sea explícita: flicker cero, `git --version` no
se llama en background. Botón "Refresh" invalida la key
`["readiness"]` y dispara refetch.

Tabla Mantine con 4 filas (Database / Claude CLI / git / gh),
badge verde `OK` o rojo `Missing`, y una columna "Details" con
texto derivado del payload: path cuando OK, `hint`/`error`/mensaje
por defecto cuando falla. Ruta `/system` registrada en `App.tsx`.

### Known limitations

- `claude_cli_ok=True` solo prueba presencia del binario, no que
  esté autenticado. Un follow-up podría añadir un modo `deep`.
- `gh` hint es hardcode inglés; i18n queda fuera.
- El botón Refresh se bloquea con `loading={isFetching}` pero no
  impide clicks repetidos si React Query entra en background
  refetch — aceptable para MVP.

### Tests

`tests/test_readiness_api.py` (6 casos): all-ok, `claude` missing,
`gh` missing + hint, `git` excepción capturada, `db` unreachable
(patchea `svc.check_db_via_session` para ejercitar la composición
del endpoint) y un unit test (`test_check_db_via_session_catches_exception`)
que pasa una session mock cuyo `execute` lanza `OperationalError`
para ejercitar la rama `except` real del helper.
Todos mockean `shutil.which` y `subprocess.run` via `monkeypatch`;
ningún subprocess real se spawnea.

`tests/SystemRoute.test.tsx` (2 casos): all-OK rinde 4 badges
verde; `gh_ok=false` con hint rinde "Missing" + el texto del hint.
Mock `fetch` via `vi.stubGlobal` siguiendo el patrón de
`ProjectList.test.tsx`.

## Clarification round-trip (PR-V1-19)

SPEC §1 / §3 / §9 Semana 5. Cierra el ciclo cuando Claude acaba el
stream con una pregunta sin respuesta: la task deja de caer en
`failed` + `error_code=question_unanswered`; en su lugar va a
`waiting_input`, el usuario responde desde la UI y la task vuelve a
`queued` para que el executor la reclame.

### Flujo

1. **Verifier.** `stream.py::check_stream_termination` (E2) devuelve
   ahora `(error_code, pending_question)`. Si el último mensaje
   `assistant` semántico termina en `?`, `error_code="needs_input"` y
   `pending_question=<texto completo concatenado>`. Si no, el contrato
   anterior se mantiene (`"tool_use_incomplete"`, `"empty_stream"`,
   `None`).
2. **`verify_run`.** Propaga `needs_input` como outcome distinto de
   `verification_failed`. `VerificationResult` gana
   `pending_question: str | None = None` (default preserva todos los
   call-sites antiguos). `evidence["outcome"] = "needs_input"` para
   que el snapshot persistido en `verification_json` sea
   autodescriptivo.
3. **Executor `_finalize`.** Tres ramas terminales:
   - `outcome == "verified"` → run `completed`, task `done`.
   - `outcome == "needs_input"` → run `failed` (el adapter no produjo
     output completo), task `waiting_input`,
     `task.pending_question = <text>`. `TaskEvent(kind="status_changed",
     payload={"from":"running","to":"waiting_input"})`.
   - otro → run `failed`, task `failed` (como antes).
4. **Endpoint `POST /api/tasks/{id}/respond`.** Body
   `TaskRespondPayload(response: str)` (`min_length=1, max_length=10_000,
   extra="forbid"`). Handler en `app/api/tasks.py`; lógica en
   `services/tasks.py::respond_to_task`:
   - 404 si la task no existe; 409 si `status != "waiting_input"`;
     422 si el body es inválido (pydantic).
   - Escribe `TaskEvent(kind="message",
     payload={"event":"user_response","text":<response>})` para audit.
   - `task.pending_question = None`, `task.status = "queued"`,
     `TaskEvent(kind="status_changed",
     payload={"from":"waiting_input","to":"queued"})`.
   - Retorna el `TaskRead` actualizado.
5. **Frontend.** `TaskDetail.tsx` renderiza un `<Alert color="yellow"
   title="Niwa necesita tu respuesta">` cuando `task.status ===
   "waiting_input" && task.pending_question`, con el texto de la
   pregunta, un `<Textarea>` controlado por `useState`, y un botón
   "Responder" que dispara `useRespondTask(taskId).mutate(...)`. El
   hook invalida `["task", taskId]` al éxito; la página refresca a
   `queued` sin banner. El botón se deshabilita mientras el textarea
   está vacío o la mutación está pendiente.

### Contrato del endpoint

```
POST /api/tasks/{task_id}/respond
Content-Type: application/json

{ "response": "yes please" }

200 → TaskRead (status=queued, pending_question=null)
404 → { "detail": "task not found" }
409 → { "detail": "Task is not waiting for input" }
422 → pydantic validation error (body vacío / campos extra / >10k)
```

### Known limitation — no composite prompt

El siguiente run del adapter **no** recibe el historial. `_build_prompt`
sigue componiendo el prompt solo con `task.title` + `task.description`;
la respuesta del usuario queda en `task_events` como audit pero el CLI
no la lee. El follow-up real combinará prompt original + pregunta
previa + respuesta del usuario en un `composite prompt`, o llamará a
`claude --resume <session_id>` usando `run.session_handle` (otro
follow-up). Para el MVP esto basta: Claude es consistente entre
corridas si la descripción de la task es clara; si sigue preguntando,
se itera.

### Otros no cubiertos (follow-up)

- No hay resume del CLI (`claude --resume`), así que cada respond
  crea un run nuevo desde cero.
- No hay UI para cancelar el `waiting_input` (p. ej. "convert to
  failed"). Se borra manualmente con `DELETE /api/tasks/:id` si
  hace falta.
- No se soporta multi-turn explícito; cada vez que el adapter acabe
  en `?`, la task vuelve a `waiting_input`. Implícito.
- El adapter sigue marcando `run.status="failed"` en la rama
  `needs_input`. Las métricas de runs felices/fallidos en SPEC §5
  no distinguen todavía entre "task parked" y "task genuinely
  failed"; follow-up si hace falta un dashboard.

### Tests

- `tests/test_tasks_api.py` (+4 casos): respond 200, 409, 404, 422
  (empty body).
- `tests/test_verification_integration.py`: el antiguo
  `test_sad_path_question_unanswered` queda reemplazado por
  `test_stream_ending_in_question_puts_task_in_waiting_input` — las
  aserciones ahora verifican `run.outcome == "needs_input"`,
  `task.status == "waiting_input"`,
  `task.pending_question == <text>` y el `status_changed
  running→waiting_input`.
- `tests/verification/test_stream.py`: los cuatro casos actualizan al
  tuple `(error_code, pending_question)`; el caso de pregunta
  verifica el texto completo propagado.
- `frontend/tests/TaskDetail.test.tsx` (+2 casos): render del banner
  + botón deshabilitado en vacío, y submit con POST capturado.

## Resume via session_handle (PR-V1-22)

Cierra la known limitation que dejó PR-V1-19: el segundo run tras un
`respond` ahora reanuda la sesión de Claude en lugar de arrancar con
prompt fresco.

### Flujo

1. **Adapter.** `ClaudeCodeAdapter` gana la kwarg opcional
   `resume_handle: str | None` y la propiedad `session_id: str | None`.
   - Cuando se pasa `resume_handle`, la argv spawneada añade
     `--resume <handle>`.
   - El primer evento con `type="system"` y `subtype="init"` popula
     `session_id` desde el campo `session_id` del payload. Se lee una
     sola vez (inits posteriores se ignoran) para que el handle
     persistido sea el de la sesión original.
2. **Executor `run_adapter`.** Tras `claim_next_task` y antes de
   spawnear el adapter:
   - `_last_user_response_text(session, task_id)` devuelve el `text`
     del último `TaskEvent(kind="message")` cuyo payload tiene
     `event=="user_response"` o `None` si no existe.
   - `_last_run_session_handle(session, task_id)` devuelve el
     `session_handle` más reciente no-NULL de los runs de esa task.
   - Si **ambos** existen: `resume_handle` y `adapter_prompt` se
     setean con los valores correspondientes (log `info`). Si falta
     el handle (p. ej. primer run murió antes del `system/init`) →
     fallback a `_build_prompt(task)` con `logger.warning`.
   - Tras `adapter.close()`, si `adapter.session_id` no es `None`,
     `run.session_handle = adapter.session_id` y commit. Se persiste
     siempre, incluso en runs fallidos, para no perder el handle que
     habilita el próximo resume.
3. **Limpieza de `pending_question`.** La hace `respond_to_task`
   atómicamente al re-queuear la task desde `waiting_input` — mismo
   commit que el `status_changed` a `queued`. Cuando `run_adapter`
   toma la task, `pending_question` ya es `None`, de modo que
   `_finalize` no lo vuelve a tocar en el path `verified`. Si una
   ronda posterior vuelve a devolver `needs_input`, el branch
   `needs_input` de `_finalize` repopula con la nueva pregunta.
4. **`respond_to_task`.** El payload del `TaskEvent(kind="message")`
   sigue el esquema `{"event":"user_response","text":<response>}`;
   PR-V1-19 lo dejó así y PR-V1-22 lo fija con el test
   `test_respond_writes_normalized_user_response_event`.

### Fallback robusto

El resume path requiere **ambas** señales (respuesta del usuario +
handle previo). Si cualquiera falta, el executor cae a prompt fresco
con warning; la task nunca se bloquea por un session_handle perdido.
La sesión del CLI puede expirar con respuestas tardías — el error
cae en `cli_nonzero_exit` y la task termina `failed`. Aceptable para
el MVP (seguimiento en las notas del brief).

### Tests

- `tests/test_adapter.py` (+2): `test_session_id_extracted_from_system_init`
  y `test_resume_handle_adds_resume_arg_to_cli`.
- `tests/test_executor.py` (+2): `test_resume_path_uses_prev_run_session_handle`
  (stubea `ClaudeCodeAdapter` para capturar kwargs) y
  `test_resume_prompt_is_user_response_not_task_description`.
- `tests/test_tasks_api.py` (+1):
  `test_respond_writes_normalized_user_response_event` (asserta el
  payload vía `json_extract`).
- Fixture: `fake_claude_cli.py` acepta `FAKE_CLAUDE_SESSION_ID` que
  se emite como `system/init` antes del script principal.

## Próximos PRs (SPEC §9)

- Semana 5 (restante): instalación en la máquina de la pareja.
- Semana 6: bugfix + jubilar v0.2. Follow-ups de PR-V1-22:
  detectar expiración de sesión en el CLI con fallback a prompt
  compuesto; UI para cancelar un `waiting_input` largo.

Ver `v1/docs/plans/` para los briefs conforme se escriben.
