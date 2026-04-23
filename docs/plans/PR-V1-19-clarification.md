# PR-V1-19 — Clarification round-trip: waiting_input + respond

**Semana:** 5 (cierre)
**Esfuerzo:** M
**Depende de:** PR-V1-18 mergeado.

## Qué

Cierra el ciclo de clarificación:

1. **Verifier cambia**: cuando la E2 detecta que el último mensaje
   assistant termina en `?` (antes: `error_code=question_unanswered`
   + `task.status=failed`), ahora el verificador emite una señal
   `needs_input` con el texto de la pregunta. El executor mapea
   eso a:
   - `task.status = "waiting_input"`.
   - `task.pending_question = <texto de la pregunta>`.
   - `run.status = "failed"` con `outcome="needs_input"`
     (run-level el adapter no produjo output completo; task-level
     queda a la espera).
2. **Endpoint nuevo**: `POST /api/tasks/{id}/respond` con body
   `{"response": "texto"}`:
   - Valida `task.status == "waiting_input"`; si no → 409.
   - Escribe `TaskEvent(kind="message",
     payload_json={"event":"user_response", "text": ...})`.
   - `task.status = "queued"`, `task.pending_question = None`.
   - `TaskEvent(kind="status_changed",
     payload_json={"from":"waiting_input","to":"queued"})`.
   - Response 200 con task payload.
3. **UI**: en `/projects/:slug/tasks/:id`, si
   `task.status === "waiting_input"`:
   - Banner "Niwa necesita tu respuesta" + texto de
     `task.pending_question`.
   - `<Textarea>` + botón "Responder".
   - Submit → `POST /api/tasks/:id/respond`; en éxito invalida
     la query del task y refresca.

**Known limitation MVP (explícita)**: el siguiente run del
adapter NO recibe el historial — arranca con prompt fresco desde
`_build_prompt(task)`. La respuesta del usuario queda en
`task_events` para audit pero el CLI no la lee. Follow-up añadirá
composite prompt (original + pregunta previa + respuesta).

## Por qué

SPEC §1: "puede responder si Niwa hace una pregunta (clarification
round-trip)". SPEC §9 Semana 5 pide el ciclo completo. Sin este
PR, las tasks que acababan con pregunta iban a `failed` con el
error_code `question_unanswered` y el usuario tenía que recrear
la task a mano.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── verification/
│   │   ├── models.py                       # +needs_input field
│   │   └── core.py                         # propaga needs_input
│   ├── executor/
│   │   └── core.py                         # maps outcome needs_input → waiting_input
│   ├── api/
│   │   └── tasks.py                        # +POST /{id}/respond
│   └── schemas/
│       └── tasks.py                        # +TaskRespondPayload
└── tests/
    ├── test_tasks_api.py                   # +3 cases respond
    └── test_verification_integration.py    # 1 case waiting_input end-to-end

v1/frontend/
├── src/
│   ├── api.ts                              # +respondTask fetcher
│   └── features/tasks/
│       ├── api.ts                          # +useRespondTask mutation
│       └── TaskDetail.tsx                  # banner + form
└── tests/
    └── TaskDetail.test.tsx                 # +2 cases waiting_input
```

**HARD-CAP 400 LOC netas código+tests** (sin HANDBOOK). Proyección
~350. Si vas a exceder, PARAS.

## Fuera de scope (explícito)

- **No hay composite prompt**: el siguiente adapter run no ve la
  respuesta. Follow-up.
- **No hay resume del CLI** (`claude --resume session_id`). No se
  toca `session_handle`. Follow-up.
- **No hay UI para cancelar el waiting_input** (p.ej., "convert to
  failed"). Follow-up.
- **No hay multi-turn** (varios rounds de pregunta/respuesta). Se
  soporta implicit: cada vez que acabe en `?`, vuelve a
  waiting_input.
- **No hay validación de contenido de la respuesta** (longitud
  mínima, etc.). Solo no-vacío.
- **No hay notificación** cuando task entra waiting_input. UI polling
  del 06b lo refleja.
- **No se toca adapter, triage, finalize, bootstrap, niwa_cli,
  deploy, readiness**.
- **Schema**: `task.pending_question` ya existe (PR-V1-02) y
  `task.status` ya soporta `waiting_input`. No migración.

## Dependencias nuevas

- **Ninguna**.

## Contrato funcional

### Verification change

`VerificationResult` ya tiene `passed`, `outcome`, `error_code`,
`evidence`. Nuevo campo opcional:

```python
@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    outcome: str                      # "verified" | "verification_failed" | "needs_input"
    error_code: str | None
    evidence: dict[str, Any]
    pending_question: str | None = None   # NUEVO
```

En `stream.py::check_stream_terminated`, la rama
`question_unanswered` devuelve ahora:
- `outcome="needs_input"` (no `verification_failed`).
- `error_code=None` (no es fallo).
- `pending_question=<texto del último assistant>`.

### Executor `_finalize` extendido

Actualmente: `outcome=="verified"` → run completed + task done.
Otro outcome → run failed + task failed.

Tras 19:
- `outcome=="verified"` → run completed + task done.
- `outcome=="needs_input"` → run **failed** (no hubo output
  completo) + task **waiting_input** + `task.pending_question`
  populado desde `VerificationResult.pending_question`.
  TaskEvent(kind="status_changed", {"from":"running",
  "to":"waiting_input"}).
- cualquier otro → run failed + task failed (como hoy).

### Endpoint `POST /api/tasks/{id}/respond`

Body: `TaskRespondPayload(response: str)` — validación
`min_length=1, max_length=10000`.

Flow:
1. Fetch task por id; 404 si no existe.
2. Si `task.status != "waiting_input"` → 409
   `{"detail": "Task is not waiting for input"}`.
3. `TaskEvent(kind="message", payload_json=json.dumps(
   {"event":"user_response", "text": payload.response}))`.
4. `task.status = "queued"`; `task.pending_question = None`.
5. `TaskEvent(kind="status_changed",
   payload_json=json.dumps({"from":"waiting_input","to":"queued"}))`.
6. Commit; return task payload.

### UI `TaskDetail` extendido

Condicional render:

```tsx
{task.status === "waiting_input" && task.pending_question && (
  <Alert color="yellow" title="Niwa necesita tu respuesta" mb="md">
    <Text mb="sm">{task.pending_question}</Text>
    <Textarea
      value={response}
      onChange={(e) => setResponse(e.currentTarget.value)}
      minRows={3}
    />
    <Button
      mt="sm"
      onClick={() => respondMutation.mutate({ response })}
      disabled={!response.trim() || respondMutation.isPending}
    >
      Responder
    </Button>
  </Alert>
)}
```

Hook `useRespondTask(taskId)`:
```ts
export function useRespondTask(taskId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { response: string }) =>
      apiFetch<Task>(`/tasks/${taskId}/respond`, {
        method: "POST",
        body: JSON.stringify(payload),
        headers: { "content-type": "application/json" },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["task", taskId] }),
  });
}
```

## Tests

### Backend `test_tasks_api.py` — 3 nuevos

1. `test_respond_transitions_waiting_input_to_queued` — seed task
   con `status="waiting_input"`, `pending_question="ok?"`.
   POST `/respond` con body `{"response":"yes"}`. Response 200.
   DB: task status=`queued`, pending_question=None. TaskEvents:
   `message` con payload user_response; `status_changed` with
   from waiting_input to queued.
2. `test_respond_returns_409_if_not_waiting_input` — task en
   `done`. POST → 409. No side effects en DB.
3. `test_respond_404_on_missing_task` — id=9999 → 404.

### Backend `test_verification_integration.py` — 1 nuevo

4. `test_stream_ending_in_question_puts_task_in_waiting_input` —
   fake CLI emite assistant con texto `"... what should I do?"`.
   Tras process_pending: `task.status="waiting_input"`,
   `task.pending_question="what should I do?"` (o el texto
   completo, según extracción), `run.outcome="needs_input"`,
   `run.status="failed"`.

### Frontend `TaskDetail.test.tsx` — 2 nuevos

5. `test_shows_banner_and_form_for_waiting_input` — mock task con
   waiting_input + pending_question. Banner visible, textarea
   rendered, button disabled on empty, enabled on non-empty.
6. `test_submits_response_and_invalidates_task_query` — mock
   fetch para `/api/tasks/:id/respond`; verifica que la mutation
   dispara el POST con payload correcto y que la query invalida.

**Baseline tras PR-V1-19**: backend 124 → **≥128 passed**.
Frontend 10 → **12 passed**.

## Criterio de hecho

- [ ] Task con verify acabando en `?` → `waiting_input` +
  `pending_question` populado; run `failed` outcome
  `needs_input`.
- [ ] POST `/api/tasks/:id/respond` con task en waiting_input
  transiciona a queued, clears pending_question, escribe los 2
  TaskEvents.
- [ ] 409 si task no está en waiting_input; 404 si no existe.
- [ ] `/projects/:slug/tasks/:id` muestra banner + form cuando
  waiting_input; submit dispara la mutation y refresca.
- [ ] `pytest -q` → ≥128 passed.
- [ ] `npm test -- --run` → ≥12 passed.
- [ ] HANDBOOK sección "Clarification round-trip (PR-V1-19)"
  con flujo, known limitation (no composite prompt), contrato
  del endpoint.
- [ ] Codex ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests ≤ **400**. Proyección ~350.

## Riesgos conocidos

- **Question text extraction**: `stream.py` ya tiene la lógica
  para concatenar `content[].text` del último assistant. Se
  reutiliza; el texto extraído pasa como `pending_question`. Si
  el assistant pregunta con contexto muy largo, se trunca? No,
  se guarda completo. Columna `pending_question` es String; OK.
- **Race entre response y executor**: si el user responde
  mientras el executor procesa otra cosa, no hay problema — la
  task queda `queued` y el executor la tomará cuando el daemon
  haga `claim_next_task`. SQLite WAL maneja la concurrencia.
- **Múltiples responses al mismo waiting_input**: el endpoint
  valida status=waiting_input. Si llegan dos POSTs concurrentes,
  el 2º verá `queued` y dará 409. Aceptable.
- **No composite prompt**: documentado arriba. El siguiente run
  no conoce la respuesta. User debe entender esa limitación.

## Notas para Claude Code

- Commits sugeridos (6):
  1. `feat(verification): emit needs_input when stream ends in question`
  2. `feat(executor): map needs_input outcome to waiting_input task state`
  3. `feat(api): POST /tasks/{id}/respond endpoint`
  4. `test(api): respond endpoint cases + verification integration`
  5. `feat(frontend): waiting_input banner and respond form`
  6. `test(frontend): task detail waiting_input cases`
  7. `docs(v1): handbook clarification round-trip`
- `VerificationResult.pending_question` con default `None` para no
  romper call-sites existentes.
- En executor, `_finalize` firma ya acepta `error_code` opcional
  (PR-V1-11a); añadir manejo de `outcome=="needs_input"` es una
  rama extra en el if-tree.
- Frontend: reutiliza `useProject`, `useLatestRun` existentes; solo
  añade `useRespondTask` mutation.
- **Si algo ambiguo, PARA y reporta.**
