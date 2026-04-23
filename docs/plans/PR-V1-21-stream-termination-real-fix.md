# PR-V1-21 — Verification: detectar pregunta abierta con stream real

**Tipo:** FIX (bug crítico de integración detectado en smoke real del MVP)
**Semana:** 6 (segundo PR)
**Esfuerzo:** S-M
**Depende de:** PR-V1-20 (recomendable tenerlo mergeado antes para
poder regenerar streams reales limpios)

## Qué

Reescribir `check_stream_termination` en `v1/backend/app/verification/
stream.py` para detectar correctamente "Claude terminó con una
pregunta sin responder" cuando el stream viene del Claude CLI real.
La versión actual (PR-V1-11a, PR-V1-19) falla silenciosamente
porque no anticipa que el CLI **siempre** emite un evento `result`
al final, aunque el último mensaje `assistant` fuera una pregunta.

## Por qué

Bug descubierto en el smoke real (2026-04-22), task 6 "fallar":
Claude terminó con 4 preguntas numeradas + "Dime.",
`stop_reason=end_turn`. El verificador marcó
`stream_terminated_cleanly=true` y el run acabó `verification_failed`
solo porque también falló E3 (no_artifacts). Sin E3 habría sido un
`done` false-positive — exactamente el bug-corazón de v0.2 que v1
debía cerrar.

**Causa raíz:** `check_stream_termination` recoge los eventos
filtrando `_LIFECYCLE = {"started", "completed", "failed", "error"}`,
coge el **último evento semántico**, y si es `type=="result"`
devuelve `(None, None)` (clean completion). Con Claude CLI real, el
último semántico es **siempre** `result` (lo emite el CLI como cierre
de turno, independiente de si el contenido previo era pregunta o
respuesta). La rama `if kind == "assistant"` nunca se ejecuta en
streams reales → la detección de `?` final nunca se dispara.

Los fixtures de v0.2 / PR-V1-11a no emitían `result` final (solo
terminaban con `assistant`), por eso los tests pasaban. Los
fixtures no eran realistas — PR-V1-11b confirmó el mismo patrón en
E4 ("real runs never see top-level frames"), ahora lo confirmamos
en E2.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── verification/
│       └── stream.py                    # rewrite check_stream_termination
└── tests/
    ├── verification/
    │   └── test_stream.py               # existing 4 tests + 3 new
    └── fixtures/
        └── stream_real_question.json    # NEW — portado del smoke real
```

**Hard-cap: 250 LOC netas** (código+tests+fixture JSON).

## Fuera de scope

- **No tocar `verify_run` / `core.py`** — la firma de
  `check_stream_termination` se mantiene
  `tuple[str | None, str | None]`.
- No modificar E3/E4/E5.
- No tocar el adapter.
- No tocar la UI de waiting_input.
- No añadir heurísticas nuevas (detectar preguntas sin `?` final,
  detectar "please", etc.) — YAGNI.

## Contrato tras el fix

Nueva lógica de `check_stream_termination(events)`:

1. Filtrar lifecycle: `events` con `type not in _LIFECYCLE`.
2. Si no hay ningún evento semántico → `("empty_stream", None)`.
3. Buscar el **último `assistant`** iterando hacia atrás
   (ignorando `result`, `user` con tool_result, `system`,
   `tool_use` intermedios).
4. Si no hay ningún `assistant` → `("empty_stream", None)`.
5. Extraer `text` concatenando bloques `content[].type=="text"`
   del último `assistant`.
6. Si `text` está vacío (el último assistant solo tenía bloques
   `tool_use` sin texto de cierre) → `("tool_use_incomplete", None)`.
7. Si `text.rstrip().endswith("?")` → `("needs_input", text)`.
8. En otro caso → `(None, None)`.

Implementación de referencia:

```python
def check_stream_termination(
    events: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    semantic = [e for e in events if e.get("type") not in _LIFECYCLE]
    if not semantic:
        return ("empty_stream", None)

    # Claude CLI always emits a terminal ``result`` frame. The
    # semantically meaningful "what did Claude say last" lives in
    # the last ``assistant`` event, not in ``result``. Walk back.
    last_assistant = None
    for event in reversed(semantic):
        if event.get("type") == "assistant":
            last_assistant = event
            break

    if last_assistant is None:
        # Stream has result/user/tool_use plumbing but no assistant
        # text — unusable output.
        return ("empty_stream", None)

    text = _assistant_text(last_assistant)
    if not text:
        # Last assistant has only tool_use blocks, no text wrap-up.
        return ("tool_use_incomplete", None)
    if text.rstrip().endswith("?"):
        return ("needs_input", text)
    return (None, None)
```

## Fixtures

**`tests/fixtures/stream_real_question.json`** — NUEVO. Porta el
stream real de task 6 del smoke (los eventos relevantes, no todo:
`system/init`, uno o dos `assistant` intermedios, `assistant`
final con el texto de 4 preguntas, `result` con
`subtype="success"`, `stop_reason="end_turn"`). El fichero vive
en el repo como regression guardrail — si alguien en el futuro
rompe la detección, este fixture lo caza.

Estructura mínima esperada (simplificada, usa los eventos reales
del smoke):

```json
[
  {"type": "system", "subtype": "init", "session_id": "..."},
  {"type": "assistant", "message": {"content": [{"type": "text",
    "text": "Antes de escribirla, tengo un par de dudas:\n\n1. Formato: ¿...?\n2. Idioma: ¿...?\n\nDime."}]}},
  {"type": "result", "subtype": "success", "stop_reason": "end_turn"}
]
```

## Tests

**`tests/verification/test_stream.py`** — los 4 casos existentes
siguen. Añadir:

1. `test_stream_with_result_after_assistant_question_detects_needs_input`:
   carga el fixture `stream_real_question.json` → el verificador
   devuelve `("needs_input", text)` donde `text` termina en `?` o
   `".".` (el texto real del fixture).
2. `test_last_assistant_answer_with_result_after_passes`:
   caso simétrico con `result` final tras un `assistant` que NO
   termina en `?` (ej. "Listo, añadido el comentario.") →
   devuelve `(None, None)`.
3. `test_stream_with_only_plumbing_no_assistant_returns_empty`:
   stream con `system/init` + `user` (tool_result) + `result`, sin
   ningún `assistant` → `("empty_stream", None)`.

**Baseline tras el fix:** 130 (post PR-V1-20) + 3 = **133 passed**.

## Criterio de hecho

- [ ] `check_stream_termination` busca el último `assistant`
      ignorando `result` trailing.
- [ ] `tests/verification/test_stream.py` pasa con los 7 casos (4
      existentes + 3 nuevos).
- [ ] Fixture `stream_real_question.json` committed y versionado.
- [ ] `pytest -q` → ≥133 passed, 0 regresiones.
- [ ] **Regression manual:** reencolar task 6 ("fallar" con pregunta
      final) en un smoke post-merge debe terminar `task.status =
      waiting_input`, `pending_question` populado con el texto de
      la pregunta, `run.outcome = "needs_input"`.
- [ ] Codex-reviewer ejecutado — este PR es directo descendiente del
      bug-corazón de v0.2, merece review aunque sea S-M.

## Riesgos conocidos

- **Falsos positivos por `?` en respuesta normal:** si el último
  `assistant` contiene una respuesta correcta que casualmente
  termina con signo de interrogación (ej. "¿Algo más?" como cierre
  cortés), la task quedará en waiting_input innecesariamente. Es
  un riesgo aceptado para MVP — el usuario puede responder vacío y
  la task reanuda. Detección más fina (NLP, heurística de contexto)
  es follow-up, no MVP.
- **`tool_use_incomplete` más raro tras el fix:** el caso de
  "último assistant solo con tool_use sin texto" era teóricamente
  posible antes pero raro; con la nueva lógica es aún más raro.
  Mantenemos el error_code por coherencia histórica.

## Notas para el implementador

- Cambio MINIMAL dentro de `stream.py`. No refactores el
  docstring del módulo más allá de actualizar las rules.
- Actualiza el docstring del módulo para reflejar la nueva lógica
  ("walk back to last assistant, not last semantic").
- La fixture puede ser trimmed del stream real de task 6 del
  smoke del 2026-04-22. Captura los eventos relevantes tras el
  smoke usando `sqlite3 ... "SELECT payload_json FROM run_events
  WHERE run_id = 5 ORDER BY id"` y pídele al human que te pase el
  dump si no tienes acceso a la DB.
- Commits sugeridos:
  1. `fix(verification): find last assistant, not last semantic event`
  2. `test(verification): regression fixture from real CLI stream`
