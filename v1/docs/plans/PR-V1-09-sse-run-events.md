# PR-V1-09 — SSE endpoint para run events

**Semana:** 2
**Esfuerzo:** M
**Depende de:** PR-V1-07 (adapter escribe `run_events`) + PR-V1-08
(branch per task) mergeados.

## Qué

Expone `GET /api/runs/{run_id}/events` como Server-Sent Events. El
stream emite primero los `run_events` históricos ordenados por
`created_at`, y después tail-polls la DB cada 200 ms hasta que el
`Run.status` sea terminal (`completed|failed|cancelled`), enviando
cada nuevo evento. Heartbeat cada 15 s para que proxies no timeouten.
Cierra el stream con un evento `eos` (end-of-stream) tras emitir el
último evento del run terminal.

## Por qué

SPEC §9 Semana 2: "stream de eventos hasta UI". Este PR entrega la
capa de transporte; PR-V1-10 conecta la UI. Sin SSE, la UI tendría
que hacer polling masivo sobre el CRUD existente, lo cual es caro y
rompe la experiencia "en vivo" que el SPEC §7 ("stream en vivo del
run activo") promete.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── api/
│   │   └── runs.py                           # +GET /api/runs/{id}/events
│   └── services/
│       └── run_events.py                     # nuevo, helpers puros
└── tests/
    └── test_runs_api.py                      # +3 casos SSE
```

**Hard-cap:** 400 LOC netas.

## Fuera de scope (explícito)

- **No hay cancel desde UI.** Solo se observa; cancelar runs vivos
  es follow-up (requiere protocolo adapter ↔ executor que no
  existe).
- **No hay `resume` ni `waiting_input`.** Clarification round-trip
  es Semana 5.
- **No hay WebSocket.** SSE es suficiente (unidireccional
  server→client, funciona con EventSource nativo del browser).
- **No hay auth/token en el endpoint.** Binding local 127.0.0.1,
  SPEC §2 lo autoriza.
- **No hay compresión ni gzip.** Stream plano.
- **No se toca el adapter.** El adapter ya escribe en
  `run_events`; este PR solo lee.
- **No hay paginación.** El histórico completo se emite antes del
  tail; para runs muy largos se optimiza en follow-up.
- **No toca frontend.** Cero cambios en `v1/frontend/`. La UI
  llega en PR-V1-10.

## Dependencias nuevas

- Python: **ninguna** (FastAPI ya incluye `StreamingResponse` y
  soporta `async` generators nativamente).
- npm: **ninguna**.

## Contrato del stream

**URL:** `GET /api/runs/{run_id}/events`
**Content-Type:** `text/event-stream`
**Cache-Control:** `no-cache`
**Connection:** `keep-alive`

**Eventos:**

```
: heartbeat                                   (comentario SSE, cada 15 s)

id: <run_event.id>
event: <run_event.event_type>
data: {"id": 42, "event_type": "assistant", "payload": {...}, "created_at": "2026-04-20T..."}

...

event: eos
data: {"run_id": 7, "final_status": "completed", "exit_code": 0, "outcome": "cli_ok"}
```

El evento `eos` es terminal; tras él, el servidor cierra el stream.

**404** si el `run_id` no existe. Response body JSON
`{"detail": "Run not found"}` (no SSE).

## Tests

**Nuevos en `test_runs_api.py`** (3 casos):

1. `test_events_stream_returns_historical_then_eos_for_terminal_run`
   — crear un run en estado `completed` con 3 eventos históricos.
   Consumir el stream con `httpx.AsyncClient` (o el mecanismo
   equivalente de `TestClient`). Verificar que llegan los 3 eventos
   en orden + un evento `eos` final; que el stream se cierra.
2. `test_events_stream_emits_new_events_for_running_run` — crear
   un run `running` con 1 evento. Arrancar consumer en background.
   Desde el test, añadir 2 eventos más a DB con delay. Luego flipear
   `run.status='completed'` y añadir el evento final. Verificar que
   el consumer recibe los 4 eventos + `eos` en orden.
3. `test_events_stream_404_for_missing_run` — pedir run_id
   inexistente → 404 JSON.

**Baseline tras PR-V1-09:**
- Backend: **59 passed** (56 actuales + 3 SSE).
- Frontend: 4 passed (no tocado).

## Criterio de hecho

- [ ] `GET /api/runs/{run_id}/events` responde con
  `content-type: text/event-stream`.
- [ ] Un run `completed` emite todos sus eventos históricos + `eos`
  inmediatamente y cierra.
- [ ] Un run `running` emite históricos, tail-polls cada 200 ms,
  emite cada evento nuevo al llegar, y cierra tras el `eos` del
  evento terminal.
- [ ] Heartbeat comentario `: heartbeat\n\n` cada 15 s.
- [ ] 404 JSON si run no existe.
- [ ] No hay busy-loop: el tail duerme con `await asyncio.sleep`.
- [ ] `pytest -q` → 59 passed.
- [ ] HANDBOOK actualizado con sección "SSE run events (PR-V1-09)":
  URL, formato, comportamiento en runs terminales vs vivos,
  heartbeat, límites conocidos.
- [ ] Codex-reviewer ejecutado.

## Riesgos conocidos

- **Busy-loop en tail.** Usa `await asyncio.sleep(0.2)` entre polls.
  No hagas `while True: query()`. Documentado.
- **Client disconnect no drena.** FastAPI detecta `ClientDisconnect`
  sobre `Request`; el generador debe chequear o permitir que el
  runtime cierre el task. `StreamingResponse` maneja esto si el
  generador es async y cooperativo.
- **Race históricos↔nuevos.** Para evitar perder eventos entre el
  query del histórico y el inicio del tail: el tail usa
  `WHERE id > last_emitted_id ORDER BY id ASC`. El `last_emitted_id`
  se inicializa al mayor `id` del histórico inmediatamente antes
  del primer yield. Garantiza orden monotónico por `id` aunque
  `created_at` tenga colisiones.
- **Sessions SQLAlchemy dentro de async.** FastAPI + SQLAlchemy v2
  síncrono ya está en uso (no asyncpg). Opciones: (a) `asyncio.to_thread`
  para las queries dentro del generator async; (b) una session
  dedicada con scope limitado al stream. Recomiendo **(a)**: mínimo
  cambio, no introduce AsyncSession en el proyecto.
- **Timeouts de proxy.** Heartbeat cada 15 s previene cierre de
  keep-alives intermedios. Nginx/Caddy podrían necesitar config
  aparte; fuera del MVP (binding local sin proxy).
- **Eventos batch vs uno a uno.** El adapter commitea uno por
  evento (PR-V1-07), así que cada poll ve eventos nuevos
  incrementalmente. No hay rebatching necesario.

## Notas para Claude Code

- Commits sugeridos:
  1. `feat(backend): sse event stream helpers`
  2. `feat(backend): sse endpoint for run events`
  3. `test(backend): sse stream terminal run`
  4. `test(backend): sse stream running run with tail`
  5. `test(backend): sse 404 on missing run`
  6. `docs(v1): handbook sse section`
- El generator async no debe mantener una `Session` abierta todo el
  tiempo. Patrón recomendado:
  ```python
  async def stream():
      last_id = 0
      # historical
      events = await asyncio.to_thread(_load_initial, run_id)
      for e in events:
          yield _format_sse(e)
          last_id = max(last_id, e.id)
      # tail
      while True:
          run_state = await asyncio.to_thread(_get_run_status, run_id)
          new = await asyncio.to_thread(_load_since, run_id, last_id)
          for e in new:
              yield _format_sse(e)
              last_id = max(last_id, e.id)
          if run_state in TERMINAL_STATES:
              yield _format_eos(run_id, final_run_snapshot)
              return
          # heartbeat slot
          await asyncio.sleep(0.2)
          # emit heartbeat comment every ~15s (count iterations)
  ```
- `_format_sse(event)` devuelve un string completo:
  ```
  id: 42\nevent: assistant\ndata: {"..."}\n\n
  ```
  con `data:` JSON-encoded.
- Test con runs vivos: usa `asyncio.create_task` o la fixture
  `httpx.AsyncClient` + `stream()` del SDK de httpx. Cronometra con
  `asyncio.wait_for` para no colgar el suite si el servidor no
  cierra.
- Si algo del SPEC queda ambiguo (p.ej. orden exacto de campos en
  `data` payload), sigue el brief y documenta.
