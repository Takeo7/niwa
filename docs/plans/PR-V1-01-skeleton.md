# PR-V1-01 — Esqueleto FastAPI + React + SQLite

**Semana:** 1
**Esfuerzo:** S
**Depende de:** ninguna

## Qué

Crea la estructura base del proyecto v1: backend FastAPI con endpoint
`/api/health`, frontend React+Vite+Mantine con landing mínima, SQLite
inicializada con Alembic (sin tablas todavía), y un Makefile que
arranca ambos en dev.

## Por qué

Es el esqueleto de la Semana 1 del SPEC. Sin él, los siguientes PRs
no tienen dónde escribir. Valida que el stack elegido arranca en
local antes de meter lógica.

## Scope — archivos que toca

```
v1/
├── backend/
│   ├── pyproject.toml                    # deps + setup
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                       # FastAPI app, /api/health
│   │   ├── config.py                     # lee ~/.niwa/config.toml
│   │   └── db.py                         # engine + session maker
│   ├── alembic.ini
│   ├── migrations/
│   │   ├── env.py
│   │   └── versions/.gitkeep             # sin migrations aún
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                   # fixture app + client
│       └── test_health.py                # GET /api/health → 200
├── frontend/
│   ├── package.json                      # React 19, Vite, Mantine, React Query
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx                      # entrypoint, MantineProvider
│       ├── App.tsx                       # landing "Niwa v1"
│       └── api.ts                        # fetch wrapper a /api
├── data/.gitkeep                         # SQLite vive aquí
├── Makefile                              # dev, test, install
└── docs/
    └── HANDBOOK.md                       # arquitectura v1, se irá ampliando
```

## Fuera de scope (explícito)

- **No hay modelos de datos.** Las 5 tablas llegan en PR-V1-02.
- **No hay endpoints CRUD.** Solo `/api/health`.
- **No hay executor.** Llega en PR-V1-05.
- **No hay config real.** `config.py` lee un TOML de ejemplo pero no
  se usa todavía.
- **No hay autenticación.** Bind local, fin.
- **No hay Docker.** En v1 el dev y el install es local, sin
  contenedores (al menos en el MVP).

## Dependencias nuevas

- **Python** (`v1/backend/pyproject.toml`):
  - `fastapi`
  - `uvicorn[standard]`
  - `sqlalchemy>=2`
  - `alembic`
  - `pydantic>=2`
  - `pydantic-settings`
  - `tomli` (o stdlib `tomllib` si Python ≥ 3.11)
  - Dev: `pytest`, `httpx`
- **npm** (`v1/frontend/package.json`):
  - `react@19`, `react-dom@19`, `react-router-dom@7`
  - `@mantine/core@7`, `@mantine/hooks@7`
  - `@tanstack/react-query@5`
  - Dev: `vite`, `@vitejs/plugin-react`, `typescript`, `vitest`,
    `jsdom`, `@testing-library/react`
  - Pin exacto igual que el frontend de v0.2 para no reinventar.

Todas pre-aprobadas por `v1/CLAUDE.md §Reglas duras 10`.

## Tests

- **Nuevo backend:** `v1/backend/tests/test_health.py`
  - `GET /api/health` devuelve 200 con `{"status": "ok", "version":
    "0.1.0"}`.
- **Nuevo frontend:** ninguno en este PR (se añade vitest setup pero
  sin tests todavía; un test-suite vacío pasa).
- **Baseline tras el PR:** backend `1 passed`, frontend `0 tests
  collected`.

## Criterio de hecho

- [ ] `make -C v1 install` instala deps backend y frontend.
- [ ] `make -C v1 dev` arranca backend en `:8000` y frontend en
  `:5173` en paralelo.
- [ ] `curl localhost:8000/api/health` → `{"status":"ok",...}`
- [ ] `http://localhost:5173` muestra "Niwa v1" en pantalla.
- [ ] `cd v1/backend && pytest -q` → 1 passed.
- [ ] `cd v1/frontend && npm test -- --run` → 0 tests collected sin
  error.
- [ ] `alembic current` no falla (sin migraciones, pero Alembic está
  inicializado correctamente).
- [ ] No hay referencias a `niwa-app/`, `bin/` ni `servers/` desde
  `v1/`. Esqueleto independiente.

## Riesgos conocidos

- **Alembic con SQLite y FKs.** Alembic + SQLite requiere
  `render_as_batch=True` en `env.py` para soportar ALTER TABLE con
  FKs. Documentar en el propio `env.py`.
- **Mantine v7 + React 19.** Ya funciona en v0.2; si aparece warning
  de peer deps, se ignora.

## Notas para Claude Code

- Este PR es scaffolding puro. No metas lógica de negocio, aunque el
  siguiente PR "obviamente" la necesite.
- Copia el pin de dependencias frontend desde
  `niwa-app/frontend/package.json` para ahorrar decisiones.
- `Makefile` mínimo — 4 targets: `install`, `dev`, `test`, `clean`.
  No inventes más.
- Commits sugeridos:
  1. `chore(v1): backend skeleton with fastapi and alembic`
  2. `chore(v1): frontend skeleton with vite and mantine`
  3. `chore(v1): makefile with install/dev/test/clean`
  4. `test(v1): health endpoint returns 200`
