# PR-V1-22 — Resume con session_handle + respuesta del usuario

**Tipo:** FEATURE (cierra el loop de clarification)
**Semana:** 6
**Esfuerzo:** M
**Depende de:** PR-V1-21b (detector estructural de needs_input)

## Qué

Cerrar el flujo de clarification end-to-end. Hoy una task en
`waiting_input` + `POST /api/tasks/:id/respond` → `queued` → run
nuevo con prompt fresco de título/descripción originales; Claude no
ve la respuesta ni recuerda el trabajo previo. El fix:

1. El adapter extrae `session_id` del primer evento `system/init`
   y lo persiste en `run.session_handle`.
2. El adapter acepta un kwarg `resume_handle: str | None` que
   añade `--resume <handle>` a los args del CLI cuando es no-None.
3. El endpoint `POST /api/tasks/:id/respond` normaliza el TaskEvent
   que ya escribe: `kind="message"` + payload
   `{"event": "user_response", "text": "<respuesta>"}`.
4. El executor, al recoger una task `queued` que tiene un último
   TaskEvent `message/user_response`, busca el último run de esa
   task con `session_handle NOT NULL` y lanza el adapter con
   `resume_handle=<handle>` y `prompt=<respuesta_del_usuario>`.
5. Tras el nuevo run terminando OK (verified), limpiar
   `task.pending_question = NULL` (si la nueva ronda no generó otra
   pregunta).

## Por qué

Smoke 2026-04-22: PR-V1-21b validó que `waiting_input` se detecta
correctamente contra Claude CLI real. Pero el respond sigue como
"known limitation" de PR-V1-19: mueve la task a queued sin
reanudar. Con Claude real significa que el siguiente run es ciego
al trabajo previo — misma pregunta, misma frustración, la feature
de clarification queda inutilizada en uso real. Este PR la activa.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── adapters/
│   │   └── claude_code.py        # extract session_id + accept resume_handle
│   ├── executor/
│   │   └── core.py               # detect resume path, pass kwargs
│   └── services/
│       └── tasks.py              # respond_to_task writes normalized event
└── tests/
    ├── test_adapter.py           # +2: session_id extracted, --resume in argv
    ├── test_executor.py          # +2: resume path picks right handle + prompt
    ├── test_tasks_api.py         # +1: respond writes user_response event
    └── fixtures/
        └── fake_claude_cli.py    # FAKE_CLAUDE_SESSION_ID env var for tests
```

**Hard-cap: 300 LOC netas** (código + tests + fixtures). Excede el
soft 400 si se suma HANDBOOK; **hard-cap es código+tests**.

## Fuera de scope

- No tocar la UI del waiting_input (TaskDetail.tsx sigue con
  Textarea libre — `ask_user_question_options` es para follow-up).
- No tocar verification (el verifier sigue igual — la respuesta al
  resume pasa por el mismo contrato E1..E5).
- No implementar retry múltiple ni cancelación desde respond.
- No persistir historial completo de conversación — Claude ya lo
  reconstruye del session_handle. Niwa solo guarda el handle y los
  run_events por run.

## Contrato tras el fix

### Adapter — `ClaudeCodeAdapter.__init__` añade kwarg

```python
def __init__(
    self,
    cli_path: str | None,
    *,
    cwd: str,
    prompt: str,
    timeout: float = _DEFAULT_TIMEOUT,
    extra_args: list[str] | None = None,
    resume_handle: str | None = None,   # NUEVO
) -> None:
```

En `iter_events` al construir `cmd`:

```python
cmd = [self._cli_path, *self.DEFAULT_ARGS, *self._extra_args]
if self._resume_handle:
    cmd += ["--resume", self._resume_handle]
```

Y una nueva propiedad `session_id: str | None` que se popula al
parsear el primer evento `system/init` (campo `session_id`). La
extracción vive en `_parse_line` o en un callback del bucle de
`iter_events`.

### Executor — `run_adapter` detecta resume

Tras `claim_next_task`, antes de spawnear el adapter:

```python
resume_handle = None
resume_prompt = None
last_message = _last_user_response_event(session, task)  # helper
if last_message is not None:
    last_run_with_handle = _last_run_with_session_handle(session, task.id)
    if last_run_with_handle is not None:
        resume_handle = last_run_with_handle.session_handle
        resume_prompt = last_message.payload_json_text_field
        # log claro: "resuming run_id=N via session_handle=X..."
```

Si `resume_handle` existe:
- `adapter_prompt = resume_prompt` (la respuesta del usuario, no
  title+description).
- `ClaudeCodeAdapter(..., resume_handle=resume_handle)`.

Si no existe (resume no disponible):
- Fallback a prompt fresco (comportamiento actual) + logger.warning
  indicando que el session_handle no estaba disponible.

### Tras cada run, persistir session_id si se obtuvo

```python
if adapter.session_id is not None:
    run.session_handle = adapter.session_id
    session.commit()
```

### respond_to_task — normalizar TaskEvent

En `services/tasks.py::respond_to_task`, al mover la task a
`queued`, escribir el TaskEvent con payload explícito:

```python
session.add(TaskEvent(
    task_id=task.id,
    kind="message",
    message=None,
    payload_json=json.dumps({
        "event": "user_response",
        "text": response_text,
    }),
))
```

Hoy probablemente ya escribe un message — este PR estandariza el
schema para que el executor lo encuentre reliably.

### Limpieza de `pending_question`

En `_finalize`, si `outcome == "verified"` Y la task tenía
`pending_question` poblado al entrar al run:

```python
task.pending_question = None
```

Si el nuevo run devuelve `needs_input` de nuevo, `pending_question`
se vuelve a poblar con la nueva pregunta (lógica ya existente).

## Tests

### Adapter (`test_adapter.py`)

- `test_session_id_extracted_from_system_init`: fake-CLI emite
  `{"type":"system","subtype":"init","session_id":"abc-123",...}`,
  adapter completa; `adapter.session_id == "abc-123"`.
- `test_resume_handle_adds_resume_arg_to_cli`: spawn con
  `resume_handle="abc-123"`; `proc.argv` contiene
  `--resume abc-123`. Sin resume_handle, no aparece.

### Executor (`test_executor.py`)

- `test_resume_path_uses_prev_run_session_handle`: setup con task
  en queued tras TaskEvent user_response + run previo con
  session_handle="xxx"; ejecutar → adapter spawneado con
  `resume_handle="xxx"` y prompt=respuesta, no title/description.
- `test_resume_prompt_is_user_response_not_task_description`:
  igual que arriba, asserta que el prompt que recibe el adapter
  mock es exactamente el texto del user_response.

### Endpoint (`test_tasks_api.py`)

- `test_respond_writes_normalized_user_response_event`: POST
  respond con text "React"; comprobar que `task_events` tiene una
  fila nueva con kind="message" y
  `json_extract(payload_json, '$.event') == "user_response"` y
  `json_extract(payload_json, '$.text') == "React"`.

### Fake CLI

- Extender `fake_claude_cli.py` con env var
  `FAKE_CLAUDE_SESSION_ID` que se incluye en el system/init
  emitido. Para tests del adapter.

### Baseline tras el fix

138 + 5 nuevos = **143 passed**.

## Criterio de hecho

- [ ] `pytest -q` → 143 passed.
- [ ] Smoke manual del humano:
  1. Crear task con descripción ambigua → esperar waiting_input
     con pending_question.
  2. Responder vía UI (o POST /respond) con texto concreto.
  3. Observar que el nuevo run spawnea `claude --resume <handle>`
     con prompt = la respuesta del usuario.
  4. Verificar que Claude resume desde donde dejó y completa la
     task correctamente (commit + PR si aplica), sin repetir la
     pregunta.
- [ ] `run.session_handle` persistido (no NULL) para todo run que
      haya emitido system/init con session_id.
- [ ] `task.pending_question` limpio tras un respond exitoso.
- [ ] Codex-reviewer ejecutado.

## Riesgos conocidos

- **Session expira en Claude CLI:** si el usuario tarda horas en
  responder y la sesión expira, `--resume <handle>` puede fallar
  con error del CLI. Hoy ese error cae en `cli_nonzero_exit` y la
  task queda `failed`. Aceptable para MVP — el usuario puede crear
  una task nueva con descripción explícita. Follow-up: detectar
  error específico y fallback a prompt fresco con composite.
- **Multiple respond antes de que se ejecute el run:** si el
  usuario responde dos veces rápido, hay dos TaskEvents
  user_response. El executor usa el último. Aceptable.
- **Session handle missing en first run:** si el primer run falló
  antes de emitir system/init, `session_handle` queda NULL. El
  respond no puede resume → fallback a prompt fresco con warning.
  Aceptable.

## Notas para el implementador

- El `respond_to_task` actual en `services/tasks.py` probablemente
  ya escribe un TaskEvent. Revisar y **normalizar**, no duplicar.
- La detección de "task viene de waiting_input" se hace via
  TaskEvent más reciente (kind=message, payload.event=user_response)
  posterior al último status_changed a waiting_input — no vía
  `pending_question IS NOT NULL` solo, porque tras la limpieza del
  punto 5 el campo queda NULL.
- `fake_claude_cli.py` ya existe (PR-V1-07). Extender, no
  reescribir.
- Commits sugeridos:
  1. `feat(adapter): expose session_id and accept resume_handle kwarg`
  2. `feat(services): normalize respond_to_task event payload`
  3. `feat(executor): spawn adapter with --resume on respond flow`
  4. `feat(executor): clear pending_question on successful verify`
  5. `test: session handle + resume path coverage`
