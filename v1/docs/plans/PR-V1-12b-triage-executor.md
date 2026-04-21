# PR-V1-12b — Triage executor integration

**Semana:** 3
**Esfuerzo:** M
**Depende de:** PR-V1-12a mergeado (módulo `triage.py` existe).

## Qué

Segunda mitad del split. **Wiring**: `executor/core.py` invoca
`triage_task(project, task)` antes de `prepare_task_branch`.
Dispatcha a ejecución normal o a split según la decisión. Fake CLI
extendido con keyword-dispatch para que los tests de integración
sean E2E reales. 2 stubs añadidos a tests legacy que ahora correrían
triage primero y desviarían su flujo.

Tras este PR, cada task encolada pasa por triage antes de ejecutarse.

## Por qué

Split a mitad del combinado original. 12a entregó el módulo puro;
12b lo enchufa. Esta parte es pura fontanería + integration tests.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── executor/
│       └── core.py                         # invoca triage, dispatcha split/execute/failure
└── tests/
    ├── test_executor.py                    # +2 integration (execute, split)
    ├── test_adapter.py                     # +stub triage en 2 legacy tests
    └── fixtures/
        └── fake_claude_cli.py              # keyword-dispatch "triage agent for Niwa"
```

**HARD-CAP 400 LOC netas código+tests.** Proyección: ~240 LOC. Si
excedes, PARAS.

## Fuera de scope (explícito)

- **No se toca el módulo `triage.py`** (12a lo fijó).
- **No hay validación semántica de subtasks** creadas (trust CLI).
- **No hay protección contra recursión** (subtasks pasan por triage
  otra vez cuando salen del queue). Documentado como riesgo.
- **No se toca el adapter, el verification, ni el frontend.**
- **No hay UI para parent/subtask**.
- **No hay env var `NIWA_SKIP_TRIAGE`** — todo task pasa por triage.
- **No hay retry**. Fallo de triage → task `failed` con
  `outcome="triage_failed"`.

## Dependencias nuevas

- **Ninguna.**

## Contrato funcional

### Integración en `executor/core.py → process_pending`

```python
from ..triage import triage_task, TriageError

# ... existing claim_next_task loop ...
while True:
    task = claim_next_task(session)
    if task is None:
        break

    project = session.get(Project, task.project_id)

    # NUEVO: triage antes de cualquier otro paso
    try:
        decision = triage_task(project, task)
    except TriageError as exc:
        _finalize_triage_failure(session, task, project, reason=str(exc))
        processed += 1
        continue

    if decision.kind == "split":
        _apply_split(session, task, decision)
        processed += 1
        continue

    # decision.kind == "execute" → flujo existente
    run_adapter(session, task)  # ya contiene prepare_task_branch + spawn + verify
    processed += 1
    logger.info("ran adapter for task_id=%s", task.id)
```

### `_apply_split(session, task, decision)`

1. Para cada `title` en `decision.subtasks`:
   ```python
   session.add(Task(
       project_id=task.project_id,
       parent_task_id=task.id,
       title=title,
       description="",            # vacío — triage no lo provee
       status="queued",
   ))
   ```
2. `session.flush()` para obtener `id` de cada subtask (los
   necesita el payload del TaskEvent).
3. Parent task: `task.status = "done"`, `task.completed_at =
   datetime.now(tz=timezone.utc)`.
4. Escribe **`TaskEvent(kind="message", payload_json=json.dumps(
   {"event": "triage_split", "subtask_ids": [...], "rationale":
   decision.rationale}))`** — **resolución Opción B del orquestador**:
   no se puede usar `kind="triage_split"` porque SPEC §3 restringe
   el enum. El marker va en el payload.
5. Escribe `TaskEvent(kind="status_changed",
   payload_json=json.dumps({"from":"running","to":"done"}))`.
6. `session.commit()`.

### `_finalize_triage_failure(session, task, project, reason)`

1. Crea un `Run` sintético:
   ```python
   run = Run(
       task_id=task.id,
       status="failed",
       model="claude-code",
       started_at=datetime.now(tz=timezone.utc),
       finished_at=datetime.now(tz=timezone.utc),
       outcome="triage_failed",
       artifact_root=project.local_path if project else "",
       exit_code=None,
   )
   session.add(run)
   session.flush()
   ```
2. Escribe `RunEvent(event_type="error",
   payload_json=json.dumps({"reason": reason[:500]}))`.
3. Escribe `RunEvent(event_type="failed", payload_json=None)` para
   el lifecycle terminal.
4. Task → `failed`, `completed_at` no se setea (no fue success).
5. Escribe `TaskEvent(kind="verification",
   payload_json=json.dumps({"error_code": "triage_failed",
   "outcome": "triage_failed"}))` — consistente con el flujo de
   verification del adapter.
6. `TaskEvent(kind="status_changed",
   payload_json=json.dumps({"from":"running","to":"failed"}))`.
7. Commit.

### Fake CLI keyword-dispatch

`v1/backend/tests/fixtures/fake_claude_cli.py`:
- Lee `FAKE_CLAUDE_TRIAGE_JSON` env var.
- Si el prompt (stdin) contiene el literal `"triage agent for Niwa"`:
  - Si `FAKE_CLAUDE_TRIAGE_JSON` está set, emite ese JSON como texto
    del último `assistant` (en fence ```json...```).
  - Si no está set, emite un JSON **execute con subtasks vacío**
    por defecto (permite que tests legacy no se rompan).
  - Termina con exit 0.
- Si el prompt NO contiene ese keyword, comportamiento actual
  (stream del script `FAKE_CLAUDE_SCRIPT` + `FAKE_CLAUDE_EXIT`, etc.).

### Stubs en tests legacy

Dos tests legacy ya no pueden correr sin intervención:
- `test_runs_fail_on_git_setup_error` — si triage corre primero,
  falla con cli_not_found ANTES de ejercer `git_setup_failed`.
- `test_adapter_binary_missing_fails_fast` — análogo.

**Fix**: en cada uno, `monkeypatch` `triage_task` antes del test
para devolver `TriageDecision(kind="execute", subtasks=[],
rationale="stub", raw_output="")`. ~5 líneas por test.

## Tests

### Nuevos integration — `tests/test_executor.py` (2 casos)

1. `test_process_pending_executes_when_triage_says_execute`:
   - Fake CLI con `FAKE_CLAUDE_TRIAGE_JSON` emitiendo
     `{"decision":"execute","subtasks":[],"rationale":"ok"}`.
   - Task encolada, `process_pending` ejecuta.
   - Asserts: task pasa por flujo normal
     (`prepare_task_branch` + run adapter + verify) y termina
     `done`. `run.outcome == "verified"`. `task.branch_name` no
     None.
2. `test_process_pending_splits_when_triage_says_split`:
   - Fake CLI emite `{"decision":"split","subtasks":["one","two"],
     "rationale":"two areas"}`.
   - Task encolada, `process_pending` ejecuta.
   - Asserts:
     - Parent task `status=="done"`, `completed_at` set.
     - **Cero Runs** creados sobre la parent (no corrió adapter).
     - 2 subtasks nuevas en DB con `parent_task_id=parent.id`,
       `status=="queued"`, `project_id=parent.project_id`.
     - `TaskEvent(kind="message")` con
       `payload.event=="triage_split"` y `payload.subtask_ids`
       coincidentes con las 2 subtasks creadas.

**Baseline tras 12b:** 80 → **82 passed** (12a dio 80; +2 integration).

## Criterio de hecho

- [ ] `pytest -q` completo → 82 passed, 0 regresiones.
- [ ] Cualquier task encolada invoca `triage_task` antes de
  `prepare_task_branch`.
- [ ] Triage `execute` → flujo normal activo.
- [ ] Triage `split` con N subtasks → parent `done` sin run, N
  subtasks `queued`, TaskEvent `message` con payload marker.
- [ ] Triage failure → task `failed`, Run sintético con
  `outcome="triage_failed"`, TaskEvent verification.
- [ ] Los 2 tests legacy con stub de triage siguen verdes.
- [ ] HANDBOOK sección "Triage executor integration (PR-V1-12b)"
  con pipeline actualizado, flujo split vs execute vs failure.
- [ ] Codex ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests ≤ **400**. Proyección ~240.

## Riesgos conocidos

- **Coste**: cada task = 2 invocaciones CLI (triage + ejecución o
  triage sin ejecución). MVP asume valor > coste.
- **Recursión sin límite**: subtasks pasan por triage al salir del
  queue. Si triage vuelve a splitear, se crea un árbol.
  Documentado. Si aparece en uso real, follow-up con depth counter.
- **Keyword-dispatch fake CLI**: si un test futuro usa la frase
  `"triage agent for Niwa"` en su prompt accidentalmente,
  dispatcharía al branch de triage. Keyword específico minimiza
  riesgo.
- **Tests legacy stub**: `monkeypatch.setattr("app.executor.core.triage_task",
  lambda p, t: TriageDecision(...))`. Minimal intrusion.

## Notas para Claude Code

- Commits sugeridos (4):
  1. `feat(executor): invoke triage before prepare_task_branch`
  2. `test(fixtures): triage keyword dispatch in fake cli`
  3. `test(executor): integration for triage execute and split`
  4. `test(adapter): stub triage in two legacy tests`
  5. `docs(v1): handbook triage executor integration`
- Ordena la integración para que el bloque nuevo quede
  self-contained en `process_pending`; evita mezclar con lógica
  de `run_adapter`. Helpers `_apply_split` y `_finalize_triage_failure`
  en `executor/core.py` (no nuevo módulo).
- Si el stub de legacy tests requiere más de 10 LOC por test,
  considera extraerlo a un helper en `conftest.py` (fixture
  `stub_triage_execute`).
- **Si algo del brief es ambiguo, PARA y reporta.**
