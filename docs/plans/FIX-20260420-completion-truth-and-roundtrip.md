# FIX-20260420 — Completion detection por evidencia + round-trip real de clarificación

**Tipo:** FIX estructural (fuera del MVP-ROADMAP, post-MVP)
**Esfuerzo:** **L** (3-4 días de trabajo real, no lo empieces sin brief aprobado)
**Depende de:** FIX-20260419-bug33 (mergeado), PR-C1 (auto-deploy, mergeado), PR-B1/B2 (mergeados)
**Bloquea a:** todo testing manual del happy path. Hasta que esto esté mergeado, el MVP no se puede probar end-to-end sin ambigüedad.

## Observación que dispara este FIX

19/4/2026. Instalación limpia en máquina del usuario. Tarea: "crea un proyecto
con un botón que se mueve y cambia estilos". Resultado:

- Claude **escribió** 3 ficheros en `~/.niwa/data/projects/nuevo-proyecto-2ab561/`
  (`index.html` al menos, presumiblemente los 3).
- Niwa contó `tool_use_count: 0`, `stop_reason: "end_turn"`, `ends_with_question: false`.
- El detector de Bug 32 de PR-B1 marcó `error_code: "clarification_required"` y
  transicionó la tarea a `waiting_input`.
- La UI mostró banner amarillo "Claude necesita más información" — **falsamente**.
- No había forma de responder a Claude: la única acción disponible era
  reeditar la descripción entera y cambiar el estado a `pendiente` para
  re-ejecutar desde cero, sobreescribiendo el trabajo hecho.

Tres síntomas, una raíz: **la detección de completion se basa en una señal
frágil** (`tool_use_count`) y **la UX no ofrece camino de vuelta** cuando el
detector decide "necesita input".

## Qué arreglamos

**Tres bugs agrupados en un solo FIX porque son la misma herida:**

| Bug | Síntoma | Causa |
|---|---|---|
| **35 (nuevo)** | `tool_use_count` sale 0 cuando Claude sí ejecutó tools. Falso positivo del detector de Bug 32. | Una sola señal para decidir completion. No cruzamos con el filesystem ni con `stop_reason` ni con artifacts. |
| **36 (nuevo)** | Tarea en `waiting_input` no permite responder — solo reescribir descripción y relanzar. | `backend_runs.resume` existe en backend (PR-04) pero no hay endpoint público ni UI que lo invoque. |
| **17/33 parcial** | `ServicesPanel` sigue mostrando "CONFIGURADO" aunque el probe del FIX #95 devuelva `credential_expired` en `/api/readiness`. | La UI legacy calcula el badge a partir de detectores viejos, no consume el probe nuevo. |

## Principio de diseño del fix

**Un estado de tarea tiene que ser una afirmación verificable por el usuario.**
Niwa deja de "interpretar" con heurísticas aisladas y pasa a **cruzar señales
objetivas**:

1. **Stream events** — `tool_use` correctamente contado (parser robusto), más
   detección de `permission_denials`, `is_error`, `stop_reason`.
2. **Filesystem diff** — snapshot del `project_directory` antes de la run y
   después. Si hay nuevos ficheros, modificaciones, o borrados, es evidencia
   objetiva de que el agente hizo algo.
3. **Exit code** del CLI.
4. **Stream vacío** (ya detectado en FIX-20260419-bug33) como señal de
   credenciales caducadas.

Con esas 4 señales cruzadas, la tabla de decisión es:

| Stream events | Filesystem diff | Exit | Outcome |
|---|---|---|---|
| ≥1 tool_use + result success | cualquiera | 0 | **succeeded** |
| 0 tool_use + stream no vacío | diff ≠ ∅ | 0 | **succeeded** (el caso del 19/4, Bug 35) |
| 0 tool_use + stream no vacío | diff = ∅ + mensaje con `?` | 0 | **needs_input** (clarification real) |
| 0 tool_use + stream no vacío | diff = ∅ + sin `?` | 0 | **needs_input** con mensaje "Claude respondió sin ejecutar; si crees que el trabajo está hecho, revisa logs" (antes-Bug-32) |
| stream vacío | cualquiera | 0 | **credential_error** (FIX #95, ya cubierto) |
| permission_denials ≥ 1 | cualquiera | 0 | **failed** con `error_code=permission_denied` |
| is_error=true en result | cualquiera | 0 | **failed** con mensaje del result |
| cualquiera | cualquiera | ≠ 0 | **failed** con `error_code=exit_<N>` |

Un diff **no vacío** se define como: al menos 1 fichero nuevo, modificado o
borrado dentro del `project_directory` (excluyendo `.niwa/runs/`,
`.git/`, `.DS_Store`, `__pycache__/`, `node_modules/`, `.venv/`).

## Scope — archivos a tocar

### Backend

- **`niwa-app/backend/backend_adapters/claude_code.py`** — `_execute`:
  - Contador `tool_use_count` revisado: iterar todos los eventos del stream,
    identificar `type == "tool_use"` Y normalizar variantes observadas
    (`content[*].type == "tool_use"` dentro de `assistant_message`). El fixture
    capturado del 19/4 es la referencia.
  - Reemplazar la clasificación actual por la tabla de decisión arriba.
  - Integrar `fs_snapshot_before` y `fs_snapshot_after` llamando a los nuevos
    helpers de `runs_service`.
  - Nuevos `error_code`: `empty_stream_exit_0` (ya existe), `permission_denied`,
    `exit_<N>`, `clarification_required` (sin tocar — sigue siendo el bucket
    final cuando todo lo demás falla).

- **`niwa-app/backend/runs_service.py`** — nuevas funciones:
  - `snapshot_directory(path: Path, excludes: list[str]) -> dict` — devuelve
    `{relative_path: sha256}` para cada fichero. Determinista.
  - `diff_snapshots(before: dict, after: dict) -> {added: [], modified: [], removed: []}`.
  - `register_artifacts_from_diff(run_id, diff, project_directory)` — persiste
    en `artifacts` con `artifact_type ∈ {added, modified, removed}` cada entrada.
  - Extender `create_run` para aceptar `relation_type='resume'` + `parent_run_id`.
    Esto ya existe parcialmente; asegurar consistencia y test.

- **`niwa-app/backend/app.py`** — nuevo endpoint:
  - `POST /api/tasks/:id/respond` con body `{message: str}`.
  - Validaciones: tarea existe, está en `waiting_input`, tiene al menos un
    `backend_run` previo.
  - Crea un nuevo `backend_run` con `relation_type='resume'`, `parent_run_id`
    apuntando al último run, y `prompt` compuesto como contexto anterior +
    "\n\nUSER FOLLOWUP:\n{message}".
  - Transiciona la tarea a `en_progreso` vía state_machine.
  - El executor (polling loop) recoge el run nuevo como cualquier otro —
    **no requiere que el executor sepa nada de "resume"**; simplemente
    ejecuta el run con el prompt expandido.
  - Tests: estados incorrectos (tarea en otro estado → 409), mensaje vacío
    (400), happy path (201 con el run_id nuevo).

- **`niwa-app/backend/state_machines.py`** — permitir transición
  `waiting_input → en_progreso` cuando la dispara `POST /api/tasks/:id/respond`.
  Verificar si ya está permitida; si no, añadir sin romper otras rutas.

### Frontend

- **`niwa-app/frontend/src/features/tasks/components/WaitingInputBanner.tsx`**
  (nuevo):
  - Consume `useLastRunForTask(taskId)` (hook nuevo en
    `features/runs/hooks/useRuns.ts` — o similar si ya existe algo parecido).
  - Muestra:
    - La **pregunta real** que Claude hizo (`result_text` del último evento
      `error` con `error_code == 'clarification_required'`, o el mensaje
      directamente si el outcome es `needs_input`).
    - `<Textarea>` "Responde a Claude y reenvía" con placeholder útil.
    - Botón "Reenviar con tu respuesta" (deshabilitado si textarea vacío).
    - Botón secundario "Descartar y marcar como hecha" (opcional — ver
      §"Fuera de scope").
  - Mutación contra `POST /api/tasks/:id/respond`. Optimistic UI: banner
    desaparece, tarea vuelve a "en progreso".
  - Toast con error si el endpoint devuelve 4xx/5xx.

- **`niwa-app/frontend/src/features/tasks/components/TaskDetailsTab.tsx`** —
  integrar `WaitingInputBanner` donde hoy está el banner amarillo estático.
  El banner viejo (texto "Edita la tarea con los detalles…") **se elimina**,
  no se comenta.

- **`niwa-app/frontend/src/features/system/components/ServicesPanel.tsx`** y
  **`ServiceCard.tsx`**:
  - **Borrar** el cómputo legacy del badge (el que mira
    `services.llm_anthropic.status` computado a partir de detectores de
    ficheros locales). Delete, no flag-hide.
  - Consumir directamente `/api/readiness`:
    - Para claude_code: `backends[claude_code].claude_probe.status`.
    - Para cada backend: usar `auth_mode` y `claude_probe.status` para pintar
      el badge con texto claro: "suscripción · activa", "suscripción ·
      caducada", "api key", "sin credencial", "no instalado".
  - Si el usuario pulsa "Refrescar" → invalidar `/api/readiness` en React
    Query, no recargar la página.

### Tests

- **`tests/fixtures/claude_stream_bug35.jsonl`** (nuevo) — captura real (o
  cuidadosamente emulada) del stream-json que generó Claude el 19/4 en la
  tarea del usuario. Esta captura es **evidencia reproducible** del bug. Si
  no se puede capturar literalmente la original, fabricar una basada en
  observación directa del CLI `claude -p --output-format stream-json` con
  un prompt similar ("crea index.html con un botón") ejecutado fuera de Niwa.
  Documentar en el fichero cómo se obtuvo.

- **`tests/fixtures/fake_claude_wrote_files.py`** (nuevo) — fake CLI que emite
  eventos como los del fixture anterior Y escribe 3 ficheros en el
  `project_directory`. Usa el patrón de `fake_claude.py` existente.

- **`tests/fixtures/fake_claude_talked_no_work.py`** (nuevo) — fake CLI que
  emite un mensaje conversacional sin tool_use y **no** escribe ficheros.
  Reproduce Bug 32 original.

- **`tests/test_claude_adapter_completion.py`** (nuevo) — 8 casos mínimos,
  uno por fila de la tabla de decisión. Assertions: outcome, error_code,
  task status tras la run, artifacts registradas.

- **`tests/test_tasks_respond_endpoint.py`** (nuevo) — 5 casos:
  - 404 si tarea no existe.
  - 409 si tarea no está en `waiting_input`.
  - 400 si body vacío o message vacío.
  - 201 happy path: crea run con `relation_type='resume'`, tarea pasa a
    `en_progreso`, prompt incluye contexto anterior + followup.
  - Idempotencia: dos POST seguidos con distinto message → 2 runs creados.

- **`tests/test_runs_service_snapshot.py`** (nuevo) — 4 casos:
  - Snapshot de directorio vacío → `{}`.
  - Snapshot con 3 ficheros → 3 entradas con sha256.
  - Diff(before=5 files, after=6 files con 1 modificado) → 1 added, 1
    modified, 0 removed.
  - Excludes: crear `__pycache__/foo.pyc`, `.git/HEAD`, `node_modules/x.js`
    → no aparecen en snapshot.

- **Tests existentes que deben seguir verdes:**
  - Toda la suite actual. Baseline: `1330+ pass` (ha subido tras FIX #95 —
    verificar con `pytest -q` al empezar la rama y documentarlo en el PR).
  - Especialmente `test_claude_adapter_*` existentes — NO regresar.

### Docs

- **`docs/state-machines.md`** — añadir sección "Completion detection:
  evidence-based classification" con la tabla de decisión de este FIX.

- **`docs/BUGS-FOUND.md`** — añadir Bug 35 y Bug 36 como entradas con
  `**Estado:** fixed en FIX-20260420`. Extender entrada de Bug 17 con
  referencia al FIX (la parte del ServicesPanel).

- **Si `docs/HANDBOOK.md` ya existe** (brief DOCS-20260419): extender su
  §2 con el nuevo flow de round-trip y §9 recipe 5 con el endpoint
  `respond`. Si no existe todavía, ignorar.

## Fuera de scope (explícito)

- **No** añadir "Descartar y marcar como hecha" como botón de primera clase
  en el banner. Si el fix clasifica correctamente, ese caso debería ser
  raro — y si el usuario lo necesita por un edge, que lo haga desde el
  dropdown de estado manualmente. Dejar la puerta abierta en un FIX futuro,
  no meterlo aquí.
- **No** reescribir el executor. El executor ejecuta runs; que el run sea
  inicial o resume es transparente para él.
- **No** tocar Codex adapter en este PR. La tabla de decisión se aplicará
  a Codex en un FIX hermano, cuando se observe un síntoma real ahí.
- **No** refactorizar `runs_service.py` más allá de añadir las funciones
  nuevas necesarias. Si encuentras código duplicado, anótalo en el body
  del PR como "found along the way"; no lo limpies aquí.
- **No** tocar el flow de "auto-project creation" (PR-B2). Por el camino
  verás que el `project_directory` en este flow es un tempdir hasta que
  hay diff real; respétalo.

## Tests — qué ejecutar antes de abrir PR

```bash
python3 -m pytest tests/ -q --tb=short
```

Baseline esperada al terminar:
- `≥1350 pass` (1330+ previos + ~20 nuevos).
- `≤15 failed` (no deberías añadir nuevos failed).
- `0 errors`.

Además, después de la suite:

```bash
# Verificar que el endpoint nuevo funciona con la app real corriendo
python3 -m pytest tests/test_tasks_respond_endpoint.py -v

# Verificar que el snapshot es determinista
python3 -m pytest tests/test_runs_service_snapshot.py::test_deterministic -v
```

## Criterio de hecho (verificable punto por punto)

- [ ] Se reproduce el caso del 19/4 con un fake CLI que emite 0 tool_use pero
  escribe ficheros → el test sale `succeeded`, **no** `clarification_required`.
- [ ] Se reproduce Bug 32 original (fake CLI conversa sin trabajar) → el
  test sale `needs_input` y el `result_text` queda guardado en el run.
- [ ] `POST /api/tasks/:id/respond` con message="haz la versión azul" sobre
  una tarea en `waiting_input` crea un run nuevo con `relation_type='resume'`
  y pasa la tarea a `en_progreso`.
- [ ] UI: tarea en `waiting_input` muestra `WaitingInputBanner` con
  textarea; tras escribir y enviar, el banner desaparece y la tarea
  aparece en "en progreso".
- [ ] UI: `ServicesPanel` muestra estado real del probe. Con credenciales
  inválidas (borrar `~/.claude/.credentials.json` antes de cargar la UI),
  el badge dice "caducada" o "sin credencial", **no** "configurado".
- [ ] `artifacts` tabla tiene entradas `added`/`modified`/`removed` para
  cualquier fichero cambiado durante una run.
- [ ] `docs/state-machines.md` contiene la tabla de decisión.
- [ ] `docs/BUGS-FOUND.md` cierra Bugs 35 y 36; extiende Bug 17.
- [ ] `pytest -q` ≥1350 pass, ≤15 failed, 0 errors.
- [ ] Codex reviewer ha pasado sobre el diff y sus blockers se han
  resuelto en commits subsiguientes (no amendments).

## Riesgos conocidos

- **Snapshot del filesystem es caro** si `project_directory` tiene muchos
  ficheros. Mitigación: límite hard de 10k ficheros por snapshot; si
  excede, loggear warning y marcar `artifacts_snapshot_truncated=true` en
  el run. No bloquear la ejecución.
- **Race condition**: otro proceso (un watchdog, un `npm install`) escribe
  en el directorio durante la run y aparece en el diff como si fuera de
  Claude. Mitigación: documentar limitación, añadir columna
  `snapshot_attribution_confidence` al run con valor `high` por defecto;
  en el futuro se puede cruzar con `tool_use.input.file_path` si
  discrepancia.
- **Resume con session_handle perdido**: si el `session_handle` del run
  anterior se perdió (executor reiniciado, Docker restart), `claude
  --resume` falla. Fallback: prompt compuesto con contexto anterior
  textual + followup, sin `--resume`. Documentar en el código.
- **Backward compat**: `backend_runs` existentes tienen `outcome` según la
  lógica vieja. NO migrar. Dejar como están; la tabla de decisión nueva
  solo se aplica a runs nuevos.

## Orden de implementación sugerido (para que no te ahogues)

1. Capturar el stream-json real → `claude_stream_bug35.jsonl`. Sin esto, no
   sabes qué arreglas.
2. Escribir `snapshot_directory` + `diff_snapshots` + tests unit.
3. Escribir `fake_claude_wrote_files.py` y test de integración que reproduce
   el Bug 35.
4. Implementar la tabla de decisión en `claude_code.py::_execute`. Test rojo
   → verde.
5. Integrar `fs_snapshot_before/after` en el adapter. Test end-to-end.
6. Endpoint `POST /api/tasks/:id/respond` + tests.
7. UI: `WaitingInputBanner`. Instalar y probar en dev server contra backend
   real.
8. UI: `ServicesPanel` consume `/api/readiness`. Borrar cómputo legacy.
9. Docs.
10. `pytest -q` completo. Codex reviewer. PR.

## Notas para Claude Code (la sesión que implemente esto)

- **Este brief es tu contrato.** Si encuentras que el scope se desborda
  (p.ej. necesitas refactorizar `runs_service.py` más de lo que indica
  "Fuera de scope"), **paras y preguntas**. No amplías.
- **Commits pequeños, uno por paso del orden sugerido.** Facilita que
  Codex reviewer aísle cada señal.
- **Codex reviewer obligatorio** — esto es un PR L. Pega su output
  marcado como 🤖 Codex review en el body del PR, con resolución de
  cada comment.
- **El stream capturado (`claude_stream_bug35.jsonl`) es gold standard**.
  Si tu fix no hace `pass` el test que usa ese fixture, el fix no está
  hecho — aunque el resto de tests pasen.
- **Commits imperativos en inglés.** Mensaje del último commit del PR,
  cuando abras:
  ```
  fix: evidence-based completion + clarification round-trip

  Completion outcome is now derived from 4 cross-checked signals
  (stream events, filesystem diff, exit code, stop_reason) instead
  of tool_use_count alone.  Introduces artifacts_snapshot_diff as
  objective evidence of work done.  New endpoint POST /api/tasks/:id
  /respond + WaitingInputBanner component close the clarification
  loop with a real conversational round-trip.  ServicesPanel now
  consumes /api/readiness directly, retiring the legacy badge
  heuristic.  Closes Bug 35, Bug 36; extends Bug 17 fix from PR #95.
  ```
