# PR-V1-23 — Parent task semantics (promote on subtasks terminal)

**Tipo:** FIX (semántica)
**Semana:** 6
**Esfuerzo:** S-M
**Depende de:** PR-V1-22 (no estrictamente, pero conviene que el
resume esté wired para no interferir con estado de subtasks)

## Qué

La tarea madre que triage decide split hoy pasa a `done` al
emitir el evento `triage_split`, sin esperar a que las hijas
terminen. Evidencia en smoke 2026-04-22: task 9 (LICENSE + CI)
pasó a `done` en ~7s, subtask 10 `done`, subtask 11 `failed`;
la madre sigue marcada `done` falsamente.

El fix: la madre queda `running` después del split. Tras cada
subtask que alcanza estado terminal, el executor comprueba si
todas las hijas han terminado; si sí, promociona el estado del
padre según agregación:

- Todas `done` → madre `done`.
- Alguna `failed` → madre `failed`.
- Alguna `cancelled` y ninguna `failed` → madre `cancelled`.
- Alguna en `waiting_input`, `queued`, `running` → madre sigue
  `running` (no promover).

## Por qué

El kanban / lista de tareas muestra `done` para una madre que
semánticamente NO terminó (tiene una hija fallida y otra pendiente
de respuesta). Un usuario lee el status y asume trabajo cerrado
cuando no lo está. Es deuda visual que se paga cada vez que se
usa el producto con tareas complejas.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── triage.py                  # quitar la transición running→done
│   │                              # al split; dejar en running
│   └── executor/
│       └── core.py                # _finalize: tras actualizar
│                                  # hija, _maybe_promote_parent()
└── tests/
    ├── test_triage.py             # +1: parent keeps running after split
    ├── test_executor.py           # +3: promotion rules
    └── test_executor_parent.py    # NUEVO si el fichero existente crece
                                   # demasiado
```

**Hard-cap: 250 LOC** código + tests.

## Fuera de scope

- No introducir `done_with_failures` u otro status nuevo. La madre
  se propaga al estado agregado con los 7 existentes (inbox, queued,
  running, waiting_input, done, failed, cancelled).
- No propagación recursiva a nietos (los splits hoy son de 1 nivel,
  SPEC no admite decompose de N niveles).
- No resumir/contar subtasks en el TaskRead — eso es follow-up UI.
- No tocar frontend — el cambio es transparente, status de la madre
  simplemente se actualiza más tarde.

## Contrato tras el fix

### En `triage.py` / donde aplica split

Hoy tras emitir el TaskEvent triage_split se escribe:

```python
task.status = "done"  # ← QUITAR esta línea
```

La madre debe quedar en `running` después del split. La
transición a terminal llega via `_maybe_promote_parent` cuando
todas las hijas acaben.

### En `executor/core.py::_finalize`

Al final de la función, después de actualizar status de la subtask:

```python
if task.parent_task_id is not None:
    _maybe_promote_parent(session, task.parent_task_id)
```

### Nueva función `_maybe_promote_parent`

```python
_TERMINAL_STATUSES = {"done", "failed", "cancelled"}

def _maybe_promote_parent(session: Session, parent_id: int) -> None:
    """If every subtask of ``parent_id`` is terminal, update parent.

    Aggregation:
      - all done → done
      - any failed → failed
      - any cancelled (and none failed) → cancelled
      - any non-terminal → no-op
    """

    children = session.execute(
        select(Task).where(Task.parent_task_id == parent_id)
    ).scalars().all()
    if not children:
        return  # defensive; shouldn't happen

    statuses = [c.status for c in children]
    if any(s not in _TERMINAL_STATUSES for s in statuses):
        return

    parent = session.get(Task, parent_id)
    if parent is None:
        return
    if parent.status in _TERMINAL_STATUSES:
        return  # already promoted (idempotent)

    if any(s == "failed" for s in statuses):
        new_status = "failed"
    elif all(s == "done" for s in statuses):
        new_status = "done"
    else:
        new_status = "cancelled"

    from_status = parent.status
    parent.status = new_status
    if new_status == "done":
        parent.completed_at = datetime.now(timezone.utc)

    session.add(TaskEvent(
        task_id=parent.id,
        kind="status_changed",
        message=None,
        payload_json=json.dumps({
            "from": from_status,
            "to": new_status,
            "reason": "subtasks_terminal",
        }),
    ))
    session.commit()
```

### Regla defensiva

`_maybe_promote_parent` no lanza; si algo está mal (huérfanos,
ciclos), loguea warning y return. La promoción es best-effort.

## Tests

### `test_triage.py` — 1 caso nuevo

- `test_parent_stays_running_after_split`: mock triage que decide
  split; tras llamar al código del split, `parent.status ==
  "running"`, las subtasks existen en `queued`.

### `test_executor.py` — 3 casos nuevos (o en `test_executor_parent.py`)

- `test_parent_promoted_to_done_when_all_subtasks_done`: setup con
  parent `running`, 2 subtasks `done`. Llamar a `_finalize` sobre
  la segunda subtask → parent queda `done` con `completed_at`.
- `test_parent_promoted_to_failed_when_any_subtask_failed`: parent
  `running`, 1 subtask `done`, 1 `failed`. Finalize sobre la
  failed → parent `failed`.
- `test_parent_stays_running_when_any_subtask_not_terminal`:
  parent `running`, 1 subtask `done`, 1 `running`. Finalize sobre
  la done → parent sigue `running`.

### Baseline tras el fix

143 + 4 = **147 passed**.

## Criterio de hecho

- [ ] `pytest -q` → 147 passed, 0 regresiones.
- [ ] Smoke manual: crear tarea "Añade LICENSE y CI workflow"
      (ambigua, la del smoke real). Triage split → madre
      `running`. Hija LICENSE termina `done`. Madre sigue
      `running`. Hija CI termina (o `failed` o `waiting_input`) →
      madre refleja el estado agregado correcto.
- [ ] En la UI (`/projects/:slug`), la madre con subtasks pending
      muestra `running`, no `done`.
- [ ] Codex-reviewer ejecutado.

## Riesgos conocidos

- **Race: dos subtasks hermanas terminando casi a la vez.** Ambas
  pueden entrar a `_maybe_promote_parent` en paralelo. Mitigación:
  la función es idempotente (check `parent.status in TERMINAL` al
  inicio), así que el segundo caller ve la madre ya promocionada
  y return. No hay corrupción.
- **Subtask en `waiting_input`:** el parent NO promociona hasta
  que todas las hijas estén terminales. Si una hija queda
  waiting_input, la madre sigue `running` indefinidamente hasta
  que el humano responda y la hija complete. Correcto.

## Notas para el implementador

- El código del split (hoy `task.status = "done"` tras emitir
  triage_split) vive en `triage.py` o en `executor/core.py` —
  localizarlo exactamente y quitar esa línea. Emitir TaskEvent
  `status_changed queued → running` en su lugar si no está ya.
- `_maybe_promote_parent` vive en `executor/core.py`, no en
  `tasks.py`, porque es parte del ciclo del executor.
- Commits sugeridos:
  1. `refactor(triage): leave parent in running after split`
  2. `feat(executor): promote parent when all subtasks terminal`
  3. `test: parent promotion aggregation rules`
