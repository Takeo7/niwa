# PR-V1-05 — Executor echo daemon

**Semana:** 1
**Esfuerzo:** M
**Depende de:** PR-V1-04

## Qué

Primer executor: un proceso Python que hace polling sobre la DB,
toma tareas `queued`, las procesa con un "echo" inocuo (no hay
Claude CLI todavía) y las marca `done`. Crea la fila `Run` asociada
y escribe `run_events` mínimos. Sin rama git, sin PR, sin
verificación.

## Por qué

SPEC §9 Semana 1: "Endpoint POST /tasks escribe, el executor lee
pero hace echo." Este PR cierra Semana 1 dejando un pipeline E2E
observable: crear task → executor la transita → task.status=done +
run.status=completed. El adapter real y la verificación llegan en
Semana 2+.

## Scope — archivos que toca

- `v1/backend/app/executor/__init__.py` (nuevo, re-exporta)
- `v1/backend/app/executor/core.py` (lógica pura:
  `claim_next_task(session) -> Task | None`,
  `run_echo(session, task) -> Run`,
  `process_pending(session) -> int` — cantidad procesada)
- `v1/backend/app/executor/runner.py` (loop: `run_forever(interval)`
  con `session_scope` y `logging`)
- `v1/backend/app/executor/__main__.py` (entrypoint para
  `python -m app.executor`; parsea `--interval` y `--once`)
- `v1/backend/app/api/tasks.py` (añade `GET /api/tasks/{id}/runs` —
  lista runs de una task para validar desde fuera; el brief lo pide
  como parte de "pipeline observable")
- `v1/backend/app/schemas/run.py` (`RunRead`)
- `v1/backend/app/schemas/__init__.py` (re-export)
- `v1/backend/app/services/runs.py` (helpers: `create_run`,
  `complete_run`, `list_runs_for_task`)
- `v1/backend/tests/test_executor.py` (ver §Tests)
- `v1/backend/tests/test_runs_api.py` (tests del nuevo endpoint)
- `v1/docs/HANDBOOK.md` (sección "Executor" nueva)

## Fuera de scope (explícito)

- **No hay Claude CLI adapter.** Semana 2.
- **No hay triage.** Semana 3.
- **No hay verificación (artifact_root, evidencias).** Semana 3.
- **No hay rama git ni commits/push.** Semana 2.
- **No hay approvals ni auto-merge.** Semana 4.
- **No systemd unit file.** El bootstrap llega con `v1/bootstrap.sh`.
- **No stream SSE.** La UI sigue polling por ahora.
- **No cancel endpoint.** Fuera de alcance de este PR; un PR dedicado
  lo añade.
- **No respawn si el loop crashea.** Excepciones no atrapadas matan
  el daemon — el systemd unit posterior hará respawn.

## Dependencias nuevas

- Python: ninguna. `logging` + stdlib.
- npm: ninguna.

## Schemas (contrato)

```python
class RunRead(BaseModel):
    id: int
    task_id: int
    status: Literal["queued", "running", "completed", "failed",
                    "cancelled"]
    model: str
    started_at: datetime
    finished_at: datetime | None
    exit_code: int | None
    outcome: str | None
    session_handle: str | None
    artifact_root: str
    verification_json: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

## Semántica del echo

Por cada task `queued` (ordenada `created_at asc, id asc`):

1. Transicionar `task.status: queued → running`. Escribir `task_event`
   `status_changed`.
2. Crear `Run` con: `status="running"`, `model="echo"`,
   `started_at=now()`, `artifact_root=""` (MVP echo no tiene
   artefactos), `session_handle=None`.
3. Escribir `run_event` `event_type="started"`, payload vacío.
4. **Echo:** no hay trabajo — se salta directo al cierre. Sin sleeps
   artificiales.
5. Actualizar Run: `status="completed"`, `finished_at=now()`,
   `exit_code=0`, `outcome="echo"`.
6. Escribir `run_event` `event_type="completed"`.
7. Transicionar `task.status: running → done`. Escribir `task_event`
   `status_changed`. `task.completed_at=now()`.
8. Commit de la transacción. Si algo falla → rollback y task queda
   en `running` (para retry manual; el daemon no reintenta
   automáticamente en este PR).

**Idempotencia:** `claim_next_task` usa `SELECT ... WITH FOR UPDATE`
simulado con `BEGIN IMMEDIATE` de SQLite (`session.begin()` + `UPDATE
... SET status='running' WHERE id=? AND status='queued'`). Si otra
instancia ya lo cogió, el UPDATE afecta 0 filas → se salta.

## Tests

En `v1/backend/tests/test_executor.py`:

1. `test_process_pending_nothing_to_do` — DB vacía → `process_pending`
   devuelve `0`.
2. `test_process_pending_single_task` — crea project+task; después
   `process_pending` devuelve `1`, task.status=`done`,
   task.completed_at no-null, run.status=`completed`,
   `exit_code=0`, `outcome="echo"`.
3. `test_process_pending_multiple_tasks` — 3 tasks queued;
   `process_pending` devuelve `3` y todas quedan `done` en orden
   de creación.
4. `test_process_pending_skips_non_queued` — task en `inbox`, otra
   en `running`, otra en `done`: `process_pending` devuelve `0` y
   ninguna cambia.
5. `test_run_writes_expected_events` — tras el echo, el run tiene
   exactamente 2 `run_events`: `started` y `completed`.
6. `test_task_writes_status_transitions` — tras el echo, la task
   tiene `task_events` con kinds `status_changed` en orden
   (`queued→running`, `running→done`).
7. `test_claim_is_atomic_under_race` — dos threads llaman
   `claim_next_task` simultáneamente sobre la misma task; solo uno
   devuelve la task, el otro `None`.

En `v1/backend/tests/test_runs_api.py`:

8. `test_list_runs_for_task_empty` — task sin runs → `[]`.
9. `test_list_runs_for_task_after_echo` — tras `process_pending`,
   `GET /api/tasks/{id}/runs` devuelve el run con status
   `completed`.
10. `test_list_runs_for_task_not_found` — task inexistente → `404`.

**Baseline tras PR:** 34 (PR-V1-04) + 10 nuevos = **44 passed**.

## Criterio de hecho

- [ ] `pytest -q` en `v1/backend/` → 44 passed.
- [ ] `python -m app.executor --once` desde `v1/backend/` procesa
  las `queued` existentes y termina con exit 0.
- [ ] `python -m app.executor --interval 0.5` arranca el loop en
  foreground y procesa tasks creadas en caliente (test manual).
- [ ] `curl .../api/tasks/{id}/runs` devuelve el run tras el echo.
- [ ] `HANDBOOK.md` documenta el executor: entrypoint, estados de
  run, qué es "echo" y qué se sustituye en Semana 2.
- [ ] Frontend sin cambios.

## Riesgos conocidos

- **Race con SQLite.** SQLite serializa escrituras; el race test
  puede volverse flaky bajo carga. Si aparece, el test puede hacer
  reintentos limitados. Preferimos `BEGIN IMMEDIATE` a un `for
  update` inexistente en SQLite.
- **Transacción larga.** La transacción envuelve `UPDATE task` +
  `INSERT run` + events. Manten todo dentro de un `session.begin()`
  explícito; si el loop necesita más granularidad llegará cuando
  haya ejecución real.
- **Logging ruidoso.** Usa `logging.getLogger("niwa.executor")` con
  INFO por defecto; el runner CLI sube a DEBUG con `--verbose`.

## Notas para Claude Code

- Commits sugeridos:
  1. `feat(v1): run pydantic schema`
  2. `feat(v1): run service helpers`
  3. `feat(v1): executor core echo pipeline`
  4. `feat(v1): executor runner and cli entrypoint`
  5. `feat(v1): list runs endpoint`
  6. `test(v1): executor echo`
  7. `test(v1): runs api`
- El `__main__.py` debe ser muy fino: `argparse` + llamada a
  `run_forever` o `process_pending` según flags.
- Tests de executor NO deben arrancar el loop; llaman directo a
  `process_pending(session)`. Solo el test de race usa threads.
- `completed_at` de task y `finished_at` de run se fijan con
  `datetime.now(timezone.utc)` desde el service (no con
  `func.now()`) para tener granularidad de microsegundos en los
  tests.
- No metas retry, backoff, ni circuit breakers — todo eso es
  prematuro hasta tener executor real.
- Esfuerzo M → codex review obligatorio antes de mergear.
