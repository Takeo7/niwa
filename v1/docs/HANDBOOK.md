# Niwa v1 — Handbook

Guía operativa y arquitectural del código dentro de `v1/`. Se actualiza
en cada PR que añade/quita módulo backend, feature frontend, tabla DB o
cambia el pipeline. El SPEC vive en `v1/docs/SPEC.md` — este documento
es el "cómo" práctico, no el "qué" del producto.

## Layout actual (tras PR-V1-02)

```
v1/
├── backend/                    # FastAPI app (Python 3.11+)
│   ├── app/
│   │   ├── __init__.py         # __version__
│   │   ├── main.py             # FastAPI factory, /api/health
│   │   ├── config.py           # ~/.niwa/config.toml loader
│   │   ├── db.py               # SQLAlchemy engine + Base + FK PRAGMA
│   │   └── models/             # ORM models (SPEC §3)
│   ├── alembic.ini
│   ├── migrations/             # env.py con render_as_batch=True
│   │   └── versions/           # initial_schema (9d205b6968c1)
│   ├── tests/                  # pytest + TestClient
│   └── pyproject.toml
├── frontend/                   # React 19 + Vite + Mantine v7
│   ├── src/
│   │   ├── main.tsx            # MantineProvider + React Query
│   │   ├── App.tsx             # landing
│   │   └── api.ts              # fetch wrapper a /api
│   ├── index.html
│   ├── vite.config.ts          # proxy /api → :8000
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
- **Frontend:** `cd v1/frontend && npm test` (vitest + jsdom, aún sin
  tests en PR-V1-01 — suite vacía pasa con "no tests found").

## Próximos PRs (SPEC §9)

- PR-V1-03: CRUD proyectos y tareas. `POST /api/tasks`.
- PR-V1-04: executor daemon en modo echo.

Ver `v1/docs/plans/` para los briefs conforme se escriben.
