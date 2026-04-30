# Fase 7 — MCP para OpenClaw y otros clientes

Fecha de preparación: 2026-04-30

**Resumen.** Exponer Niwa como servidor MCP seguro para que otros agentes creen tareas, consulten estado, respondan preguntas, gestionen PRs y disparen deploys.

## Contexto

- El MVP excluye MCP hasta que el motor funcione E2E.
- MCP debe ser una capa delgada sobre API/services existentes, no un segundo motor.
- Debe depender de auth/tokens/scopes para no crear una superficie peligrosa.

## No-objetivos

- No permitir acceso arbitrario al filesystem por MCP.
- No exponer herramientas de shell directo.
- No hacer multi-provider LLM.

## Reglas para pasar estas tareas a un LLM implementador

Usa estas reglas como preámbulo de cualquier brief:

1. Trabaja sobre `main` actualizado y lee primero `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md` y el documento de la fase correspondiente.
2. Implementa solo la tarea o PR block indicado. No adelantes fases posteriores aunque parezcan relacionadas.
3. Mantén los cambios pequeños. Si una tarea supera el scope, detente y deja explícito qué sub-tareas nuevas propones.
4. Añade o actualiza tests en el mismo PR. Si no puedes probar algo, explica exactamente por qué y deja un check manual reproducible.
5. Conserva compatibilidad con proyectos/tareas existentes salvo que el brief diga lo contrario.
6. No ocultes fallos. Los errores deben ser visibles por API/UI/logs con causa accionable.
7. No uses servicios externos en tests obligatorios. Claude real, GitHub real, DNS real y TLS real solo van en pruebas live opcionales.
8. Antes de cerrar, ejecuta como mínimo `make test`; cuando exista, ejecuta también `make smoke`.

## Brief base copiable para LLM

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 7 — MCP para OpenClaw y otros clientes.

Contexto: Exponer Niwa como servidor MCP seguro para que otros agentes creen tareas, consulten estado, respondan preguntas, gestionen PRs y disparen deploys.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-MCP-01.** Spec MCP + auth/scopes.
- **PR-MCP-02.** Servidor MCP con project/task tools read/create/status/respond.
- **PR-MCP-03.** Herramientas PR/deploy con scopes.
- **PR-MCP-04.** Resources/prompts + OpenClaw guide.
- **PR-MCP-05.** Tests y smoke MCP.

## Tareas

### MCP-01 — Definir contrato MCP

**Objetivo.** Especificar herramientas, inputs, outputs y permisos.

**Archivos probables.**

- `docs/MCP.md`

**Instrucciones de implementación.**

- Crear docs/MCP.md con tools, schemas, scopes requeridos, ejemplos y errores.
- Mapear cada tool a endpoint/service existente.
- Definir transport inicial: stdio para local o HTTP/SSE si se justifica; elegir uno y documentarlo.

**Tests/verificación.**

- No aplica; docs.

**Criterios de aceptación.**

- Spec aprobada antes de código.
- No hay tool que ejecute shell arbitrario.
- Cada tool declara scope.

**Brief corto para LLM.**

```text
Implementa MCP-01 (Definir contrato MCP) en Niwa. Objetivo: Especificar herramientas, inputs, outputs y permisos. Toca principalmente `docs/MCP.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: No aplica; docs.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-02 — Implementar servidor MCP base

**Objetivo.** Levantar un servidor que autentique y enrute tools.

**Archivos probables.**

- `backend/app/mcp`
- `pyproject.toml`

**Instrucciones de implementación.**

- Añadir módulo backend/app/mcp o scripts/niwa_mcp_server.py.
- Leer API token desde env NIWA_MCP_TOKEN o config segura.
- Conectar con services internos si corre in-process o con API HTTP si corre out-of-process; elegir y documentar tradeoff.

**Tests/verificación.**

- Unit tests servidor con token fake.

**Criterios de aceptación.**

- Cliente MCP puede llamar ping/version.
- Token inválido falla.
- Logs no muestran token.

**Brief corto para LLM.**

```text
Implementa MCP-02 (Implementar servidor MCP base) en Niwa. Objetivo: Levantar un servidor que autentique y enrute tools. Toca principalmente `backend/app/mcp`, `pyproject.toml`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Unit tests servidor con token fake.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-03 — Tool project_list

**Objetivo.** Listar proyectos disponibles.

**Archivos probables.**

- `backend/app/mcp/tools/projects.py`

**Instrucciones de implementación.**

- Input opcional: include_archived false si existe.
- Output: slug, name, kind, status summary, public/deploy status si existe.
- Scope requerido: read.

**Tests/verificación.**

- MCP tool test.

**Criterios de aceptación.**

- Devuelve proyectos sin exponer secretos/local_path si policy lo limita.
- Schema estable.

**Brief corto para LLM.**

```text
Implementa MCP-03 (Tool project_list) en Niwa. Objetivo: Listar proyectos disponibles. Toca principalmente `backend/app/mcp/tools/projects.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP tool test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-04 — Tool project_get

**Objetivo.** Consultar detalle útil de proyecto.

**Archivos probables.**

- `backend/app/mcp/tools/projects.py`

**Instrucciones de implementación.**

- Input slug.
- Output settings no sensibles, tareas activas, PRs/deploys resumidos.
- No devolver tokens ni env secrets.

**Tests/verificación.**

- MCP tool test.

**Criterios de aceptación.**

- project_get no filtra secretos.
- 404 claro si no existe.

**Brief corto para LLM.**

```text
Implementa MCP-04 (Tool project_get) en Niwa. Objetivo: Consultar detalle útil de proyecto. Toca principalmente `backend/app/mcp/tools/projects.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP tool test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-05 — Tool task_create

**Objetivo.** Crear tareas desde OpenClaw/otros agentes.

**Archivos probables.**

- `backend/app/mcp/tools/tasks.py`

**Instrucciones de implementación.**

- Inputs: project_slug, title, description, priority opcional, approval_mode override opcional si permitido.
- Validar title/description igual que API.
- Registrar audit event actor token.

**Tests/verificación.**

- MCP tool test con scopes.

**Criterios de aceptación.**

- Crea task queued/inbox según contrato.
- Token sin task:create falla.
- UI muestra tarea creada por MCP si se implementa actor.

**Brief corto para LLM.**

```text
Implementa MCP-05 (Tool task_create) en Niwa. Objetivo: Crear tareas desde OpenClaw/otros agentes. Toca principalmente `backend/app/mcp/tools/tasks.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP tool test con scopes.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-06 — Tool task_status

**Objetivo.** Consultar progreso completo.

**Archivos probables.**

- `backend/app/mcp/tools/tasks.py`

**Instrucciones de implementación.**

- Input task_id.
- Output status, plan latest, review latest, pending_question, runs summary, pr_url, deploy url si aplica.
- No devolver payloads raw gigantes por defecto; añadir include_raw opcional.

**Tests/verificación.**

- MCP tool test.

**Criterios de aceptación.**

- Un agente externo puede decidir si responder, esperar o revisar PR.
- Output compacto y estructurado.

**Brief corto para LLM.**

```text
Implementa MCP-06 (Tool task_status) en Niwa. Objetivo: Consultar progreso completo. Toca principalmente `backend/app/mcp/tools/tasks.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP tool test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-07 — Tool task_respond

**Objetivo.** Responder tareas waiting_input.

**Archivos probables.**

- `backend/app/mcp/tools/tasks.py`

**Instrucciones de implementación.**

- Input task_id, response.
- Solo permitido si task waiting_input.
- Registrar audit event.

**Tests/verificación.**

- MCP tool test.

**Criterios de aceptación.**

- Respuesta reencola o desbloquea igual que API.
- 409 claro si no espera input.

**Brief corto para LLM.**

```text
Implementa MCP-07 (Tool task_respond) en Niwa. Objetivo: Responder tareas waiting_input. Toca principalmente `backend/app/mcp/tools/tasks.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP tool test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-08 — Tool task_cancel y task_retry

**Objetivo.** Operar tareas sin UI.

**Archivos probables.**

- `backend/app/mcp/tools/tasks.py`

**Instrucciones de implementación.**

- Inputs task_id y reason/instructions opcional.
- Scopes task:write.
- Respetar las mismas reglas que UI/API.

**Tests/verificación.**

- MCP tool tests.

**Criterios de aceptación.**

- Cancel/retry por MCP tiene mismos efectos y auditoría.
- No puede cancelar/deployar sin scope.

**Brief corto para LLM.**

```text
Implementa MCP-08 (Tool task_cancel y task_retry) en Niwa. Objetivo: Operar tareas sin UI. Toca principalmente `backend/app/mcp/tools/tasks.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP tool tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-09 — Tool task_attach

**Objetivo.** Adjuntar contexto desde otro agente.

**Archivos probables.**

- `backend/app/mcp/tools/attachments.py`

**Instrucciones de implementación.**

- Inputs task_id, filename, content/base64 o text.
- Respetar gating de attachments: solo antes de inicio.
- Limitar tamaño y sanitizar filename.

**Tests/verificación.**

- MCP attachment tests.

**Criterios de aceptación.**

- Adjunto aparece en UI y llega al prompt.
- Archivo peligroso se rechaza.

**Brief corto para LLM.**

```text
Implementa MCP-09 (Tool task_attach) en Niwa. Objetivo: Adjuntar contexto desde otro agente. Toca principalmente `backend/app/mcp/tools/attachments.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP attachment tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-10 — Tools pulls_list y pull_merge

**Objetivo.** Gestionar PRs desde agentes autorizados.

**Archivos probables.**

- `backend/app/mcp/tools/pulls.py`

**Instrucciones de implementación.**

- pulls_list requiere read; pull_merge requiere merge.
- pull_merge input project_slug, number, method.
- Confirmar que el PR pertenece a rama niwa/task-* o política aprobada.

**Tests/verificación.**

- MCP PR tests.

**Criterios de aceptación.**

- Token sin merge no puede mergear.
- Merge respeta checks/not mergeable según servicio existente.

**Brief corto para LLM.**

```text
Implementa MCP-10 (Tools pulls_list y pull_merge) en Niwa. Objetivo: Gestionar PRs desde agentes autorizados. Toca principalmente `backend/app/mcp/tools/pulls.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP PR tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-11 — Tool deploy_trigger

**Objetivo.** Lanzar deploy desde MCP.

**Archivos probables.**

- `backend/app/mcp/tools/deployments.py`

**Instrucciones de implementación.**

- Input project_slug, ref/commit optional, mode manual.
- Requiere deploy scope y project public/deploy policy compatible.
- Output deployment id/status/url.

**Tests/verificación.**

- MCP deploy tests.

**Criterios de aceptación.**

- Deploy no arranca sin permiso.
- Deployment queda visible en UI.

**Brief corto para LLM.**

```text
Implementa MCP-11 (Tool deploy_trigger) en Niwa. Objetivo: Lanzar deploy desde MCP. Toca principalmente `backend/app/mcp/tools/deployments.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP deploy tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-12 — Resources y prompts MCP

**Objetivo.** Ayudar a otros agentes a usar Niwa correctamente.

**Archivos probables.**

- `backend/app/mcp/resources.py`
- `backend/app/mcp/prompts.py`

**Instrucciones de implementación.**

- Resources: niwa://projects, niwa://tasks/{id}, niwa://docs/usage.
- Prompts: create_task_from_goal, respond_to_waiting_input, review_project_status.
- Evitar prompts que pidan al agente tocar filesystem directo.

**Tests/verificación.**

- MCP resource/prompt tests.

**Criterios de aceptación.**

- Un cliente MCP ve recursos útiles.
- Prompts generan inputs compatibles con tools.

**Brief corto para LLM.**

```text
Implementa MCP-12 (Resources y prompts MCP) en Niwa. Objetivo: Ayudar a otros agentes a usar Niwa correctamente. Toca principalmente `backend/app/mcp/resources.py`, `backend/app/mcp/prompts.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: MCP resource/prompt tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-13 — Guía OpenClaw

**Objetivo.** Documentar configuración y flujos recomendados.

**Archivos probables.**

- `docs/integrations/OPENCLAW.md`

**Instrucciones de implementación.**

- Crear docs/integrations/OPENCLAW.md.
- Incluir ejemplo de config MCP, scopes mínimos y workflow: create task→poll status→respond→read PR.
- Incluir límites de seguridad y no-goals.

**Tests/verificación.**

- Docs review.

**Criterios de aceptación.**

- OpenClaw u otro cliente puede integrarse sin adivinar.
- La guía usa tools existentes y scopes mínimos.

**Brief corto para LLM.**

```text
Implementa MCP-13 (Guía OpenClaw) en Niwa. Objetivo: Documentar configuración y flujos recomendados. Toca principalmente `docs/integrations/OPENCLAW.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Docs review.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### MCP-14 — Smoke MCP

**Objetivo.** Validar tools principales en automático.

**Archivos probables.**

- `scripts/smoke_mcp.py`
- `Makefile`

**Instrucciones de implementación.**

- Añadir make smoke-mcp o extender make smoke.
- Usar token temporal y fixture project.
- Cubrir project_list, task_create, task_status, task_respond y scope denial.

**Tests/verificación.**

- make smoke-mcp.

**Criterios de aceptación.**

- Smoke MCP no requiere OpenClaw real.
- Falla si schema/tool cambia de forma incompatible.

**Brief corto para LLM.**

```text
Implementa MCP-14 (Smoke MCP) en Niwa. Objetivo: Validar tools principales en automático. Toca principalmente `scripts/smoke_mcp.py`, `Makefile`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke-mcp.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

## Criterio de cierre de fase

La fase se considera cerrada cuando todos los PR blocks están mergeados, `make test` pasa, el smoke aplicable pasa, la documentación afectada queda actualizada y `docs/STATE.md` refleja el nuevo estado operativo.

## Fuentes usadas para el estado actual del repo

Consultadas el 2026-04-30. Estos documentos no sustituyen a una lectura fresca de `main` antes de implementar.

- `README.md` — Instalación, flujo inicial, backend/frontend, requisitos, modo safe/dangerous.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/README.md
- `docs/STATE.md` — Estado operativo: ciclo v1.1 cerrado y siguiente paso smoke-v1.1.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/docs/STATE.md
- `docs/SPEC.md` — Contrato MVP: triage, execute, verify, finalize; no auth/MCP/subdominios en MVP.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/docs/SPEC.md
- `docs/HANDBOOK.md` — Layout backend/frontend, modelos, tests y módulos principales.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/docs/HANDBOOK.md
- `Makefile` — Targets actuales: install, dev, test, clean.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/Makefile
- `backend/app/finalize.py` — Cierre: commit, push, PR y auto-merge dangerous.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/finalize.py
- `backend/app/schemas/project.py` — Contrato project create/patch/read.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/schemas/project.py
- `backend/app/schemas/task.py` — Contrato task create/read/respond y estados actuales.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/schemas/task.py
- `backend/app/api/tasks.py` — Endpoints de tareas, runs, respond y attachments.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/api/tasks.py
- `backend/app/api/deploy.py` — Deploy estático actual bajo /api/deploy/{slug}/.  
  https://raw.githubusercontent.com/Takeo7/niwa/main/backend/app/api/deploy.py