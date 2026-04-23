# PR-V1-12a — Triage module (pure + unit tests)

**Semana:** 3
**Esfuerzo:** M
**Depende de:** PR-V1-11c mergeado. Supersede junto con 12b a
`PR-V1-12-triage-planner.md`.

## Qué

Primer PR del split. Entrega el **módulo `triage.py` puro**, con
función pública `triage_task(project, task) -> TriageDecision`,
dataclass `TriageDecision`, excepción `TriageError`, y prompt
template. El módulo **existe, compila, y tiene 3 unit tests verdes**
pero **NO se invoca desde el executor** — ese wiring es PR-V1-12b.

## Por qué

Split a mitad del combinado original para respetar el hard-cap 400
de Semana 3. 12a entrega una unidad testeable de verdad (mock del
adapter + parsing); 12b hace el wiring mínimo encima. Dos PRs
independientes, cada uno bajo cap.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── triage.py                           # nuevo, ≤160 LOC
└── tests/
    └── test_triage.py                      # nuevo, 3 casos unit
```

**HARD-CAP 400 LOC netas código+tests.** Proyección: ~260 LOC.
Si excedes, PARAS.

## Fuera de scope (explícito)

- **No hay integración en executor.** Es 12b. El módulo queda
  como "código vivo pero dead" hasta que 12b lo conecte. Aceptado
  como costo del split.
- **No se extiende el fake CLI.** Los unit tests mockean el adapter
  directamente con `monkeypatch` (`ClaudeCodeAdapter.iter_events`,
  `.wait`, `.close`). Evitamos inflar fake CLI para luego tirarlo.
- **No se tocan tests legacy** (`test_adapter.py`, `test_executor.py`).
  Siguen verdes porque no hay cambio de flujo.
- **No hay HANDBOOK section del módulo completo.** Una sección
  mínima ("Triage module (PR-V1-12a)") con el contrato y que apunta
  a 12b para la integración. HANDBOOK sigue fuera del cap.
- **No se toca adapter ni verification ni frontend.**

## Dependencias nuevas

- **Ninguna.** `json`, `re`, `dataclasses`, y el `ClaudeCodeAdapter`
  existente para runtime; en tests, mocks sobre esa clase.

## Contrato funcional

### `TriageDecision` (dataclass frozen)

```python
@dataclass(frozen=True)
class TriageDecision:
    kind: str                        # "execute" | "split"
    subtasks: list[str]              # vacío si kind=="execute"
    rationale: str                   # texto del CLI, para debug
    raw_output: str                  # último bloque textual, para logs
```

### `TriageError(Exception)`

Se lanza cuando:
- JSON inválido o no presente en la respuesta.
- Shape inválido (falta `decision`, tipo incorrecto, `decision`
  fuera de `{"execute","split"}`, `subtasks` no lista, etc.).
- `decision == "execute"` pero `subtasks` no vacío (incoherencia).

Mensaje `str(exc)` debe ser legible para logs (primeros 200 chars
del motivo).

### `triage_task(project, task) -> TriageDecision`

Firma exacta. Efectos:

1. Construye el prompt con `_build_triage_prompt(task, project)` —
   template idéntico al del brief original §"Prompt" (ver §
   "Prompt template" abajo).
2. Instancia `ClaudeCodeAdapter(cli_path=resolve_cli_path(),
   cwd=project.local_path, prompt=<prompt>, timeout=180)`.
3. **Consume** `iter_events()` en memoria (lista acumulador). **NO
   persiste** `run_events` — el triage no es un Run almacenado.
4. Llama `adapter.wait()`; verifica `adapter.outcome == "cli_ok"`
   y `adapter.exit_code == 0`; si no → `TriageError` con el
   outcome del adapter en el mensaje.
5. Extrae el texto del último evento significativo:
   - Prioridad: `event_type == "result"` con `payload.result` o
     `payload.text`; si no, último `event_type == "assistant"`
     concatenando `content[].text` de bloques `type:"text"`.
6. Llama `_parse_triage_json(text) -> dict` que:
   - Busca ```json fence``` con
     `re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)`.
   - Si no matchea, busca el primer objeto JSON balanceado
     (stack-based match) empezando por `{`.
   - Si ninguno → `TriageError`.
   - `json.loads` del contenido.
7. `_validate_shape(parsed) -> TriageDecision`:
   - `decision ∈ {"execute","split"}`, `subtasks: list[str]`,
     `rationale: str`.
   - `decision=="execute"` ⇒ `subtasks == []`.
   - `decision=="split"` ⇒ `len(subtasks) >= 1`, todos no vacíos.
   - Si falla cualquier check → `TriageError(msg)`.
8. `adapter.close()` en `finally` para no dejar procesos huérfanos
   (misma semántica que run_adapter).

### Prompt template

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

**Keyword crítico** para el fake CLI futuro (12b): la frase
`"triage agent for Niwa"` aparece literalmente en el prompt. 12b
lo usará para keyword-dispatch.

## Tests

### Nuevos — `tests/test_triage.py` (3 casos)

Todos los casos **mockean `ClaudeCodeAdapter`** via monkeypatch.
Helper interno `_mock_adapter(monkeypatch, *, events, outcome="cli_ok",
exit_code=0)` que parchea la clase para que `iter_events` yield
una lista dada y `wait`/`outcome`/`exit_code` devuelvan lo pedido.

1. `test_decision_execute_parsed_from_json_fence` — adapter
   yield-ea un `assistant` con text `"```json\n{\"decision\":\"execute\",
   \"subtasks\":[], \"rationale\":\"single change\"}\n```"`.
   `triage_task(project, task)` devuelve
   `TriageDecision(kind="execute", subtasks=[],
   rationale="single change", raw_output=...)`.
2. `test_decision_split_with_subtasks_parsed` — adapter yield-ea
   ```json fence``` con `{"decision":"split",
   "subtasks":["one","two"], "rationale":"two areas"}`.
   Resultado `kind="split"`, `subtasks==["one","two"]`,
   `rationale="two areas"`.
3. `test_invalid_json_raises_triage_error` — adapter yield-ea
   texto sin JSON parseable (p. ej. `"I refuse to answer"`).
   `triage_task` lanza `TriageError` con mensaje informativo.

**Baseline tras 12a:** 77 → **80 passed**.

## Criterio de hecho

- [ ] `cd v1/backend && pytest -q tests/test_triage.py` → 3 passed.
- [ ] `pytest -q` completo → 80 passed, 0 regresiones (77 actuales
  + 3 nuevos).
- [ ] `from app.triage import triage_task, TriageDecision,
  TriageError` funciona sin errores.
- [ ] El módulo NO está importado desde `executor/core.py` — queda
  para 12b. Verificable con `grep triage v1/backend/app/executor/`
  = sin resultados.
- [ ] HANDBOOK sección mínima "Triage module (PR-V1-12a)" con:
  contrato público, prompt template, nota "integración en 12b".
- [ ] Codex ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests ≤ **400**. Proyección ~260.

## Riesgos conocidos

- **Código vivo no invocado**: durante la ventana 12a-merged / 12b-open,
  el módulo existe pero no hace nada. Cost del split.
- **Mock del adapter**: los tests no ejercen la ruta de spawn de
  subprocess. 12b los integration tests la cubren.
- **Parser JSON frágil**: si el CLI real decide no usar fence,
  el parser fallback (primer objeto balanceado) debe cubrirlo.
  Añade **caso extra** si cabe en LOC:
  `test_decision_plain_json_without_fence` — `"{\"decision\":\"execute\",
  \"subtasks\":[], \"rationale\":\"ok\"}"` (sin fence) → parsea OK.

## Notas para Claude Code

- Commits sugeridos (3):
  1. `feat(triage): decision dataclass and error type`
  2. `feat(triage): prompt template and json parsing`
  3. `test(triage): unit cases for execute, split, invalid`
  4. `docs(v1): handbook triage module section` (si caben bajo
     cap, sino merge con 3).
- `triage.py` plano: una función pública + dataclasses. Nada de
  clases con state. `_parse_triage_json` y `_validate_shape` son
  privadas.
- Si decides usar `sys.executable` para algo, innecesario —
  `ClaudeCodeAdapter` ya gestiona binarios.
- Si parser se complica, apóyate en:
  ```python
  import re
  m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
  if m:
      return json.loads(m.group(1))
  # fallback: first balanced {...}
  ```
- **Si algo del brief es ambiguo, PARA y reporta.**
