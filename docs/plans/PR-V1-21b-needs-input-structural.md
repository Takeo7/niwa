# PR-V1-21b — Verification: detección de needs_input estructural

**Tipo:** FIX (bug de precisión descubierto en smoke post-PR-V1-21)
**Semana:** 6
**Esfuerzo:** S-M
**Depende de:** PR-V1-21 (mergeado)

## Qué

Reforzar `check_stream_termination` en
`v1/backend/app/verification/stream.py` con detección estructural
del `tool_use` de `AskUserQuestion`. La heurística actual
(`text.endswith("?")` del último `assistant`) falla cuando Claude
cierra con imperativo ("Dime cuál prefieres..."). El fix añade dos
señales más robustas: (1) si Claude intentó usar el tool nativo
`AskUserQuestion` (o la CLI lo reporta en `permission_denials`), es
`needs_input` sin ambigüedad; (2) detección de texto mejorada que
mira cualquier párrafo, no solo el último carácter.

## Por qué

Smoke post-PR-V1-21 (2026-04-22). Dos casos fallaron la detección:

- **Task 11 (subtask "Add GitHub Actions CI workflow"):** Claude
  preguntó sobre lenguaje y framework. Texto final:
  > "...Let me know which direction you'd like."

  El `?` aparece DENTRO del texto (dos preguntas al principio),
  pero el texto termina en `.`. Heurística perdió.

- **Task 12 (pregunta-forzada):** Claude invocó `AskUserQuestion`
  con 3 opciones estructuradas (Alineamiento / Limitaciones /
  Interpretabilidad). Stream-json denegó el tool por ser
  non-interactive. Evidencia en `run_events`:
  ```json
  {"type":"user","message":{"content":[{"type":"tool_result",
   "is_error":true,"content":"Answer questions?",
   "tool_use_id":"toolu_01KPRgQwSr6ffXdV8YsWNjBB"}]}}
  ```
  Y en el `result` final:
  ```json
  {"permission_denials":[{"tool_name":"AskUserQuestion",
    "tool_input":{"questions":[{"question":"¿Qué enfoque...?",
    "options":[{"label":"Alineamiento","description":"..."}, ...]}]}}]}
  ```

  Claude nos está dando la pregunta + opciones en estructura JSON.
  Usar ese contrato es estrictamente superior a parsear prosa.

Bajo la heurística actual, ambos casos acabaron `failed` con
`no_artifacts` cuando semánticamente deberían ser `waiting_input`
para que el usuario responda vía el endpoint
`POST /api/tasks/:id/respond` (PR-V1-19).

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── verification/
│       └── stream.py               # nuevas señales + fallback mejorado
└── tests/
    ├── verification/
    │   └── test_stream.py          # 5 casos nuevos
    └── fixtures/
        ├── stream_ask_user_question.json        # NUEVO — fixture task 12
        └── stream_question_with_imperative.json # NUEVO — fixture task 11
```

**Hard-cap: 250 LOC** (código + tests + fixtures JSON).

## Fuera de scope

- No modificar la UI de waiting_input (TaskDetail.tsx) para renderizar
  `options` como botones — eso es follow-up PR cuando queramos UX más
  rica. Por ahora `verification_json.ask_user_question_options` se
  persiste para que esté disponible, pero la UI sigue renderizando
  Textarea libre.
- No tocar `verify_run` / `core.py` — la firma de
  `check_stream_termination` se mantiene
  `tuple[str | None, str | None]`.
- No tocar `respond_to_task` endpoint ni el flujo de resume.
- No cambiar E1/E3/E4/E5.

## Contrato tras el fix

Nueva lógica de `check_stream_termination(events)`, en este orden:

### Señal 1 (primaria): AskUserQuestion como `tool_use`

Iterar `events` y buscar cualquier `assistant` message cuyo
`content[]` contenga un bloque `{"type": "tool_use", "name":
"AskUserQuestion", "input": {...}}` **Y** también aceptar
top-level `tool_use` events (mismo patrón que E4 usa para cubrir
ambas shapes, ver PR-V1-11b).

Si existe al menos uno:

```python
question = input["questions"][0]["question"]  # string
# Opcional: capturar options si existen
options = input["questions"][0].get("options")  # list[dict] | None
return ("needs_input", question)
```

Capturar `options` como side-effect para que el caller (verify_run)
las pueda añadir a `verification_json`.

### Señal 2 (secundaria): `permission_denials` en `result`

Buscar el último evento `type=="result"`. Si tiene
`permission_denials` array y alguna entrada tiene
`tool_name=="AskUserQuestion"`:

```python
denied = entry["tool_input"]["questions"][0]["question"]
return ("needs_input", denied)
```

Esto cubre el caso donde el tool_use no quedara visible como evento
independiente pero sí como denial estructurado.

### Señal 3 (fallback): heurística de texto mejorada

Del último `assistant` (lógica PR-V1-21 actual), extraer `text`. Ahora:

- Split por `\n\n` (párrafos).
- Si **cualquier** párrafo con contenido termina en `?` o `?`
  (incluyendo `¿...?` español) → es pregunta.
- Si el texto original ya termina en `?` → es pregunta
  (comportamiento actual, se mantiene).

Si ninguna señal dispara → `(None, None)` (clean completion).

### Señal de respaldo pre-existente

- Si último `assistant` tiene solo `tool_use` blocks sin texto →
  `("tool_use_incomplete", None)`.
- Si no hay ningún `assistant` → `("empty_stream", None)`.

### Propagación de `options` al caller

La firma de `check_stream_termination` sigue devolviendo
`tuple[str | None, str | None]` para no reescribir el caller. Las
`options` viajan vía un argumento opcional `evidence: dict`:

```python
def check_stream_termination(
    events: list[dict[str, Any]],
    *,
    evidence: dict[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    # ... detectar AskUserQuestion ...
    if evidence is not None and options is not None:
        evidence["ask_user_question_options"] = options
    # ...
```

`verify_run` en `core.py` ya pasa `evidence` al llamar al stream
analyzer — si no lo pasa hoy, ajustar.

## Tests

**`test_stream.py`** — 5 nuevos casos:

1. `test_ask_user_question_tool_use_signals_needs_input`:
   fixture `stream_ask_user_question.json` (task 12 real) →
   devuelve `("needs_input", "¿Qué enfoque quieres...?")` y
   populates `evidence["ask_user_question_options"]`.

2. `test_ask_user_question_in_permission_denials_signals_needs_input`:
   fixture donde el tool_use no aparece como evento pero sí en
   `result.permission_denials` → mismo efecto.

3. `test_question_with_imperative_closing_detects_via_paragraph_scan`:
   fixture `stream_question_with_imperative.json` (task 11 real),
   texto termina en `.` pero contiene `?` en párrafo anterior →
   needs_input.

4. `test_spanish_question_marks_detected`:
   último assistant contiene `¿Cómo quieres proceder?` seguido de
   línea con imperativo → needs_input.

5. `test_statement_with_question_mark_inside_code_not_detected`:
   caso de falso positivo controlable — mensaje final tipo
   "Instalado. El archivo X contiene `?` como separador." termina
   con `.` y el `?` está en código. Actualmente es ruido conocido
   aceptado; el test documenta el trade-off explícito y devuelve
   `(None, None)`.

**Fixtures:**

- `stream_ask_user_question.json`: porte de run 10 task 12 del
  smoke del 2026-04-22. Capturar eventos id 128-137 del run. Ver
  reporte de smoke.
- `stream_question_with_imperative.json`: porte de run 9 task 11.
  Contiene el texto "Let me know which direction you'd like."
  con `?` en párrafo previo.

**Tests existentes que siguen:** los 7 de PR-V1-21 actuales. Revisar
caso 2 (`test_assistant_ending_in_question_signals_needs_input`)
para que no rompa con la nueva lógica — debería seguir funcionando
(texto termina en `?`).

**Baseline tras el fix:** 133 + 5 = **138 passed**.

## Criterio de hecho

- [ ] Reencolar task 12 ("pregunta-forzada") del smoke → termina
      `status=waiting_input`, `pending_question` con la pregunta
      real de Claude, `run.outcome=needs_input`,
      `verification_json.ask_user_question_options` con las 3
      opciones.
- [ ] Reencolar task 11 / equivalente ("Add CI workflow" sin stack
      declarado) → mismo resultado (waiting_input).
- [ ] Task 10 (LICENSE, camino feliz) sigue terminando
      `done/verified` sin regresión.
- [ ] `pytest -q` → 138 passed, 0 regresiones.
- [ ] Codex-reviewer ejecutado — este PR cierra el último
      agujero del detector.

## Riesgos conocidos

- **Falso positivo en código fence que contenga `?`:** si Claude
  responde con un bloque de código que accidentalmente termina un
  párrafo con `?` literal, la señal 3 dispara. Mitigación: para MVP
  priorizamos señal 1 (AskUserQuestion) que es determinista y
  cubre el 95% de casos reales. Señal 3 es fallback.
- **AskUserQuestion con `multi_select=true`:** hoy tomamos
  `questions[0].question` literal. Si Claude pregunta múltiples
  preguntas en un solo tool_use, solo registramos la primera; las
  siguientes se pierden. Aceptable para MVP — Claude típicamente
  hace una pregunta por turno. Follow-up si aparece abuso.
- **Denials futuros de otros tools:** `permission_denials` puede
  contener cualquier tool_name, no solo AskUserQuestion.
  Solo tratamos AskUserQuestion como señal de clarificación; los
  demás denials siguen siendo fallo.

## Notas para el implementador

- Las dos fixtures salen del dump de smoke 2026-04-22, run_ids 9
  (task 11) y 10 (task 12). Pedir al humano los JSON si no tienes
  acceso a su DB:
  ```
  sqlite3 ~/.niwa/data/niwa-v1.sqlite3 \
    "SELECT json_group_array(json(payload_json))
     FROM run_events WHERE run_id = <run_id>
     ORDER BY id ASC" > fixture.json
  ```
- Cambio MINIMAL en `stream.py`. Pueden aparecer dos helpers
  (`_find_ask_user_question`, `_scan_paragraphs_for_question`)
  — bien, pero no refactorizar más allá.
- Actualiza el docstring del módulo: añadir las señales 1 y 2 al
  listado de decisión.
- Commits sugeridos:
  1. `fix(verification): detect AskUserQuestion tool_use as needs_input`
  2. `fix(verification): scan result.permission_denials for AskUserQuestion`
  3. `fix(verification): paragraph-level question heuristic fallback`
  4. `test(verification): fixtures + 5 cases from real CLI smoke`
