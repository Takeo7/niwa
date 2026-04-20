# PR-V1-04 — Tasks CRUD API

**Semana:** 1
**Esfuerzo:** M
**Depende de:** PR-V1-03

## Qué

Añadir los endpoints REST del recurso `Task` al backend:

- `GET /api/projects/{slug}/tasks` — lista tareas del proyecto.
- `POST /api/projects/{slug}/tasks` — crea tarea, status `queued`.
- `GET /api/tasks/{task_id}` — detalle de una tarea.
- `DELETE /api/tasks/{task_id}` — borra tarea.

Con schemas Pydantic v2, validación, `task_events` escritos en
`created` y `status_changed`, y tests. Cero executor, cero
`waiting_input`, cero `respond`, cero subtareas.

## Por qué

SPEC §9 Semana 1 pide "CRUD proyectos/tareas. Endpoint POST /tasks
escribe". Este PR entrega CRUD de tasks; el PR siguiente (executor
echo, PR-V1-05) cierra Semana 1 leyendo las `queued` y marcándolas
`done`.

## Scope — archivos que toca

- `v1/backend/app/schemas/__init__.py` (re-exporta los nuevos)
- `v1/backend/app/schemas/task.py` (`TaskRead`, `TaskCreate`)
- `v1/backend/app/services/tasks.py` (`list_tasks_for_project`,
  `create_task`, `get_task`, `delete_task`; escribe `task_events`
  al crear y al cambiar estado)
- `v1/backend/app/api/tasks.py` (4 endpoints nuevos bajo el router
  principal)
- `v1/backend/app/api/__init__.py` (registra el router de tasks)
- `v1/backend/tests/test_tasks_api.py` (ver §Tests)
- `v1/docs/HANDBOOK.md` (sección "API" extendida con las 4 rutas)

## Fuera de scope (explícito)

- **No hay executor.** Llega en PR-V1-05.
- **No hay triage, ni split, ni subtareas.** `parent_task_id` sigue
  nullable; no se expone en el create.
- **No hay POST `/respond`.** Llega cuando haya adapter Claude Code.
- **No hay PATCH de task** (cambiar título/descripción). Para el
  MVP se crea y se borra; editar es scope futuro.
- **No hay transiciones de estado desde la API** salvo la creación
  (→`queued`) y el delete. Los demás estados los escribe el executor.
- **No hay stream ni SSE.** La UI consulta `GET` por polling.
- **No hay frontend.** Será un PR separado.

## Dependencias nuevas

- Python: ninguna.
- npm: ninguna.

## Schemas (contrato)

```python
class TaskCreate(BaseModel):
    title: str  # 1-200 chars
    description: str | None = None  # hasta 10_000 chars
    # status, branch_name, pr_url, pending_question, timestamps
    # NO se aceptan en create — los pone el servicio.

class TaskRead(BaseModel):
    id: int
    project_id: int
    parent_task_id: int | None
    title: str
    description: str | None
    status: Literal["inbox", "queued", "running", "waiting_input",
                    "done", "failed", "cancelled"]
    branch_name: str | None
    pr_url: str | None
    pending_question: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    model_config = ConfigDict(from_attributes=True)
```

## Semántica

- `POST /api/projects/{slug}/tasks` con `TaskCreate`:
  1. Si el proyecto no existe → `404`.
  2. Crea `Task` con `status="queued"`, `project_id` del proyecto,
     `parent_task_id=None`.
  3. Escribe un `TaskEvent` con `kind="created"` y `message=title`.
  4. Escribe un `TaskEvent` con `kind="status_changed"`,
     `payload_json='{"from":null,"to":"queued"}'`.
  5. Devuelve `201` + `TaskRead`.
- `GET /api/projects/{slug}/tasks` → lista todas las tasks del
  proyecto ordenadas por `created_at asc, id asc`.
- `GET /api/tasks/{task_id}` → detalle; `404` si no existe.
- `DELETE /api/tasks/{task_id}`:
  1. `404` si no existe.
  2. Si `status in ("running", "waiting_input")` → `409` con mensaje
     "task is active; cancel first".
  3. Borra la task (cascade limpia `task_events`, `runs`,
     `run_events` por las FKs). `204`.

## Tests

En `v1/backend/tests/test_tasks_api.py`, usando fixture `client` ya
existente y creando un project por test via helper:

1. `test_list_tasks_empty` — proyecto existe, 0 tasks → `[]`.
2. `test_create_task_happy` — `POST` válido → `201` con `status="queued"`,
   `parent_task_id=None`, timestamps rellenos.
3. `test_create_task_project_not_found` — slug inexistente → `404`.
4. `test_create_task_missing_title` → `422`.
5. `test_create_task_title_too_long` (201 chars) → `422`.
6. `test_create_task_writes_events` — tras crear una task, hay
   exactamente 2 `task_events`: `created` y `status_changed`
   (`null → queued`).
7. `test_get_task_happy` — `GET /api/tasks/{id}` devuelve lo
   esperado.
8. `test_get_task_not_found` → `404`.
9. `test_list_tasks_order` — crea 2 tasks; `GET` devuelve en orden
   de creación con tie-breaker por id.
10. `test_delete_task_queued` → `204`; `GET` posterior → `404`.
11. `test_delete_task_running_conflict` — crea task, la marca
    `running` directamente por SQL (no hay executor aún) y el DELETE
    responde `409`.
12. `test_delete_task_cascades_events` — crear task, borrarla, y
    verificar que `task_events` asociados desaparecen.

**Baseline tras PR:** 22 (PR-V1-03) + 12 nuevos = **34 passed**.

## Criterio de hecho

- [ ] `pytest -q` en `v1/backend/` → 34 passed.
- [ ] `curl -X POST .../api/projects/{slug}/tasks -d '{"title":"hello"}'`
  devuelve `201` con la task en `queued`.
- [ ] `curl .../api/projects/{slug}/tasks` devuelve lista.
- [ ] `curl .../api/tasks/{id}` devuelve la task.
- [ ] `HANDBOOK.md` sección "API" lista las 4 rutas.
- [ ] Frontend sin cambios; `npm test -- --run` en verde.
- [ ] No hay referencias a executor, adapter, Claude CLI, triage en
  este PR.

## Riesgos conocidos

- **task_events como side-effect del service.** Debe pasar dentro
  de la misma transacción que el `Task`; si falla la escritura del
  evento, la task no debe existir. Usa un solo `session.commit()` al
  final.
- **DELETE cascade.** La migración ya declaró FKs con `ondelete
  CASCADE` (ver PR-V1-02). Confirma con test que realmente borra
  dependientes; sin `PRAGMA foreign_keys=ON` no cascadea. El listener
  ya está en `db.py`.
- **`GET /api/tasks/{id}` global** (no scoped a proyecto) es
  deliberado — SPEC §7 muestra `/projects/:slug/tasks/:id` pero la
  API no necesita el slug para fetch por id; la UI se lo lleva de la
  URL como contexto.

## Notas para Claude Code

- Commits sugeridos: `feat(v1): task pydantic schemas`,
  `feat(v1): task service with event writes`,
  `feat(v1): task crud endpoints`,
  `test(v1): tasks api`.
- Los `task_events` los escribe `services/tasks.py`; el endpoint no
  sabe de ellos. Mantén el router fino.
- `payload_json` es un `str` con JSON serializado manualmente —
  `json.dumps({"from": None, "to": "queued"})`.
- Evita `datetime.utcnow()` dentro del service: usa `server_default`
  / `onupdate` del modelo para timestamps (ya declarados).
- Esfuerzo M → el orquestador correrá codex-reviewer antes de
  mergear.
