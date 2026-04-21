# PR-V1-12 — Triage planner (single-call decision)

**Semana:** 3
**Esfuerzo:** M
**Depende de:** PR-V1-11c mergeado (verification §5 completa).

## Qué

Módulo `triage.py` que, antes de invocar el adapter para ejecutar
una task, hace **una única llamada al CLI de Claude Code** con un
prompt dedicado que pide una decisión binaria:

- `"execute"` — la task se ejecuta como hoy (el executor procede
  con `prepare_task_branch` + `run_adapter`).
- `"split"` — la task se descompone en N subtasks. El executor crea
  esas subtasks (cada una `parent_task_id = parent.id`, status
  `queued`), marca la parent task `done` sin correr adapter, y
  escribe un `TaskEvent(kind="triage_split", payload={...})`.

Sin retries, sin loops, sin recursión explícita. Si el triage CLI
falla (timeout, exit ≠ 0, JSON inválido), la task termina `failed`
con `outcome="triage_failed"`.

## Por qué

SPEC §1: "Decide si la tarea se ejecuta directa o se descompone en
subtareas. Sin LLM de más: una sola llamada, decisión binaria."
SPEC §4: `[triage] → decide: execute|split (1 LLM call)` es el
primer paso del pipeline. Hasta ahora saltábamos directo a execute;
este PR cierra ese gap.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── triage.py                           # nuevo, ~120 LOC
│   └── executor/
│       └── core.py                         # triage antes de prepare_task_branch
└── tests/
    ├── test_triage.py                      # nuevo, 3 casos unit
    ├── test_executor.py                    # 1-2 casos integration (execute + split)
    └── fixtures/
        └── fake_claude_cli.py              # +env FAKE_CLAUDE_TRIAGE_JSON si cabe
```

**HARD-CAP: 400 LOC netas código+tests** (sin HANDBOOK). Si
proyectas exceder, PARAS y reportas.

## Fuera de scope (explícito)

- **No hay retry.** Un triage fallido marca la task `failed` sin
  reencolar.
- **No hay validación semántica de subtasks.** Trust the CLI — si
  genera subtasks absurdas, es responsabilidad del usuario y del
  siguiente PR iterar.
- **No hay límite de profundidad** de splits (una subtask puede
  volver a splitearse cuando salga del queue). Si esto crea
  problemas, follow-up.
- **No se toca el contrato de verificación.** El adapter de
  verificación (post-run) sigue igual.
- **No se toca la UI.** La UI actual no muestra la relación
  parent/subtask — follow-up.
- **No hay cancelación en vivo** del triage CLI.
- **No hay modo "skip triage"** (env var / config). Todo task pasa
  por triage. Si perf es problema, follow-up con cache o heurística.

## Dependencias nuevas

- **Ninguna.** Stdlib + `ClaudeCodeAdapter` existente.

## Contrato funcional

### `TriageDecision` (dataclass)

```python
@dataclass(frozen=True)
class TriageDecision:
    kind: str                        # "execute" | "split"
    subtasks: list[str]              # título de cada subtask; vacío si execute
    rationale: str                   # texto libre del CLI, para debug
    raw_output: str                  # último bloque result/text para logs
```

### Función pública: `triage_task(project, task) -> TriageDecision`

Invoca `ClaudeCodeAdapter` con:

- `cwd` = `project.local_path` (el adapter necesita un dir válido,
  pero el prompt NO le pide modificar ficheros).
- `prompt` = un bloque estructurado (ver abajo) que pide JSON de
  decisión en la respuesta.
- `timeout` = 180 s (más corto que el run normal; triage es
  rápido).

Parseo de la respuesta:

1. Lee los `run_events` recogidos por el adapter (el adapter los
   yield-ea; recogemos en memoria, **no los persistimos** — el
   Run de triage NO se almacena).
2. Encuentra el último `assistant` o `result` significativo.
3. Extrae el texto y busca un bloque JSON (entre fences
   ` ```json ... ``` ` o a pelo). Parsea con `json.loads`.
4. Valida shape: `{"decision": "execute" | "split", "subtasks":
   [str, ...], "rationale": str}`. Si `decision="execute"`,
   `subtasks` debe ser `[]`.
5. Si el JSON no parsea o el shape es inválido → `TriageError`
   con mensaje; el caller lo traduce a `outcome="triage_failed"`.

### Prompt usado (template exacto)

```
You are a triage agent for Niwa. Decide if this task should be
executed directly or split into subtasks.

# Task
Title: {task.title}
Description: {task.description or "(none)"}
Project kind: {project.kind}
Project path: {project.local_path}

# Instructions
- If the task is a single cohesive change (one bug fix, one
  feature, one refactor) → decision "execute".
- If the task requires multiple independent changes that would
  naturally land in separate PRs → decision "split", and list
  the subtask titles (short, imperative, in English).
- Do NOT modify any files. Your only output is the JSON below.

# Response format (JSON only, in a ```json fence)
{
  "decision": "execute" | "split",
  "subtasks": ["title1", "title2", ...],
  "rationale": "one sentence explaining the choice"
}
```

### Integración en `executor/core.py`

Dentro de `process_pending`, tras `claim_next_task` y antes de
`prepare_task_branch`:

```python
try:
    decision = triage_task(project, task)
except TriageError as exc:
    # marca fallo y continúa con la siguiente task
    _finalize_triage_failure(session, task, reason=str(exc))
    continue

if decision.kind == "split":
    _apply_split(session, task, decision)
    continue  # parent task done; subtasks quedan en el queue

# decision.kind == "execute" → sigue el flujo actual (prepare_task_branch, run_adapter)
```

### `_apply_split(session, task, decision)`

1. Crea N `Task(parent_task_id=task.id, title=subtask_title,
   description=..., status="queued", project_id=task.project_id)`.
2. Marca la parent task `status="done"`, `completed_at=now`.
3. Escribe `TaskEvent(task_id=parent.id, kind="triage_split",
   payload_json=json.dumps({"subtask_ids":[...], "rationale":
   decision.rationale}))`.
4. Escribe `TaskEvent(task_id=parent.id, kind="status_changed",
   payload_json={"from":"running", "to":"done"})`.
5. Commit.

### `_finalize_triage_failure(session, task, reason)`

1. Crea un `Run(task_id=task.id, status="failed",
   model="claude-code", outcome="triage_failed",
   artifact_root=project.local_path)` — para que aparezca en
   `GET /api/tasks/{id}/runs`.
2. Escribe `RunEvent(event_type="error", payload={"reason":reason[:500]})`.
3. Task → `failed`, `TaskEvent(kind="verification", payload.error_code="triage_failed")`
   (reutilizamos el `verification` kind porque el UI futuro lo
   reconoce — si quieres un `kind="triage"` nuevo, OK, pero
   consistencia con lo existente es preferida para MVP).

## Tests

### Nuevos unit — `test_triage.py` (3 casos)

1. `test_decision_execute_parsed_from_json_fence` — mock
   adapter que yield-ea un `assistant` con texto
   ` ```json\n{"decision":"execute", "subtasks":[], "rationale":"single change"}\n``` `.
   `triage_task` devuelve `kind="execute"`, `subtasks=[]`,
   `rationale="single change"`.
2. `test_decision_split_with_subtasks_parsed` — mock con
   ` ```json\n{"decision":"split", "subtasks":["one","two"], "rationale":"two areas"}\n``` `.
   Devuelve `kind="split"`, `subtasks=["one","two"]`.
3. `test_invalid_json_raises_triage_error` — mock con texto sin
   JSON parseable. `triage_task` lanza `TriageError`.

### Nuevos integration en `test_executor.py` (1-2 casos)

1. `test_process_pending_executes_when_triage_says_execute` —
   Fake CLI con `FAKE_CLAUDE_TRIAGE_JSON` (nueva env) que emite
   el JSON execute. Tras `process_pending`, task pasa por el
   flujo normal (prepare_branch + adapter + verify) y termina
   `done`.
2. `test_process_pending_splits_when_triage_says_split` —
   Fake CLI emite JSON split con 2 subtasks. Tras
   `process_pending`: parent task `done` SIN run del adapter
   (solo `TaskEvent(kind="triage_split")`); 2 subtasks con
   `parent_task_id=parent.id`, `status="queued"`.

La extensión del fake CLI: nueva env `FAKE_CLAUDE_TRIAGE_JSON`
que sustituye la salida del fake cuando el prompt **contiene el
keyword "triage agent for Niwa"** (el template lo incluye). Si no
contiene, fake funciona como antes (stream del script normal). Esto
permite que una sola invocación del executor pueda servir dos
scripts distintos (uno para triage, otro para ejecución) sin
inflar infra de tests.

**Alternativa más simple si la anterior infla LOC**: que el test
mockee `triage_task` directamente con un `@patch` en vez de pasar
por el fake CLI. Menos end-to-end pero más barato.

### Baseline tras PR-V1-12

- Backend: **~82 passed** (77 actuales + 3 unit + 2 integration).
- Frontend: 6 sin cambios.

## Criterio de hecho

- [ ] `pytest -q tests/test_triage.py` → 3 passed.
- [ ] `pytest -q tests/test_executor.py` → todos verdes (legacy +
  2 nuevos).
- [ ] `pytest -q` completo → ≥82 passed, 0 regresiones.
- [ ] Una task cuyo triage CLI devuelve `split` con 2 subtasks:
  parent `done`, 2 subtasks en `queued` con `parent_task_id`
  correcto; NO hay Run del adapter sobre la parent.
- [ ] Una task cuyo triage CLI devuelve `execute`: flujo normal
  (prepare_branch + run + verify) → task `done`.
- [ ] Una task cuyo triage CLI emite JSON inválido: task `failed`,
  `Run.outcome="triage_failed"`, TaskEvent con error_code.
- [ ] HANDBOOK sección "Triage planner (PR-V1-12)": prompt
  template, parseo, integración, modos de fallo.
- [ ] Codex-reviewer ejecutado. Blockers resueltos antes del
  merge.
- [ ] LOC netas código+tests ≤ **400**.

## Riesgos conocidos

- **Coste**: cada task dispara ahora 2 invocaciones del CLI
  (triage + ejecución o triage sin ejecución). Para usuarios con
  queries cortas, triage es overhead. MVP asume que el valor del
  split vale la llamada extra.
- **Subtasks también pasan por triage**, lo que permite recursión
  accidental. MVP no protege — si se observa bucle, follow-up.
- **Prompt parsing frágil**: si el CLI no devuelve JSON en fence,
  el parser falla. El prompt es explícito pidiendo fence, pero
  hay margen. `TriageError` captura los casos.
- **Subtask heredada campos mínimos**: el prompt devuelve solo
  `title`. `description` de la subtask queda vacío/igual al de la
  parent (decisión: vacío, el triage no lo provee). Documentar.
- **`FAKE_CLAUDE_TRIAGE_JSON` keyword-based dispatch** puede
  desestabilizar fakes existentes si algún test futuro usa el
  keyword "triage" accidentalmente. Keyword elegido suficientemente
  específico (`"triage agent for Niwa"`).

## Notas para Claude Code

- Commits sugeridos (5):
  1. `feat(triage): decision dataclass and public entry point`
  2. `feat(triage): prompt template and json parsing`
  3. `feat(executor): invoke triage before prepare_task_branch`
  4. `test(fixtures): triage json env for fake cli`
  5. `test(triage): unit + executor integration suites`
- Mantén `triage.py` plano — nada de clases que mantengan state.
  Una función pública + dataclasses.
- Si el parser del JSON se complica (fence detection, greedy vs
  lazy), apóyate en `re.search(r"```json\s*(\{.*?\})\s*```", text,
  re.DOTALL)` como pase 1 y `json.loads` del contenido del grupo 1.
  Si no matchea, pase 2: buscar el primer `{...}` balanceado.
  Si ninguno, `TriageError`.
- Reutiliza `ClaudeCodeAdapter.close()` — misma semántica que para
  el run normal.
- Si el volumen excede cap, prefiere **mockear `triage_task`** en
  los tests de integración (vía `monkeypatch.setattr`) en vez de
  extender el fake CLI. Más simple.
- Si algo del brief es ambiguo, **PARA y reporta** antes de
  improvisar.
