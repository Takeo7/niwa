# PR-B1 — Fix Bug 32 regression: detect clarification on N-tool + trailing question

**Hito:** B
**Esfuerzo:** S-M
**Depende de:** ninguna
**Bloquea a:** PR-B2 (no directamente; ambos atacan bugs de ejecución
y el criterio de hito B depende de los dos)

## Qué

Amplía el detector false-succeeded de Bug 32 en
`ClaudeCodeAdapter._execute()`. Hoy solo dispara cuando
`tool_use_count == 0`. El caso observado en prod el 2026-04-18 no
entra por ese filtro: Claude ejecuta ≥1 `tool_use` (p. ej.
`Bash mkdir /tmp/foo`) y **luego** termina con un mensaje de texto
que contiene una pregunta (p. ej. "Proyecto creado. ¿Qué tipo
quieres inicializar?"). `tool_use_count == 1` ⇒ no dispara el gate ⇒
tarea marcada `hecha`.

El fix añade una segunda condición: si `result_text` (el texto final
que Claude devuelve en el mensaje `result`) termina con `?` (tras
strip), marcamos `needs_clarification` aunque haya habido tool_use.
Se OR-ea con el filtro existente — no sustituye, añade.

## Por qué

Happy path §4 declara "tarea → ejecución autónoma": Niwa debe
ejecutar "sin pedir interacción" **o** dejar la tarea en un estado
accionable con la pregunta visible. Hoy la tarea acaba como `hecha`
con la pregunta enterrada en el output, el usuario piensa que está
lista y el trabajo queda a medias. Este PR cierra la regresión que
el propio BUGS-FOUND.md declara pendiente.

## Scope — archivos que toca

- `niwa-app/backend/backend_adapters/claude_code.py:1053-1086`:
  añade helper `_result_ends_with_question(text: str) -> bool` y
  extiende la condición del gate Bug 32 con él. El mensaje del event
  y el `payload_json` no cambian su schema; se añade el flag
  `ends_with_question` al payload para diagnosticar.
- `tests/test_claude_adapter_clarification.py`: 3 casos nuevos
  (detalle en §Tests).
- `docs/BUGS-FOUND.md` (sección Bug 32): marcar como
  **ARREGLADO en PR-B1** con el diff del discriminador.

## Fuera de scope (explícito)

- No toca el executor (`bin/task-executor.py`). El sentinel
  `__NIWA_CLARIFICATION__` y el mapping `needs_clarification →
  waiting_input` ya existen y siguen intactos.
- No toca `runs_service.finish_run`. El mapping existente cubre el
  nuevo caso.
- No toca el frontend (`TaskDetailsTab.tsx`). El banner amarillo de
  clarification ya se dispara por `error_code ==
  'clarification_required'`; el nuevo caso usa el mismo `error_code`.
- No toca Bug 34 ni Feature 1 (aunque están relacionados en el log
  de regresiones del 2026-04-18; ambos caen en otros PRs).
- No añade detección por idioma/keyword ("¿puedes...?"). Solo
  sufijo `?`.

## Diseño del discriminador

[Hecho] La observación de prod es: `tool_use_count == 1`,
`stop_reason == "end_turn"`, `is_error == False`,
`permission_denials == []`, `result_text` termina con `?`.

[Inferido] `?` cubre preguntas en inglés y español (Spanish abre
con `¿` pero cierra con `?`). No añado `¿` al sufijo — abriría
falsos positivos con texto interrumpido.

[Supuesto] Claude no termina tareas completas con `?` rhetórico
("¿algo más?" tras trabajo hecho). Si aparece un falso positivo, el
operador verá la tarea en `waiting_input` con el texto de Claude
visible — es un fallo benigno (pierde un ciclo, no datos ni estado).
Prefiero ese trade-off a dejar el bug abierto.

Implementación:

```python
def _result_ends_with_question(text: str) -> bool:
    if not text:
        return False
    stripped = text.rstrip().rstrip("`*_ \t\n\r")
    return stripped.endswith("?")
```

Y el gate:

```python
if outcome == "success" and stop_reason == "end_turn":
    task_source = (task.get("source") or "").strip().lower()
    if task_source and task_source != "chat":
        ends_with_q = _result_ends_with_question(result_text)
        if tool_use_count == 0 or ends_with_q:
            outcome = "needs_clarification"
            error_code = "clarification_required"
            # record_event igual que ahora, payload añade
            # "ends_with_question": ends_with_q
```

## Tests

**Nuevos:**

- `test_executive_one_tool_plus_question_needs_clarification` en
  `TestClarificationDetection`: stream = `system + tool_use(Bash) +
  tool_result + assistant(text con "¿...?") + result(stop=end_turn,
  result="... ¿Qué tipo quieres?")`. Assert: `outcome ==
  "needs_clarification"`, `error_code == "clarification_required"`,
  `tool_use_count == 1`, `result["result_text"]` contiene la pregunta.
- `test_executive_n_tools_plus_statement_stays_success` en
  `TestHappyPathWithTools`: stream con 2 `tool_use` + `result_text
  = "Files written successfully."` (sin `?`). Assert: `outcome ==
  "success"`. Guard anti-regresión del happy path.
- `test_chat_source_with_tool_and_question_stays_success` en
  `TestChatTaskNoFalsePositive`: mismo stream del primer test pero
  `task_source = "chat"`. Assert: `outcome == "success"` — el
  discriminador `source != 'chat'` sigue vigente.

**Existentes que deben seguir verdes:**

- Los 7 casos previos de `test_claude_adapter_clarification.py`.
- `tests/test_task_executor_clarification.py` (3 casos — el
  executor no cambia).
- `tests/test_claude_adapter_integration.py`,
  `tests/test_claude_adapter_start.py`,
  `tests/test_claude_adapter_parse_usage.py`.
- Baseline tras PR-A4: `1037 pass / 60 failed / 104 errors / 87
  subtests pass` [Supuesto — pendiente reverificar post-merge de
  PR-A4; si cambió, recalibro].

**Baseline esperada tras el PR:** `≥1040 pass` (3 tests nuevos) /
`≤60 failed` / `≤104 errors`.

## Criterio de hecho

- [ ] `test_executive_one_tool_plus_question_needs_clarification`
  pasa (fixture stream 1-tool + pregunta final).
- [ ] `test_executive_n_tools_plus_statement_stays_success` pasa
  (guard happy path N-tools sin pregunta).
- [ ] `test_chat_source_with_tool_and_question_stays_success` pasa
  (chat no regresa).
- [ ] Los 7 tests previos de `test_claude_adapter_clarification.py`
  siguen verdes.
- [ ] `pytest -q` completo sin regresiones vs baseline.
- [ ] `BUGS-FOUND.md` actualizado: Bug 32 pasa a **ARREGLADO en
  PR-B1** con nota del discriminador.
- [ ] Review Codex invocado (esfuerzo S-M, superficie de adapter
  sensible a state machine).
- [ ] Ningún cambio de comportamiento en `runs_service`,
  `task-executor.py` o frontend.

## Riesgos conocidos

- **Falso positivo: tarea completada que termina con `?`.** Ej.:
  Claude responde "Listo. ¿Algo más?". Mitigación: es benigno — la
  tarea queda en `waiting_input` con el texto completo visible, el
  usuario la re-dispara con un "no, todo bien". Trade-off aceptado
  sobre seguir dejando tareas `hecha` con trabajo a medias.
- **Heurística dependiente de cómo Claude estructura la respuesta.**
  Si Claude cambia de formato (markdown fenced, code block al
  final), el `rstrip` de backticks mitiga el caso más común. Si
  aparecen otros, se refinará en un FIX separado.
- **Test fixtures ≠ producción.** Los tests siguen siendo sobre
  strings, no sobre Claude real. El BUGS doc lo marca como problema
  conocido (la regresión original pasó CI). No lo resuelvo aquí
  porque requeriría infra de integration con Claude CLI real —
  fuera de scope.

## Notas para Claude Code

- Commits imperativos cortos en inglés:
  1. `test: failing cases for bug 32 question-suffix regression`
  2. `fix: detect clarification on trailing question mark`
  3. `docs(bugs): mark Bug 32 as fixed in PR-B1`
- Antes de invocar Codex reviewer: `pytest -q` completo, pegar diff
  vs baseline en el PR body.
- Si durante la implementación descubres que Claude emite tool_use
  dentro del array `content` del mensaje `assistant` (y no como
  mensaje standalone `type:"tool_use"`), reabre el brief — eso
  cambia el conteo de `tool_use_count` y puede requerir tocar
  `_classify_event`. No lo detecté en los fixtures actuales pero el
  CLI real podría hacerlo diferente.
