# PR-V1-11a — Verification E1+E2 + skeleton + executor integration

**Semana:** 3
**Esfuerzo:** M
**Depende de:** PR-V1-10 (Semana 2 cerrada). Supersede junto con
11b+11c a `PR-V1-11-verification.md`.

## Qué

Primer PR del split de verificación. Entrega:

1. Skeleton del módulo `verification/` (dataclass `VerificationResult`,
   `__init__.py` con re-exports, orquestador `core.py` limitado a
   E1+E2).
2. **E1 — Exit code**: `run.exit_code == 0` y el outcome del adapter
   es `cli_ok`. Fallo → `error_code="exit_nonzero"` o `"adapter_failure"`.
3. **E2 — Stream terminado limpiamente**: inspecciona los
   `run_events` ordenados por `id`; el último evento significativo
   (ignorando lifecycle sintéticos `started|completed|failed|error`
   y heartbeats) debe ser `result/success` o `assistant` sin acabar
   en `?`. Fallos: `tool_use_incomplete`, `question_unanswered`,
   `empty_stream`.
4. Integración en `executor/core.py`: `verify_run(...)` se invoca
   entre `adapter.wait()` y `_finalize`. Si pasa → outcome
   `"verified"`. Si falla → outcome `"verification_failed"` +
   `error_code`. `_finalize` acepta `error_code` opcional y escribe
   `TaskEvent(kind="verification", payload_json={...})` si no es
   None. `run.verification_json = json.dumps(result.evidence)`.
5. Migración de tests legacy (`test_adapter.py`, `test_executor.py`,
   `test_runs_api.py`) al nuevo outcome `"verified"` en vez de
   `"cli_ok"`.

E3+E4+E5 se implementan stub en `verify_run`: pasan vacuamente
cuando E1+E2 pasan. Cada uno llega en 11b/11c.

## Por qué

Cierra ya el bug corazón del MVP: una task no se marca `done` si
el adapter acabó con pregunta sin responder, tool_use sin
resultado, o stream vacío. Es la ganancia más grande respecto a
v0.2 y encaja en ≤400 LOC.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── verification/
│   │   ├── __init__.py                   # re-exports: verify_run, VerificationResult
│   │   ├── models.py                     # dataclass + evidence fields
│   │   ├── stream.py                     # E2 analyzer (solo E2)
│   │   └── core.py                       # orquestador: E1 → E2 → (stubs E3/E4/E5)
│   └── executor/
│       └── core.py                       # integra verify_run antes de _finalize;
│                                         # _finalize acepta error_code opcional
└── tests/
    ├── verification/
    │   ├── __init__.py
    │   └── test_stream.py                # 4 casos del brief original §"Stream"
    ├── fixtures/
    │   └── fake_claude_cli.py            # +env FAKE_CLAUDE_TOUCH (escribe durante ejecución)
    ├── test_adapter.py                   # outcome rename: cli_ok → verified
    ├── test_executor.py                  # outcome rename + multi-task fix (git_project per task)
    ├── test_runs_api.py                  # outcome rename
    └── test_verification_integration.py  # 2 casos E2E (happy + question_unanswered)
```

**HARD-CAP: 400 LOC netas de código + tests.** Si excedes, **paras**
y reportas al orquestador. NO aceptas "opción A".

## Fuera de scope (explícito)

- **No hay E3 (artefactos en cwd) ni E4 (artefactos fuera de cwd).**
  `verify_run` los trata como "skip" y la evidencia los marca
  `tests_ran=False` / `git_available=None` / equivalente. Llegan
  en PR-V1-11b.
- **No hay E5 (tests del proyecto).** Llega en PR-V1-11c.
- **No hay triage planner** (PR-V1-12).
- **No hay modo safe con PR manual** (PR-V1-13).
- **No hay auto-commit / auto-push** tras verificar OK.
- **No hay retry automático** tras `verification_failed`.
- **No se toca el adapter** ni el frontend.

## Dependencias nuevas

- **Ninguna.** Solo stdlib (`json`, `dataclasses`).

## Contrato funcional (solo lo implementado en 11a)

### `VerificationResult` (final forma, lista para 11b/11c)

```python
@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    outcome: str                    # "verified" | "verification_failed"
    error_code: str | None
    evidence: dict[str, Any]        # JSON-serializable snapshot
```

### `verify_run(session, run, task, project, cwd, *, adapter_outcome, exit_code) -> VerificationResult`

Finding 1 del brief original: `run.outcome`/`run.exit_code` se
escriben en `_finalize` posterior, por lo que el adapter lo invoca
pasando `adapter_outcome` + `exit_code` explícitamente como kwargs.

Orden de chequeo **E1 → E2 → (stubs E3/E4/E5)**, cortocircuitando
al primer fallo para señalar causa exacta.

### E1 — Exit code

- `adapter_outcome == "cli_ok"` y `exit_code == 0` → E1 pasa.
- `adapter_outcome == "cli_nonzero_exit"` → `error_code="exit_nonzero"`.
- `adapter_outcome ∈ {"cli_not_found", "timeout", "adapter_exception"}`
  → `error_code="adapter_failure"`.

Evidence populada:
```json
{"exit_ok": true, "exit_code": 0, "adapter_outcome": "cli_ok"}
```

### E2 — Stream terminado limpiamente

Input: `run_events` del run, ordenados por `id` ASC.

Pasos:
1. Filtra eventos "significativos": descarta `event_type` en
   `{"started","completed","failed","error"}` (lifecycle sintéticos
   escritos por el executor/finalize) y comentarios de heartbeat
   (no se almacenan, así que no aparecen — defensa por si acaso).
2. Si la lista filtrada es vacía → `error_code="empty_stream"`.
3. Último evento significativo:
   - Si `event_type == "result"`: mira `payload.subtype` o campo
     equivalente; si indica terminación normal (`"success"`,
     `"end_turn"`) → E2 pasa. Si no, considerar como normal también
     (MVP trust the CLI).
   - Si `event_type == "assistant"`: extrae el texto del mensaje;
     si acaba en `?` (strip blancos) → `error_code="question_unanswered"`.
     Si no → E2 pasa.
   - Si `event_type == "tool_use"`: **falla** con
     `error_code="tool_use_incomplete"` (no hubo `tool_result`
     después).

Evidence populada:
```json
{
  "stream_terminated_cleanly": true,
  "last_event_type": "result",
  "last_event_subtype": "success",
  "significant_event_count": 7
}
```

Extracción del texto del assistant: el stream-json de Claude Code
emite `payload.message.content = [{type:"text", text:"..."}, ...]`.
Concatenar los `text` de todos los bloques `type:"text"` del último
assistant. Si el payload no tiene esa forma, aceptar como cierre
normal (el adapter puede evolucionar; MVP trust).

### Integración en `executor/core.py`

```python
from ..verification import verify_run

try:
    for event in adapter.iter_events():
        _write_event(session, run, event)
    adapter.wait()
    adapter_outcome = adapter.outcome or "cli_ok"
    exit_code = adapter.exit_code
except Exception as exc:
    # ... idéntico a hoy ...

# --- nuevo: verificación ---
result = verify_run(
    session, run, task, project,
    cwd=artifact_root,
    adapter_outcome=adapter_outcome,
    exit_code=exit_code,
)
run.verification_json = json.dumps(result.evidence)
session.commit()

if result.passed:
    _finalize(session, task, run, outcome="verified", exit_code=exit_code)
else:
    _finalize(
        session, task, run,
        outcome=result.outcome,       # "verification_failed"
        exit_code=exit_code,
        error_code=result.error_code,
    )
```

`_finalize` firma extendida:
```python
def _finalize(
    session, task, run, *,
    outcome: str, exit_code: int | None,
    error_code: str | None = None,
) -> None:
    ...
    run.outcome = outcome  # "verified" | "verification_failed" | "cli_not_found" | ...
    run.exit_code = exit_code
    run.status = "completed" if outcome == "verified" else "failed"
    ...
    if error_code is not None:
        session.add(TaskEvent(
            task_id=task.id,
            kind="verification",
            message=None,
            payload_json=json.dumps({"error_code": error_code, "outcome": outcome}),
        ))
    ...
```

Success mapping:
- `outcome == "verified"` → run `completed`, task `done`.
- cualquier otro → run `failed`, task `failed`.

## Tests

### Nuevos backend — `tests/verification/test_stream.py` (4 casos)

1. `test_stream_terminated_with_result_success_passes` — stream con
   último significativo `result/success` → E2 passes,
   `error_code is None`.
2. `test_assistant_ending_in_question_fails_question_unanswered` —
   último `assistant` con texto `"...?"` → E2 falla
   `error_code="question_unanswered"`.
3. `test_tool_use_last_fails_incomplete` — último evento `tool_use`
   sin `tool_result` después → `error_code="tool_use_incomplete"`.
4. `test_empty_stream_fails_empty_stream` — stream sin eventos
   significativos → `error_code="empty_stream"`.

### `tests/test_verification_integration.py` (2 casos E2E)

Usa el fake CLI (extendido con `FAKE_CLAUDE_TOUCH`) + `git_project`
fixture de PR-V1-08.

1. `test_happy_path_run_verified` — fake emite stream con
   `result/success` final y escribe un fichero via
   `FAKE_CLAUDE_TOUCH` (finding #2). Tras el run:
   `run.outcome == "verified"`, `run.status == "completed"`,
   `task.status == "done"`, `run.verification_json` parseable con
   `exit_ok: true` + `stream_terminated_cleanly: true`.
2. `test_sad_path_question_unanswered` — fake emite stream cuyo
   último assistant acaba en `"?"`. Tras el run:
   `run.outcome == "verification_failed"`,
   `run.status == "failed"`, `task.status == "failed"`,
   `TaskEvent(kind="verification", payload.error_code="question_unanswered")`
   existe.

### Migración de tests legacy

- `test_adapter.py`: outcome rename `cli_ok` → `verified` en los
  asserts que dependían del outcome final del Run post-`_finalize`.
  Los tests que asertan sobre `adapter.outcome` (interna del
  adapter) **NO cambian** — siguen siendo `cli_ok` porque eso lo
  escribe el adapter antes del verify.
- `test_executor.py`: outcome rename + `git_project` por task en
  `test_process_pending_multiple_tasks` (finding #3).
- `test_runs_api.py`: outcome rename.

**Finding #2 aplicado**: `fake_claude_cli.py` acepta nueva env
`FAKE_CLAUDE_TOUCH` (lista separada por `:`) con paths a crear
durante la ejecución (antes de exit) para que E3/E4 vean
artefactos cuando se implementen en 11b. Para 11a solo se usa en
el test E2E happy path.

### Baseline tras 11a

- Backend: **65 passed** aprox (59 actuales + 4 stream + 2
  integration). 0 regresiones. Los tests legacy se migran, no suman.
- Frontend: 6 sin cambios.

## Criterio de hecho

- [ ] `cd v1/backend && pytest -q tests/verification/test_stream.py`
  → 4 passed.
- [ ] `pytest -q tests/test_verification_integration.py` → 2 passed.
- [ ] `pytest -q` completo → ≥65 passed, 0 regresiones.
- [ ] Un run con fake CLI que acaba con pregunta sin responder
  termina `task.status='failed'` con `error_code=question_unanswered`
  y `TaskEvent(kind='verification')` escrito.
- [ ] Un run exitoso tiene `run.verification_json` con al menos
  `exit_ok` + `stream_terminated_cleanly` populados.
- [ ] HANDBOOK actualizado con sección "Verification core
  (PR-V1-11a)" — diseño, outcomes, error_codes, evolución esperada
  en 11b/11c.
- [ ] Codex-reviewer ejecutado. Blockers resueltos en fixup antes
  del merge.
- [ ] Cero dependencias nuevas.
- [ ] LOC netas **código + tests** (sin HANDBOOK/STATE) ≤ **400**.
  Si excedes, **PARAS**.

## Riesgos conocidos

- **Texto del assistant puede variar**: el stream-json puede
  emitir varios content blocks (text + tool_use + text). La regla
  es: concatenar los bloques `type:"text"` del último evento
  assistant; strip whitespace; comparar `.endswith("?")`. Si el
  último assistant es solo tool_use sin text, el siguiente bloque
  tool_use se chequea con la regla "tool_use sin tool_result".
  Documentar este comportamiento en docstring.
- **Outcome rename puede romper suscripciones existentes** (si las
  hubiera). No las hay en v1; `outcome` se consume solo en
  `_finalize` y el API GET.
- **Stream vacío técnico**: un run que el adapter aborta antes de
  emitir algo tendrá 0 eventos significativos. Debe fallar
  `empty_stream` — confirmado.

## Notas para Claude Code

- **Reutiliza la implementación de referencia** del WIP commit
  `claude/v1-pr-11-verification` (local) para diseño y tests.
  NO hagas cherry-pick directo; el diff hay que recortarlo a E1+E2.
- Commits sugeridos (6):
  1. `feat(verification): result dataclass + public entry point`
  2. `feat(verification): E1 exit code analyzer`
  3. `feat(verification): E2 stream termination analyzer`
  4. `feat(executor): integrate verifier between adapter.wait() and finalize`
  5. `test(fixtures): fake cli touch env for mid-run artifacts`
  6. `test(verification): stream unit + integration suites`
- Si al implementar ves que la migración de tests legacy por si
  sola empuja por encima del cap (≥100 LOC solo por el outcome
  rename), reporta y pedimos split adicional. Pero no inventes
  otro split sin preguntar.
- **Si el brief es ambiguo, PARA y pregunta.** No improvises.
