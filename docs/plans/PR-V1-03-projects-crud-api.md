# PR-V1-03 — Projects CRUD API

**Semana:** 1
**Esfuerzo:** M
**Depende de:** PR-V1-02

## Qué

Añadir los 5 endpoints REST del recurso `Project` en el backend:
`GET /api/projects`, `POST /api/projects`, `GET /api/projects/{slug}`,
`PATCH /api/projects/{slug}`, `DELETE /api/projects/{slug}`. Con
schemas Pydantic v2, validación básica y tests. Cero frontend, cero
tareas, cero runs.

## Por qué

SPEC §9 Semana 1 pide "CRUD proyectos/tareas". Este PR entrega el
primero de los dos — proyectos. Los demás PRs (CRUD tasks, executor)
dependen de poder listar/crear un proyecto antes.

## Scope — archivos que toca

- `v1/backend/app/schemas/__init__.py` (nuevo, re-exporta)
- `v1/backend/app/schemas/project.py` (`ProjectRead`, `ProjectCreate`,
  `ProjectPatch`)
- `v1/backend/app/services/__init__.py` (nuevo)
- `v1/backend/app/services/projects.py` (funciones puras sobre
  `Session`: `list_projects`, `create_project`, `get_project`,
  `patch_project`, `delete_project`)
- `v1/backend/app/api/__init__.py` (nuevo, `APIRouter` principal)
- `v1/backend/app/api/projects.py` (5 endpoints; `get_session`
  dependency local al router)
- `v1/backend/app/api/deps.py` (dependencia `get_session` compartida)
- `v1/backend/app/main.py` (registra el router bajo `/api`)
- `v1/backend/tests/conftest.py` (fixture `client` con DB en memoria
  y `Base.metadata.create_all`)
- `v1/backend/tests/test_projects_api.py` (ver §Tests)
- `v1/docs/HANDBOOK.md` (sección "API" añadida con las 5 rutas de
  projects)

## Fuera de scope (explícito)

- **No hay CRUD de tasks.** Llega en PR-V1-04.
- **No hay executor.** Llega más adelante.
- **No hay frontend.** La UI de lista de proyectos llega en PR
  dedicado posterior.
- **No hay auth.** Bind local, sin tokens.
- **No hay paginación.** `GET /api/projects` devuelve lista completa
  por ahora; en el MVP el volumen es ~10 proyectos.
- **No hay filtros ni búsqueda.** KISS.
- **No hay OpenAPI tuning** — lo que genere FastAPI por defecto vale.

## Dependencias nuevas

- Python: ninguna (fastapi + pydantic v2 ya instaladas).
- npm: ninguna.

## Schemas (contrato)

```python
class ProjectCreate(BaseModel):
    slug: str  # validador: [a-z0-9-], 3-40 chars
    name: str  # 1-120 chars
    kind: Literal["web-deployable", "library", "script"]
    git_remote: str | None = None
    local_path: str  # path absoluto, no validado al existir en MVP
    deploy_port: int | None = None  # 1024-65535 si kind=web-deployable
    autonomy_mode: Literal["safe", "dangerous"] = "safe"

class ProjectPatch(BaseModel):
    name: str | None = None
    kind: Literal["web-deployable", "library", "script"] | None = None
    git_remote: str | None = None
    local_path: str | None = None
    deploy_port: int | None = None
    autonomy_mode: Literal["safe", "dangerous"] | None = None
    # slug NO es patcheable. Renombrar = borrar + crear.

class ProjectRead(BaseModel):
    id: int
    slug: str
    name: str
    kind: str
    git_remote: str | None
    local_path: str
    deploy_port: int | None
    autonomy_mode: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

## Tests

Todos en `v1/backend/tests/test_projects_api.py`, usando el `client`
fixture con DB SQLite en memoria aislada por test:

1. `test_list_projects_empty` — `GET /api/projects` devuelve `[]`.
2. `test_create_project_happy` — `POST /api/projects` con payload
   válido devuelve `201` + `ProjectRead` con `id`, `created_at`,
   `updated_at`, defaults correctos.
3. `test_create_project_duplicate_slug` — `POST` dos veces con el
   mismo `slug` → segunda devuelve `409`.
4. `test_create_project_invalid_slug` — `slug` con mayúsculas o
   espacios → `422`.
5. `test_create_project_invalid_kind` — `kind="desktop"` → `422`.
6. `test_get_project_by_slug` — `GET /api/projects/{slug}` tras un
   create devuelve el project; `GET` inexistente → `404`.
7. `test_patch_project` — `PATCH` con `{"autonomy_mode":"dangerous"}`
   actualiza solo ese campo; `updated_at` cambia; respuesta `200`.
8. `test_patch_project_slug_rejected` — intentar patchear `slug` →
   `422` (no está en el schema).
9. `test_delete_project` — `DELETE /api/projects/{slug}` devuelve
   `204`; `GET` posterior → `404`.
10. `test_delete_project_not_found` — `DELETE` inexistente → `404`.
11. `test_list_projects_returns_created` — tras crear 2, `GET`
    devuelve lista de 2 ordenada por `created_at` asc.

**Baseline tras PR:** 11 (PR-V1-02) + 11 nuevos = **22 passed**.

## Criterio de hecho

- [ ] `pytest -q` en `v1/backend/` → 22 passed.
- [ ] `uvicorn app.main:app` arranca; `curl -X POST
  http://localhost:8000/api/projects -H 'Content-Type: application/json'
  -d '{"slug":"demo","name":"Demo","kind":"library","local_path":"/tmp/demo"}'`
  devuelve `201` con el recurso creado.
- [ ] `curl http://localhost:8000/api/projects` devuelve `[{...}]`.
- [ ] `curl http://localhost:8000/docs` muestra los 5 endpoints en
  OpenAPI.
- [ ] `HANDBOOK.md` sección "API" lista las 5 rutas con `Method
  Path → Return`.
- [ ] Frontend sin cambios; `npm test -- --run` sigue en 0 tests OK.

## Riesgos conocidos

- **Slug duplicado.** El modelo declara `unique=True`; hay que
  traducir el `IntegrityError` a `409 Conflict` con mensaje claro, no
  dejar que FastAPI devuelva `500`.
- **Session lifecycle en tests.** Usa
  `TestClient` con dependency override de `get_session` para inyectar
  una DB en memoria por test; evita ensuciar `v1/data/niwa-v1.sqlite3`.
- **deploy_port sin validación cruzada.** La regla "si `kind=web-deployable`
  debería tener `deploy_port`" la dejamos al servicio de deploy (PR
  futuro). Aquí solo valida rango si viene.

## Notas para Claude Code

- Un commit por capa: `feat(v1): project pydantic schemas`,
  `feat(v1): project service functions`,
  `feat(v1): project crud endpoints`,
  `test(v1): projects api` (4 commits).
- Las funciones de `services/projects.py` reciben `Session` explícito
  y hacen `session.commit()` dentro. Prefiere funciones a clases.
- El router se registra con `prefix="/api/projects"` y `tags=["projects"]`.
- Errores: `HTTPException(status_code=409, detail="slug already exists")`,
  `404, detail="project not found"`.
- No añadas middleware, CORS, logging; esos llegan cuando haga falta
  (frontend o cross-origin real).
- Esfuerzo M → el orquestador correrá codex-reviewer antes de
  mergear.
