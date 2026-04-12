# Niwa v0.2 — Especificación de implementación

**Status:** frozen
**Branch:** `v0.2`
**Target:** 6–8 semanas de trabajo no-jornada-completa

---

## 1. Decisión de producto

Dos modos de instalación y ejecución:

**Core mode**
- Niwa standalone.
- Web UI propia.
- Chat web mínimo de fallback.
- Tareas, proyectos, runs, approvals, observabilidad.

**Assistant mode**
- Niwa + OpenClaw.
- OpenClaw aporta Telegram y capa conversacional.
- Niwa sigue siendo el system of record y el motor operativo.

**Regla dura:**
- OpenClaw decide el modelo conversacional del chat.
- Niwa decide el backend de ejecución de tareas.
- No mezclar ambas decisiones en una sola tabla ni en un solo router.

---

## 2. Objetivo funcional de v0.2

Cerrar un sistema que permita:

- Crear tareas desde web o desde OpenClaw.
- Enrutar la tarea a un backend de ejecución.
- Ejecutarla con Claude Code o Codex.
- Ver progreso, logs, artefactos, approvals y resultado final en Niwa.
- Reanudar, cancelar o hacer fallback de forma auditable.
- Funcionar en Mac mini y en VPS 4–8 GB, dejando claro que el VPS pequeño es para control plane + APIs/CLI remotos, no para modelos locales pesados.

---

## 3. Fuera de v0.2

No implementar en esta fase:

- app desktop
- bot propio de Telegram en Niwa
- Gemini/Ollama como backend de ejecución
- router con ML/LLM
- multiusuario/multitenant
- loops autónomos que creen tareas solos
- coste facturado real
- refactor completo a framework web nuevo

---

## 4. Backlog técnico (orden de ejecución)

### PR-00 — Rama, ADR y limpieza de contradicciones

Crear rama `v0.2`.

**Entregables:**
- `docs/adr/0001-v02-architecture.md`
- `docs/v0.2-scope.md`
- `docs/state-machines.md`

**Decisiones que deben quedar escritas:**
- Niwa core standalone + Assistant mode opcional.
- OpenClaw no es dependencia dura global.
- `assigned_to_claude` deja de ser semántica de routing.
- `waiting_input` será el estado canónico; `revision` queda solo para revisión humana final o se elimina de los flows automáticos.
- `backend_run` nace al iniciar ejecución, no al enrutar.

**Corregir documentación stale:**
- INSTALL/README/OpenClaw config deben dejar de enseñar SSE como camino principal y estandarizar `streamable-http` para Assistant mode.
- Asumir que `mcp set` no valida conexión: el install debe hacer smoke test real.

### PR-01 — Extensión de schema y migraciones

No romper la base actual. Añadir migración `007_v02_execution_core.sql` y actualizar `schema.sql`.

**Tablas nuevas:**

```
backend_profiles
  id, slug, display_name, backend_kind (claude_code|codex),
  runtime_kind (cli|api|acp|local), default_model, command_template,
  capabilities_json, enabled, priority, created_at, updated_at

routing_rules
  id, name, position, enabled, match_json, action_json,
  created_at, updated_at

routing_decisions
  id, task_id, decision_index, requested_profile_id, selected_profile_id,
  reason_summary, matched_rules_json, fallback_chain_json,
  estimated_resource_cost, quota_risk, created_at

backend_runs
  id, task_id, routing_decision_id, previous_run_id,
  relation_type (fallback|resume|retry),
  backend_profile_id, backend_kind, runtime_kind, model_resolved,
  session_handle, status, capability_snapshot_json, budget_snapshot_json,
  observed_usage_signals_json, heartbeat_at, started_at, finished_at,
  outcome, exit_code, error_code, artifact_root,
  created_at, updated_at

backend_run_events
  id, backend_run_id, event_type, message, payload_json, created_at

approvals
  id, task_id, backend_run_id, approval_type, reason, risk_level,
  status, requested_at, resolved_at, resolved_by, resolution_note

artifacts
  id, task_id, backend_run_id, artifact_type, path, size_bytes, sha256,
  created_at

project_capability_profiles
  id, project_id, name, repo_mode, shell_mode, web_mode, network_mode,
  filesystem_scope_json, secrets_scope_json, resource_budget_json,
  created_at, updated_at

secret_bindings
  id, project_id, backend_profile_id, secret_name, provider,
  created_at, updated_at
```

**Cambios sobre tablas existentes:**
- `tasks`: añadir `requested_backend_profile_id`, `selected_backend_profile_id`, `current_run_id`, `approval_required`, `quota_risk`, `estimated_resource_cost`.
- Deprecar `assigned_to_claude` y `assigned_to_yume`; no borrar, marcar como legacy.
- Índices: `tasks(status, source, updated_at)`, `backend_runs(task_id, status)`, `approvals(status, requested_at)`.

### PR-02 — Máquina de estados canónica

`tasks` mantiene sus estados actuales para la capa humana/UI, con transiciones forzadas.

**`tasks.status`:**

```
inbox       -> pendiente
pendiente   -> en_progreso | bloqueada | archivada
en_progreso -> waiting_input | revision | bloqueada | hecha | archivada
waiting_input -> pendiente | archivada
revision    -> pendiente | hecha | archivada
bloqueada   -> pendiente | archivada
```

**`backend_runs.status`:**

```
queued -> starting -> running
running -> waiting_approval | waiting_input | succeeded | failed | cancelled | timed_out
waiting_approval -> running | rejected
waiting_input    -> queued | cancelled
```

**Reglas:**
- `routing_decision` se crea cuando la tarea pasa a `pendiente`.
- `backend_run` se crea cuando un worker reclama y empieza ejecución.
- Fallback crea run nuevo con `relation_type='fallback'`.
- Resume crea run nuevo con `relation_type='resume'`.
- Retry crea run nuevo con `relation_type='retry'`.

**Incoherencias a eliminar:**
- `task_request_input` debe usar `waiting_input`, no `revision`.
- `_pipeline_status()` debe contar `waiting_input` como tarea activa o pendiente de intervención.
- `assigned_to_claude` deja de aparecer en prompts/descripciones como contrato de ejecución.

### PR-03 — Abstracción de backends y fin del falso multi-modelo

Obligatorio antes de tocar routing serio.

**Nuevos módulos:**

```
niwa-app/backend/backend_registry.py
niwa-app/backend/backend_adapters/base.py
niwa-app/backend/backend_adapters/claude_code.py
niwa-app/backend/backend_adapters/codex.py
niwa-app/backend/routing_service.py
niwa-app/backend/runs_service.py
niwa-app/backend/approval_service.py
niwa-app/backend/capability_service.py
niwa-app/backend/assistant_service.py
```

No seguir metiendo todo en `app.py` (ya va por miles de líneas y 70+ endpoints).

**Interfaz `BackendAdapter`:**
- `capabilities()`
- `start(task, run, profile, capability_profile)`
- `resume(task, prior_run, new_run, profile, capability_profile)`
- `cancel(run)`
- `heartbeat(run)`
- `collect_artifacts(run)`
- `parse_usage_signals(raw_output)`

**`capabilities()` debe devolver:**
- `resume_modes`
- `fs_modes`
- `shell_modes`
- `network_modes`
- `approval_modes`
- `secrets_modes`

**Punto crítico:**
- Eliminar la lógica actual que convierte cualquier modelo en `claude -p --model ...`.
- `backend_profiles` manda.
- Si el backend es Claude, usa adapter de Claude. Si es Codex, usa adapter de Codex.
- La UI no debe dejar elegir modelos que el adapter no soporte realmente.

### PR-04 — Claude backend real

Implementar Claude Code end-to-end primero.

**Entregables:**
- `start()`, `resume()`, `cancel()`, `heartbeat()`, `collect_artifacts()`
- persistencia de `session_handle`
- logs parciales a `backend_run_events`
- `observed_usage_signals_json`
- `artifact_root`

**Reglas:**
- No usar `--dangerously-skip-permissions` por defecto.
- Solo permitir modo peligroso en perfil avanzado y con approval explícito.
- Si el perfil del proyecto requiere aprobación, el adapter bloquea antes de ejecutar.

### PR-05 — Capability profiles y approvals reales

Hoy el terminal web tiene acceso brutal al host (`/:/host`, `pid: host`, `privileged: true`, `network_mode: host`). Sacarlo del camino estándar y del quick setup.

**Policy mínima:**
- `repo_mode`: `none|read-only|read-write`
- `shell_mode`: `disabled|whitelist|free`
- `web_mode`: `off|on`
- `network_mode`: `off|on|restricted`
- `filesystem_scope_json`
- `secrets_scope_json`
- `resource_budget_json`

**Approval gate obligatorio para:**
- escritura fuera de workspace
- borrado
- shell fuera de whitelist
- red cuando no esté permitida
- `quota_risk >= medium`
- `estimated_resource_cost > threshold`

**Además:**
- Desactivar terminal por defecto en `install --quick`.
- Moverlo a modo avanzado/operador.

### PR-06 — Router determinista v0.2

Sin LLM routing. `routing_service.py` con reglas persistidas en DB.

**Reglas iniciales:**
- Pin explícito del usuario gana.
- Si capability profile bloquea la tarea, crear approval o rechazar.
- Si la tarea es resume, priorizar backend del run previo si soporta resume.
- Refactor multiarchivo, repo amplio, cambios complejos → Claude.
- Parche acotado, lectura local, grep/edit/test loop corto → Codex.
- Si backend falla por auth/rate limit/timeout → fallback según cadena definida.
- Si `estimated_resource_cost` supera umbral → approval antes de ejecutar.

**Persistir en `routing_decisions`:**
- reglas que hicieron match
- backend seleccionado
- razón resumida
- fallback chain
- coste estimado
- quota risk

### PR-07 — Codex backend

Solo tras Claude sólido.

**Entregables:**
- Adapter Codex: `start`, `resume` si aplica, `cancel`, `heartbeat`, `collect_artifacts`.
- Integración con capability profile.
- Generación de `backend_runs`.
- Fallback Claude ↔ Codex.

No meter Gemini, Ollama ni APIs sueltas aquí.

### PR-08 — Conversación unificada: `assistant_turn`

Una sola lógica conversacional. `chat_sessions`/`chat_messages` en schema sobrevive como fallback nativo, no como segundo producto.

**Servicio y endpoint `assistant_turn`:**
- Entrada: `session_id`, `project_id`, `message`, `channel`, `metadata`.
- Salida: `assistant_message`, `actions_taken`, `task_ids`, `approval_ids`, `run_ids`.

**Reglas:**
- El chat web nativo de Niwa usa `assistant_turn`.
- OpenClaw también usa `assistant_turn` por MCP.
- Niwa decide si responde directo, crea tarea, pide approval, resume o consulta estado.

**Tools de dominio expuestas a OpenClaw (no CRUD ciego):**
- `assistant_turn`
- `task_list`, `task_get`, `task_create`, `task_cancel`, `task_resume`
- `approval_list`, `approval_respond`
- `run_tail`, `run_explain`
- `project_context`

### PR-09 — MCP contract v0.2 y Assistant mode con OpenClaw

`config/mcp-catalog/*.json` sigue siendo fuente de verdad y se filtra por contract.

**Tareas:**
- Crear `config/mcp-contract/v02-assistant.json`.
- Incluir solo las tools necesarias para OpenClaw.
- Añadir `assistant_turn`, `task_cancel`, `task_resume`, `approval_list`, `approval_respond`, `run_tail`, `run_explain`.
- Retirar del contract herramientas no necesarias para conversación.

**Assistant mode:**
- Un único endpoint MCP de Niwa detrás del gateway.
- `streamable-http`.
- Auto-registro en OpenClaw con `mcp set`.
- Smoke test real después del registro, no asumir éxito porque el config se haya guardado.

No usar `openclaw mcp serve`. OpenClaw consume a Niwa. ACP es vía futura, no v0.2.

### PR-10 — Web UI v0.2

**Vistas nuevas:**
- `backend_runs`
- `routing_decisions`
- `approvals`
- `artifacts`
- `backend_profiles`
- `project_capability_profiles`

**Pantallas mínimas:**
- detalle de tarea con timeline
- lista de runs por tarea
- explicación del routing
- approvals pendientes
- vista de artefactos/logs
- ajustes de backend/capabilities por proyecto

El chat web sigue mínimo, usando `assistant_turn`.

### PR-11 — Instalador `--quick`

**Modos:**
- `niwa install --quick --mode core`
- `niwa install --quick --mode assistant`

**Preguntas máximas:**
- workspace root
- local-only o URL pública
- activar OpenClaw Assistant mode sí/no
- credenciales Claude detectadas/configuradas
- credenciales Codex detectadas/configuradas

**Reglas:**
- Terminal desactivado por defecto.
- Imágenes Docker pinneadas, no `latest` en quick mode (`mcp-gateway` y `mcp-gateway-sse` están en `:latest` hoy; deriva operacional innecesaria).
- Si OpenClaw está presente, registrar MCP automáticamente.
- Smoke test final con resultado claro.

### PR-12 — Tests de verdad

Los smoke tests actuales y el E2E basado en `assigned_to_claude=1` no sirven para v0.2. Reescribir alrededor del nuevo contrato.

**Cobertura:**
- migración 007 idempotente
- creación de `routing_decision`
- creación de `backend_run` al claim real
- fallback crea run nuevo con `relation_type='fallback'`
- resume crea run nuevo con `relation_type='resume'`
- `task_request_input` usa `waiting_input`
- `_pipeline_status()` cuenta `waiting_input`
- capability profile bloquea filesystem fuera de scope
- approval gate se crea antes de ejecutar
- Claude backend `start/resume/cancel`
- Codex backend `start/cancel`
- `assistant_turn` crea tarea o responde según contexto
- install core
- install assistant
- OpenClaw registration smoke
- contract MCP exacto para Assistant mode

---

## 5. Bugs concretos a arreglar sí o sí

1. Quitar el falso multi-modelo que termina en `claude -p`.
2. Eliminar `--dangerously-skip-permissions` del camino por defecto.
3. Resolver la mentira de `assigned_to_claude` vs executor real.
4. Normalizar `waiting_input` vs `revision`.
5. Hacer que `pipeline_status` cuente `waiting_input`.
6. Sacar terminal del quick/default path.
7. Estandarizar OpenClaw en `streamable-http` y smoke test post-registro.

---

## 6. Definition of Done

No cerrar v0.2 hasta cumplir **todo**:

1. Core mode funciona sin OpenClaw.
2. Assistant mode instala/registra OpenClaw y deja Telegram/chat operativo.
3. Un mensaje desde OpenClaw entra por `assistant_turn`.
4. Claude Code y Codex ejecutan tareas reales end-to-end.
5. Cada ejecución queda en `backend_runs` con timeline, heartbeat y outcome.
6. Fallback y resume crean runs nuevos enlazados.
7. Approval bloquea al menos una tarea real antes de ejecutar.
8. Niwa UI muestra routing, runs, approvals y artefactos.
9. Install quick cabe en Mac y Linux en menos de 10 minutos.
10. VPS 4–8 GB soporta control plane + runners remotos; Mac mini soporta además el camino local.

---

## 7. Notas de implementación (no bloqueantes)

- **Orden PR-08 / PR-09:** `assistant_turn` se diseña antes del contract MCP que lo consume. Aceptable, pero esperar pequeñas revisiones a PR-08 tras cerrar el contract en PR-09.
- **Tests distribuidos:** escribir tests de migración en PR-01 y de máquina de estados en PR-02, no dejar todo para PR-12.
- **Versionado del contract MCP:** añadir `contract_version` en `routing_decisions` o `backend_runs` para que auditorías antiguas sepan qué contrato estaba activo.

---

## 8. Reglas de comportamiento para la IA implementadora

Estas reglas aplican a cualquier agente (Claude Code, Codex, etc.) que implemente un PR de este documento. Se le pasan como parte del prompt inicial.

### Lo que SÍ debe hacer

- Leer `docs/SPEC-v0.2.md` completo antes de escribir código.
- Leer el código existente relevante antes de editarlo. Nunca editar un archivo sin haberlo leído primero.
- Implementar solo el PR asignado. Si detecta trabajo que pertenece a otro PR, parar y reportarlo al humano.
- Escribir tests para el código que escribe, en el mismo PR, no después.
- Dejar la rama `v0.2` en estado mergeable al final de cada sesión: compila, tests pasan, no hay código muerto ni imports rotos.
- Hacer commits pequeños y descriptivos, no un commit gigante por PR.
- Actualizar la documentación afectada (README, INSTALL, comentarios) cuando el cambio lo requiera.
- Preguntar antes de cambiar cualquier decisión del SPEC, por pequeña que parezca (nombre de columna, tipo de enum, orden de operaciones).
- Preguntar cuando una dependencia entre PRs no esté clara.
- Si encuentra un bug preexistente fuera del scope del PR actual, documentarlo en `docs/BUGS-FOUND.md` y seguir, no arreglarlo en este PR.

### Lo que NO debe hacer

- No adelantar trabajo de PRs futuros "porque lo vio necesario".
- No refactorizar código que funciona y está fuera del scope del PR.
- No añadir features no listadas en el SPEC.
- No cambiar nombres de tablas, columnas, enums, endpoints o archivos sin confirmación explícita.
- No introducir dependencias nuevas (librerías Python, paquetes npm) sin confirmación. El backend es stdlib, mantenerlo así.
- No usar `--dangerously-skip-permissions`, `sudo`, ni equivalentes en ningún comando que el código genere.
- No asumir éxito de operaciones que no ha verificado (registro MCP, install, migración). Siempre smoke test real.
- No escribir código que ejecute LLMs para tomar decisiones de routing, clasificación de tareas o generación de reglas. El router es determinista.
- No tocar `main`. Todo el trabajo en `v0.2`.
- No modificar migraciones ya mergeadas. Si una migración vieja está mal, crear una nueva que corrija.
- No mezclar dos PRs en uno, aunque parezcan relacionados.

### Formato de entrega de cada PR

Al terminar un PR, el agente debe dejar en el chat:

1. Lista de archivos creados/modificados/eliminados.
2. Lista de tests añadidos y cómo ejecutarlos.
3. Comandos para verificar que el PR funciona (migración, endpoint, etc.).
4. Cualquier decisión que haya tomado que no estaba explícita en el SPEC.
5. Cualquier bloqueante o duda pendiente.
6. Propuesta de mensaje de merge commit.

### Escalado al humano

El agente debe parar y preguntar cuando:

- El SPEC es ambiguo o contradictorio en el punto concreto que está tocando.
- Una decisión de diseño afecta a PRs futuros de forma no reversible.
- Encuentra que una parte del código actual viola premisas del SPEC (ej: el flag peligroso aparece en más sitios de los documentados).
- Un test falla y la causa no está clara.
- El scope se le queda corto para terminar el PR.

No debe parar para preguntar trivialidades de estilo ni decisiones internas del archivo que no afectan al contrato externo.

---

## 9. Prompt maestro para sesión limpia

Este prompt se pega al agente al empezar cada PR, reemplazando las partes marcadas con `{{...}}`.

````
Vas a implementar el PR-{{NÚMERO}} del proyecto Niwa v0.2.

CONTEXTO OBLIGATORIO ANTES DE EMPEZAR:

1. Lee el documento de especificación completo:
   https://github.com/yumewagener/niwa/blob/v0.2/docs/SPEC-v0.2.md

2. Presta especial atención a:
   - El apartado 8 (Reglas de comportamiento). Se aplican estrictamente.
   - El apartado del PR que vas a implementar (PR-{{NÚMERO}}).
   - Las dependencias con PRs anteriores ya mergeados.

3. Lee el estado actual del repo en la rama v0.2:
   https://github.com/yumewagener/niwa/tree/v0.2

4. Lee el log de decisiones tomadas hasta ahora:
   https://github.com/yumewagener/niwa/blob/v0.2/docs/DECISIONS-LOG.md

TAREA:

Implementa ÚNICAMENTE el PR-{{NÚMERO}} tal como está descrito en el SPEC.

Restricciones:
- No adelantes trabajo de otros PRs.
- No refactorices código fuera del scope.
- No cambies nombres ni decisiones del SPEC sin preguntarme antes.
- Si el SPEC es ambiguo, para y pregúntame.
- Si encuentras bugs fuera del scope, anótalos en docs/BUGS-FOUND.md y sigue.
- No uses flags peligrosos (--dangerously-skip-permissions o similares).
- Tests incluidos en este mismo PR.

PRs ya mergeados en v0.2:
{{LISTA: ej "PR-00, PR-01" o "ninguno" si es el primero}}

Notas adicionales del humano:
{{OPCIONAL: cualquier cosa específica para este PR}}

Cuando termines, entrega el formato descrito en el apartado 8 del SPEC
(archivos tocados, tests, comandos de verificación, decisiones tomadas,
bloqueantes, mensaje de merge).

Empieza leyendo el SPEC y el estado actual del repo. Confírmame que tienes
el contexto antes de escribir una sola línea de código.
````

### Archivos de soporte que deben existir antes del primer PR

- `docs/SPEC-v0.2.md` — este documento.
- `docs/DECISIONS-LOG.md` — log de decisiones tomadas durante implementación, con fecha. Inicialmente vacío con solo un encabezado.
- `docs/BUGS-FOUND.md` — bugs preexistentes encontrados fuera del scope de cada PR. Inicialmente vacío con solo un encabezado.

---

## 10. Instrucción final para el modelo que lo implemente

Implementa v0.2 en la rama `v0.2`. No reescribas todo el producto. Conserva el backend stdlib, el schema actual y la web existente, pero añade una capa nueva de ejecución auditable con `routing_decisions`, `backend_runs`, `approvals` y `capability_profiles`. Niwa sigue siendo el core standalone. OpenClaw es opcional y solo obligatorio en Assistant mode.

No uses LLM routing. No añadas Gemini/Ollama como backends de ejecución en v0.2. No añadas app desktop. No añadas multiusuario.

Corrige primero los bugs semánticos existentes (`assigned_to_claude`, `waiting_input`, `pipeline_status`, falso multi-modelo, `--dangerously-skip-permissions`).

Después implementa, en este orden: schema + migrations, state machines, backend adapter abstraction, Claude backend, capability profiles + approvals, deterministic router, Codex backend, `assistant_turn`, MCP contract v0.2, Assistant mode con OpenClaw, web UI nueva, install quick y tests.

Cada PR debe ser pequeño, con migración, tests y documentación actualizada. No rompas v0.1 en `main`.
