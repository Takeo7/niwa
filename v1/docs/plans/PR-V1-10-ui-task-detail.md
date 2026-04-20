# PR-V1-10 — UI task detail con stream en vivo

**Semana:** 2 (cierre)
**Esfuerzo:** M
**Depende de:** PR-V1-09 (endpoint SSE) mergeado.

## Qué

Añade la ruta `/projects/:slug/tasks/:id` al frontend. Muestra
título, descripción, estado, `branch_name` y el stream en vivo del
run activo vía `EventSource` consumiendo el SSE de PR-V1-09. Lista
los eventos recibidos en un timeline simple (fila por evento, con
tipo, timestamp y payload JSON colapsable). Cuando llega el `eos`,
la UI muestra el estado final del run (completed/failed + outcome
+ exit_code). Los items de `TaskList` del `ProjectDetail` pasan a
ser clickables con link a la nueva ruta.

## Por qué

SPEC §7: `/projects/:slug/tasks/:id` con "stream en vivo del run
activo, timeline de eventos". §9 Semana 2 cierra con "stream de
eventos hasta UI" — este PR es el último eslabón. Sin él, el stream
del 09 no se ve en el navegador.

## Scope — archivos que toca

```
v1/frontend/
├── src/
│   ├── App.tsx                                 # +1 route
│   ├── api.ts                                  # tipos Run, RunEvent, RunStatus
│   ├── routes/
│   │   └── TaskDetailRoute.tsx                 # nuevo, solo layout
│   └── features/tasks/
│       ├── api.ts                              # +useTask(id), +useLatestRun(taskId)
│       ├── TaskDetail.tsx                      # nuevo, composición
│       ├── TaskEventStream.tsx                 # nuevo, EventSource hook + timeline
│       └── TaskList.tsx                        # filas clicables a /tasks/:id
└── tests/
    └── TaskEventStream.test.tsx                # 2 casos
```

**Hard-cap:** 400 LOC netas.

## Fuera de scope (explícito)

- **No hay formulario de respuesta** a `waiting_input` — es Semana 5.
- **No hay cancel del run** — no existe endpoint.
- **No hay re-enqueue** — si la task fallida debe reintentarse, el
  usuario la recrea.
- **No hay árbol de ficheros** del proyecto (eso es Semana 4-5).
- **No hay editor/highlighting** de los payloads. `<pre>{JSON}</pre>`
  bastante.
- **No hay virtualización** del timeline. Para runs con >1k eventos
  podría ser lento; follow-up si se observa.
- **No se toca backend.** Este PR es 100% frontend.
- **No hay permissions UI.** Binding local §2.

## Dependencias nuevas

- npm: **ninguna** (`EventSource` es nativo del browser).
- En tests (vitest + jsdom): si `EventSource` no está disponible en
  jsdom, mockearlo en los tests sin añadir polyfill de runtime a la
  app.

## Tests

**Nuevos en `tests/TaskEventStream.test.tsx`** (2 casos):

1. `renders historical events from mocked EventSource` — mock
   `EventSource` con una secuencia de 3 eventos. `TaskEventStream`
   los renderiza como 3 filas del timeline con `event_type` visible.
2. `shows eos summary when stream closes` — el mock dispara un
   evento `eos` con payload `{final_status: "completed",
   exit_code: 0, outcome: "cli_ok"}`. El componente muestra un
   banner "Run completed" + exit code. Tras `eos`, nuevos eventos
   emitidos por el mock se ignoran (suscripción cerrada).

Si los tests requieren mockear `EventSource` globalmente, usa
`vi.stubGlobal("EventSource", MockEventSource)` en el setup del
test, no a nivel `setup.ts` global.

**Baseline tras PR-V1-10:**
- Backend: 59 passed (sin cambios).
- Frontend: **6 passed** (4 actuales + 2 TaskEventStream).

## Criterio de hecho

- [ ] Click en una fila de `TaskList` navega a
  `/projects/<slug>/tasks/<id>`.
- [ ] La ruta renderiza: título, descripción (si hay), estado con
  color (running/done/failed/etc.), `branch_name` si existe,
  timestamps.
- [ ] `TaskEventStream` abre `EventSource` al montar, cierra al
  desmontar (sin leak).
- [ ] El timeline muestra cada evento recibido con: `event_type`,
  timestamp (HH:MM:SS), botón "ver payload" que despliega el JSON
  en `<pre>`.
- [ ] Al llegar el evento `eos`, el `EventSource` se cierra y se
  muestra el banner de resultado final.
- [ ] Si la task no tiene runs aún (`useLatestRun` devuelve null),
  mostrar "Run no iniciado" en vez del timeline.
- [ ] 404 del backend → la ruta muestra "Task no encontrada".
- [ ] `cd v1/frontend && npm test -- --run` → 6 passed.
- [ ] `cd v1/backend && pytest -q` → 59 passed (sin regresión).
- [ ] HANDBOOK actualizado con sección "Task detail + stream
  (PR-V1-10)": estructura componentes, mock de `EventSource` en
  tests, flujo del stream.
- [ ] Codex-reviewer ejecutado.

## Riesgos conocidos

- **EventSource en vite dev proxy.** El proxy de Vite debe mantener
  la conexión abierta; por defecto lo hace. Si hay problemas,
  añadir `timeout: 0` en el config del proxy. Verificar con backend
  corriendo.
- **Reconnect automático de EventSource.** Cuando el stream cierra
  limpiamente tras `eos`, EventSource intentará reconectar
  automáticamente por la semántica SSE. Mitigación: el componente
  llama explícitamente `.close()` tras recibir `eos`, lo que
  **cancela** el reconnect.
- **React 19 StrictMode + EventSource.** El doble-mount del strict
  mode puede abrir dos conexiones. El hook custom debe tener un
  `useEffect` con cleanup que cierre la conexión al unmount —
  estándar, pero verificar que no se duplican filas.
- **JSON payload grande.** Si un evento trae un payload de >10 KB,
  renderizar en `<pre>` bloquea. Mitigación: botón "ver payload" en
  vez de render eager, y truncar a 10 KB con "…more".
- **Orden estable.** Los eventos vienen por SSE en orden del
  servidor (`id` ASC). La UI los appendea en orden. Si el server
  desordena (no debería), el timeline queda desordenado — aceptable
  MVP.

## Notas para Claude Code

- Commits sugeridos:
  1. `feat(frontend): run and run event types`
  2. `feat(frontend): task hooks for single task and latest run`
  3. `feat(frontend): task event stream component`
  4. `feat(frontend): task detail route and layout`
  5. `feat(frontend): link task list rows to detail page`
  6. `test(frontend): task event stream vitest cases`
  7. `docs(v1): handbook task detail section`
- Hook `useEventStream(runId)`:
  ```ts
  type StreamState = {
    events: RunEvent[];
    eos: EosPayload | null;
    error: string | null;
  };
  function useEventStream(runId: number | null): StreamState;
  ```
  Encapsula `new EventSource("/api/runs/:runId/events")`, `onmessage`,
  `onerror`, y cleanup. No expone el `EventSource` crudo.
- `MockEventSource` en tests: clase JS mínima con `addEventListener`,
  `close`, y método `_emit(eventType, data)` para que el test
  dispare eventos sincrónicamente.
- El estado visual:
  - Status badge: `queued` gris, `running` azul pulsing, `done`
    verde, `failed` rojo, `waiting_input` amarillo, `cancelled`
    tachado.
  - `branch_name` mostrado como `<code>`.
- Si hay colisión con cambios de 06b en `TaskList` (p.ej.,
  botón delete vs click para navegar), resolver: click en la fila
  navega, el botón delete tiene `onClick` con `stopPropagation`.
- Si algo ambiguo, sigue el brief y nota en el PR.
