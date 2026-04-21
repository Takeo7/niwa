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
- `stream.py` — E2. `check_stream_termination(events) -> error_code |
  None`. Ignora lifecycle (`started`/`completed`/`failed`/`error`).
  Reglas último evento: `result` → OK (MVP trust), `assistant` text
  que acaba en `?` → `question_unanswered`, `tool_use` sin
  `tool_result` tras → `tool_use_incomplete`, otra cosa o vacío →
  `empty_stream`.
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
`test_exit_code` / `test_output_tail` para diagnóstico.

### Tests

- `tests/verification/test_stream.py` — 4 casos unitarios del E2
  analyzer (result/success, question trailing, tool_use trailing,
  empty stream).
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

## Próximos PRs (SPEC §9)

- PR-V1-08: ejecución aislada en rama git por task. Crear/chequear
  `niwa/<task_id>-<slug>`, sandboxear el CLI en ella, post-run con
  diff + commit + push + PR. El adapter actual queda intacto.
- PR-V1-11+: verificación post-run (exit code + artefactos + tests del
  proyecto), triaje planner, modo safe con PR manual (Semana 3 del
  SPEC). El feedback de aprobación humana en UI y el clarification
  round-trip llegan en Semana 5.

Ver `v1/docs/plans/` para los briefs conforme se escriben.
