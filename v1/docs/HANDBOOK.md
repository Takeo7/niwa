# Niwa v1 — Handbook

Guía operativa y arquitectural del código dentro de `v1/`. Se actualiza
en cada PR que añade/quita módulo backend, feature frontend, tabla DB o
cambia el pipeline. El SPEC vive en `v1/docs/SPEC.md` — este documento
es el "cómo" práctico, no el "qué" del producto.

## Layout actual (tras PR-V1-01)

```
v1/
├── backend/                    # FastAPI app (Python 3.11+)
│   ├── app/
│   │   ├── __init__.py         # __version__
│   │   ├── main.py             # FastAPI factory, /api/health
│   │   ├── config.py           # ~/.niwa/config.toml loader
│   │   └── db.py               # SQLAlchemy engine + Base
│   ├── alembic.ini
│   ├── migrations/             # env.py con render_as_batch=True
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

Declarative `Base` vive en `app/db.py`. Alembic apunta a la misma
metadata vía `migrations/env.py`. `render_as_batch=True` porque SQLite
no soporta la mayoría de `ALTER TABLE` — cada cambio de schema recrea
la tabla en una copia.

PR-V1-01 no declara tablas todavía; el directorio `migrations/versions`
queda con un `.gitkeep` hasta PR-V1-02.

## Tests

- **Backend:** `cd v1/backend && pytest -q` (fixture `client` monta
  `TestClient` sobre `app.main:app`).
- **Frontend:** `cd v1/frontend && npm test` (vitest + jsdom, aún sin
  tests en PR-V1-01 — suite vacía pasa con "no tests found").

## Próximos PRs (SPEC §9)

- PR-V1-02: las 5 tablas (`projects`, `tasks`, `task_events`, `runs`,
  `run_events`) + primera migración.
- PR-V1-03: CRUD proyectos y tareas. `POST /api/tasks`.
- PR-V1-04: executor daemon en modo echo.

Ver `v1/docs/plans/` para los briefs conforme se escriben.
