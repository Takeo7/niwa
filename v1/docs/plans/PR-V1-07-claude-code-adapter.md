# PR-V1-07 — Claude Code adapter with stream-json parser

**Semana:** 2
**Esfuerzo:** M
**Depende de:** PR-V1-05 (executor echo). Arranca Semana 2 del SPEC
§9.

## Qué

Sustituye el pipeline `run_echo` por `run_adapter`, un subprocess
wrapper sobre `claude -p --output-format stream-json` que parsea
eventos línea-a-línea y los persiste en `run_events` en tiempo real.
Incluye un fake Claude CLI para tests (script Python ejecutable que
emite stream-json controlado por env vars), sin el cual ningún test
podría correr sin autenticación real. **No** hay rama git nueva, ni
SSE endpoint, ni UI de stream, ni verificación: esos son PR-V1-08,
09 y 10.

## Por qué

Semana 2 §9 del SPEC pide "adapter Claude Code real, ejecución en
rama nueva, stream de eventos hasta UI". Ese alcance excede 400 LOC
y no cabe en un PR. Este PR entrega la pieza de más valor y menos
reversible: el parser del stream. PR-V1-08 añade git branching
encima; PR-V1-09 expone SSE; PR-V1-10 conecta la UI. Cada uno ≤400
LOC, testeable aislado.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── adapters/
│   │   ├── __init__.py                      # exporta ClaudeCodeAdapter + AdapterEvent
│   │   └── claude_code.py                   # subprocess + stream parser, ~180 LOC
│   ├── config.py                            # NIWA_CLAUDE_CLI, NIWA_CLAUDE_TIMEOUT
│   └── executor/
│       └── core.py                          # reemplaza run_echo por run_adapter;
│                                            # mantiene claim_next_task y
│                                            # process_pending intactos
└── tests/
    ├── fixtures/
    │   ├── __init__.py
    │   └── fake_claude_cli.py               # script emisor de stream-json, ~70 LOC
    ├── test_adapter.py                      # 4 casos (nuevos)
    └── test_executor.py                     # rewrite de los casos que asumían
                                             # run_echo, ahora usan el fake CLI
```

**Hard-cap:** 400 LOC netas (inserciones − deleciones). Si durante
implementación excedes, PARAS y partes en 07a/07b.

## Fuera de scope (explícito)

- **No hay rama git `niwa/<slug>`.** Runs ejecutan en
  `project.local_path` tal cual. El branching es PR-V1-08.
- **No hay SSE / WebSocket endpoint.** `run_events` se escriben en
  DB, pero aún no se exponen por HTTP. PR-V1-09.
- **No hay UI de stream.** PR-V1-10.
- **No hay `waiting_input`.** Si el stream incluye un evento de
  pregunta, se ignora y el run termina cuando termina el proceso.
  Clarification round-trip llega en Semana 5.
- **No hay contrato de verificación §5.** Artifact tracking se
  limita a registrar `artifact_root = project.local_path` en el
  `Run`; la validación de exit-code-0 + stream-closing-message +
  artefacto-dentro-de-cwd + tests es Semana 3 (PR-V1-12).
- **No se añade `task_events` nuevos.** Los de status-change siguen
  iguales; los `run_events` llevan el detalle del stream.
- **No hay retry ni timeout por evento.** Sí hay timeout global
  del proceso (`NIWA_CLAUDE_TIMEOUT`, default 1800 s); al expirar,
  el run se marca `failed` con outcome `timeout`.
- **No se toca `niwa-app/backend_adapters/claude_code.py`.** Es
  referencia histórica de solo lectura. Reescritura drástica en v1.
- **No se añade autenticación.** Se asume `claude` CLI ya logeado
  en la máquina del usuario — fuera del MVP el bootstrap lo maneja.

## Dependencias nuevas

- Python: **ninguna** (stdlib: `subprocess`, `json`, `threading`,
  `selectors`, `signal`).
- npm: **ninguna**.

Si al implementar necesitas algo fuera del set pre-aprobado de v1
(`fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `pydantic`,
`pytest`, `httpx`), PARAS.

## Tests

**Nuevos en `v1/backend/tests/test_adapter.py`** (4 casos):

1. `test_adapter_parses_stream_and_writes_run_events` — fake CLI
   emite 3 eventos JSON (assistant message, tool_use, result con
   exit_code 0). El adapter los parsea, el executor escribe 3
   `run_events` correspondientes, el `Run` termina
   `status='completed'` con `exit_code=0`, y la `Task` pasa a
   `done`.
2. `test_adapter_nonzero_exit_marks_run_failed` — fake CLI sale
   con exit code 1 tras un evento. El `Run` acaba
   `status='failed'`, outcome `"cli_nonzero_exit"`, `exit_code=1`.
   La `Task` pasa a `failed`.
3. `test_adapter_skips_malformed_json_lines` — fake CLI emite una
   línea no-JSON (`"garbage"\n`) entre dos JSON válidos. El
   adapter la ignora (warning log), parsea las dos válidas, escribe
   2 `run_events`, y termina OK.
4. `test_adapter_binary_missing_fails_fast` — `NIWA_CLAUDE_CLI`
   apunta a path inexistente. El adapter captura el
   `FileNotFoundError` del spawn y termina el run con
   `status='failed'`, outcome `"cli_not_found"`, sin crashear el
   executor.

**Refactor en `v1/backend/tests/test_executor.py`:** los 7 casos
del baseline que asumían `run_echo` se reescriben para montar el
fake CLI con un payload mínimo de un solo evento "result" y exit
code 0; semántica idéntica (task transitions, run created, events
cascaded), pero ahora vía la ruta real del adapter. Sin cambios en
`test_runs_api.py` ni en los 37 tests restantes.

**Baseline tras PR-V1-07:**
- Backend: **48 passed** (44 actuales + 4 nuevos en
  `test_adapter.py`; los 7 de executor migran, no suman).
- Frontend: 4 passed (sin cambios — PR no toca frontend).

## Criterio de hecho

- [ ] `v1/backend/app/adapters/claude_code.py` expone
  `ClaudeCodeAdapter(cli_path, cwd, prompt, timeout)` con método
  `.iter_events()` que yield-ea `AdapterEvent(kind, payload,
  raw_line)` leyendo línea a línea de stdout, y `.wait()` que
  devuelve exit code final.
- [ ] El executor llama al adapter dentro de `run_adapter`, y por
  cada evento escribe una fila en `run_events` con
  `event_type=adapter_event.kind` y
  `payload_json=json.dumps(adapter_event.payload)`. El flush al DB
  es inmediato (commit por evento o batch de 10 — decisión del
  implementador, documentada en docstring).
- [ ] Exit code 0 + cierre limpio de stdout → `Run.status='completed'`,
  `outcome='cli_ok'`. Exit code ≠ 0 → `failed` +
  `outcome='cli_nonzero_exit'`. Timeout global → `failed` +
  `outcome='timeout'` (el adapter envía `SIGTERM`, espera 5 s,
  `SIGKILL` si sigue vivo). `FileNotFoundError` en spawn → `failed`
  + `outcome='cli_not_found'`.
- [ ] `task.status` se transita a `done` o `failed` según el
  resultado del run, con el `task_event` de `status_changed`
  correspondiente.
- [ ] Fake CLI en `v1/backend/tests/fixtures/fake_claude_cli.py`
  lee `FAKE_CLAUDE_SCRIPT` (path a un JSONL con eventos a emitir)
  y `FAKE_CLAUDE_EXIT` (exit code final, default 0). Emite cada
  línea del script a stdout con `flush=True`, espera el delay
  opcional entre líneas (`FAKE_CLAUDE_DELAY_MS`, default 0), y sale
  con el exit code declarado. Ejecutable como `python
  fake_claude_cli.py` — los tests lo referencian vía
  `NIWA_CLAUDE_CLI=<path>`.
- [ ] `pytest -q` en `v1/backend/` → 48 passed, 0 failed.
- [ ] Ningún test consulta la red ni depende del `claude` real.
- [ ] HANDBOOK actualizado con sección `Adapter Claude Code
  (PR-V1-07)` describiendo el contrato del stream, la estructura
  de `AdapterEvent`, los 4 outcomes, y cómo el fake CLI reemplaza
  al real en tests.
- [ ] Codex-reviewer ejecutado, comentario pegado en el PR.

## Riesgos conocidos

- **Bloqueo en `readline()` si el CLI no cierra stdout.** Mitigación:
  lectura vía `selectors.DefaultSelector` con timeout por iteración
  (p.ej. 500 ms) para poder cooperar con el timeout global y con
  señales de cancelación futuras. No uses `subprocess.PIPE` +
  `.stdout.readline()` bloqueante sin timeout.
- **Deadlock por stderr lleno.** Si el CLI escribe mucho a stderr y
  nadie lo drena, bloquea al proceso. Mitigación: drenar stderr en
  un `threading.Thread` daemon, acumulando en buffer acotado
  (últimas 64 KB) para el log en caso de fallo.
- **UTF-8 partido a mitad de línea.** Stream-json emite una línea
  JSON completa por evento — asume `\n` como separador. Si el CLI
  emite un JSON multilínea, se romperá el parser. v0.2 asumía lo
  mismo; aceptable para el MVP, documentar en docstring.
- **Commit por evento es caro.** Mitigación: `session.flush()` por
  evento + `session.commit()` cada N eventos o al final. Empieza
  con commit por evento (más simple, más resiliente a caídas) y
  mide; si es un cuello de botella, batch en 07-followup.
- **Env var `NIWA_CLAUDE_CLI`** vs autoridad de `claude` en PATH.
  Default: si la env var no está, usar `shutil.which("claude")`.
  Si `which` devuelve `None`, el adapter falla con
  `outcome='cli_not_found'` al primer spawn.
- **El SPEC dice "rama `niwa/<task-slug>`"** — este PR la omite
  por scope. Documenta en HANDBOOK que la ejecución actual muta el
  working tree directamente, hasta PR-V1-08.

## Notas para Claude Code

- Commits sugeridos:
  1. `feat(backend): claude code adapter with stream-json parser`
  2. `test(backend): fake claude cli fixture and adapter tests`
  3. `refactor(backend): replace run_echo with run_adapter`
  4. `test(backend): migrate executor tests to fake adapter`
  5. `docs(v1): handbook adapter section`
- El adapter debe ser **puro subprocess + parse**, sin tocar la
  DB. El executor es quien escribe `run_events` y transita estados.
- Reusa el modelo `Run` existente; no añadas columnas — todo cabe
  en `verification_json` si hace falta (aunque PR-V1-07 no
  escribe nada ahí; lo deja `null`).
- No dupliques lógica del adapter de v0.2. Léelo para entender el
  contrato del stream-json, reescribe mínimo. Target LOC del
  adapter: ≤200.
- Si el executor pasa a ser demasiado grande por las transiciones
  + writes de events, extrae un helper `_apply_event(session, run,
  event)` en `executor/core.py`. No crees módulos nuevos por
  detalle de implementación.
- Si algo del SPEC está ambiguo (p. ej. qué `event_type` mapear a
  qué `AdapterEvent.kind`), PARA y pregunta antes de inventar.
