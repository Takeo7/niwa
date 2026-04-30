# Fase 2 — Pipeline formal: planificación, aprobación y review LLM

Fecha de preparación: 2026-04-30

**Resumen.** Pasar de triage→execute→verify→finalize a triage→plan→approve?→execute→verify→review→fix-loop→finalize.

## Contexto

- El MVP ya contempla triage, execute, verify y finalize; la planificación y review semántica siguen implícitas.
- La visión deseada requiere que el LLM desgrane, planifique, ejecute, revise y cierre con política configurable.
- Esta fase debe cambiar el pipeline sin romper tareas existentes ni el smoke de Fase 0.

## No-objetivos

- No añadir deploy nuevo.
- No implementar MCP.
- No cambiar la UI completa de gestión; solo vistas de plan/review necesarias.

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

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 2 — Pipeline formal: planificación, aprobación y review LLM.

Contexto: Pasar de triage→execute→verify→finalize a triage→plan→approve?→execute→verify→review→fix-loop→finalize.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-PIPE-01.** Modelo TaskPlan + API read.
- **PR-PIPE-02.** Planner adapter + etapa planning en executor.
- **PR-PIPE-03.** Plan UI + aprobación opcional.
- **PR-PIPE-04.** TaskReview model + diff collection.
- **PR-PIPE-05.** LLM review + fix loop con límites.
- **PR-PIPE-06.** Políticas de autonomía por proyecto y smoke actualizado.

## Tareas

### PIPE-01 — Crear modelo TaskPlan

**Objetivo.** Persistir planes antes de tocar código.

**Archivos probables.**

- `backend/app/models`
- `backend/app/schemas`
- `backend/migrations/versions`

**Instrucciones de implementación.**

- Añadir tabla task_plans con task_id, run_id nullable, status, summary, steps_json, risks_json, acceptance_criteria_json, raw_response_json, created_at, updated_at.
- Relación 1:N o latest plan por task; preferible 1:N para historial y retries.
- Añadir migration Alembic con render_as_batch si el patrón actual lo requiere.
- Crear schemas Pydantic TaskPlanRead.

**Tests/verificación.**

- pytest de modelo/migration/service.
- make test.

**Criterios de aceptación.**

- Se puede guardar y leer un plan por task.
- Migración limpia desde DB v1.1.
- No cambia ejecución existente hasta PIPE-02.

**Brief corto para LLM.**

```text
Implementa PIPE-01 (Crear modelo TaskPlan) en Niwa. Objetivo: Persistir planes antes de tocar código. Toca principalmente `backend/app/models`, `backend/app/schemas`, `backend/migrations/versions`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest de modelo/migration/service.; make test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-02 — API de planes

**Objetivo.** Permitir que UI/MCP futuro lean planes.

**Archivos probables.**

- `backend/app/api/tasks.py`
- `backend/app/services/plans.py`

**Instrucciones de implementación.**

- Añadir GET /api/tasks/{id}/plans y GET /api/tasks/{id}/plan/latest.
- No añadir create público salvo necesidad; el planner debe escribir por service interno.
- Exponer campos estructurados y timestamps.

**Tests/verificación.**

- TestClient endpoints.

**Criterios de aceptación.**

- Endpoints devuelven 404 si task no existe, [] si no hay planes.
- Contrato Pydantic estable.

**Brief corto para LLM.**

```text
Implementa PIPE-02 (API de planes) en Niwa. Objetivo: Permitir que UI/MCP futuro lean planes. Toca principalmente `backend/app/api/tasks.py`, `backend/app/services/plans.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: TestClient endpoints.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-03 — Planner adapter estructurado

**Objetivo.** Generar plan JSON validado con Claude Code o fake adapter.

**Archivos probables.**

- `backend/app/planning`
- `backend/tests`

**Instrucciones de implementación.**

- Crear backend/app/planning/ o backend/app/adapters/planner.py.
- Prompt: devolver JSON con summary, steps, files_likely_touched, risks, acceptance_criteria, needs_user_approval boolean opcional.
- Validar JSON estrictamente; si falla, guardar raw y marcar planning_failed.
- Añadir fake planner en tests/smoke.

**Tests/verificación.**

- pytest planner JSON válido/inválido.
- Fake Claude planner test.

**Criterios de aceptación.**

- Plan inválido no ejecuta código silenciosamente.
- Plan válido queda persistido.
- El prompt no pide implementar todavía.

**Brief corto para LLM.**

```text
Implementa PIPE-03 (Planner adapter estructurado) en Niwa. Objetivo: Generar plan JSON validado con Claude Code o fake adapter. Toca principalmente `backend/app/planning`, `backend/tests`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest planner JSON válido/inválido.; Fake Claude planner test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-04 — Insertar estado planning en executor

**Objetivo.** Separar decisión, planificación y ejecución.

**Archivos probables.**

- `backend/app/models`
- `backend/app/executor/core.py`
- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Actualizar estados permitidos: queued, triaging, planning, waiting_approval, executing, verifying, reviewing, waiting_input, done, failed, cancelled.
- Migrar estado running a transiciones más específicas sin romper lecturas existentes.
- En process_pending: claim queued → triaging → planning → executing.
- Persistir eventos status_changed con payload de etapa.

**Tests/verificación.**

- pytest executor transitions.
- make smoke.

**Criterios de aceptación.**

- Una tarea simple produce eventos triaging/planning/executing/verifying.
- Smoke execute sigue pasando.
- UI no rompe si recibe nuevos estados.

**Brief corto para LLM.**

```text
Implementa PIPE-04 (Insertar estado planning en executor) en Niwa. Objetivo: Separar decisión, planificación y ejecución. Toca principalmente `backend/app/models`, `backend/app/executor/core.py`, `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest executor transitions.; make smoke.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-05 — Aprobación manual de plan

**Objetivo.** Permitir gate humano antes de ejecutar.

**Archivos probables.**

- `backend/app/models`
- `backend/app/api/tasks.py`
- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Añadir project setting plan_approval_mode: auto/manual.
- Si manual, tras plan se deja task waiting_approval.
- Añadir POST /api/tasks/{id}/approve-plan y reject-plan o respond con decisión explícita.
- Rechazo permite editar tarea o marcar cancelled según brief.

**Tests/verificación.**

- Backend tests por modo.
- Frontend test botón aprobar.

**Criterios de aceptación.**

- Proyecto en auto no se bloquea.
- Proyecto en manual queda waiting_approval hasta aprobación.
- Aprobación reencola/continúa ejecución.

**Brief corto para LLM.**

```text
Implementa PIPE-05 (Aprobación manual de plan) en Niwa. Objetivo: Permitir gate humano antes de ejecutar. Toca principalmente `backend/app/models`, `backend/app/api/tasks.py`, `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend tests por modo.; Frontend test botón aprobar.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-06 — UI de plan

**Objetivo.** Hacer visible el plan y sus criterios.

**Archivos probables.**

- `frontend/src/features/tasks`
- `frontend/src/api.ts`

**Instrucciones de implementación.**

- En TaskDetail mostrar summary, steps, risks, acceptance criteria y estado de aprobación.
- Añadir botones approve/reject solo cuando status waiting_approval.
- Mostrar raw/errores solo colapsado para debug.

**Tests/verificación.**

- Vitest/RTL TaskDetail plan states.

**Criterios de aceptación.**

- Plan legible en detalle de tarea.
- UI no falla si no hay plan.
- Aprobación manual funciona desde UI.

**Brief corto para LLM.**

```text
Implementa PIPE-06 (UI de plan) en Niwa. Objetivo: Hacer visible el plan y sus criterios. Toca principalmente `frontend/src/features/tasks`, `frontend/src/api.ts`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Vitest/RTL TaskDetail plan states.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-07 — Crear modelo TaskReview

**Objetivo.** Persistir reviews semánticas de diffs.

**Archivos probables.**

- `backend/app/models`
- `backend/app/schemas`
- `backend/migrations/versions`

**Instrucciones de implementación.**

- Añadir tabla task_reviews con task_id, run_id, diff_summary, findings_json, decision, raw_response_json, created_at.
- decision enum: approve, request_changes, needs_input, fail.
- Schemas y services para latest/list.

**Tests/verificación.**

- pytest model/service.

**Criterios de aceptación.**

- Review puede guardarse aunque no haya PR.
- Findings contienen severity, file, line optional, message, recommendation.

**Brief corto para LLM.**

```text
Implementa PIPE-07 (Crear modelo TaskReview) en Niwa. Objetivo: Persistir reviews semánticas de diffs. Toca principalmente `backend/app/models`, `backend/app/schemas`, `backend/migrations/versions`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest model/service.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-08 — Recolectar diff para review

**Objetivo.** Preparar entrada confiable al reviewer.

**Archivos probables.**

- `backend/app/reviewing`
- `backend/app/executor/core.py`

**Instrucciones de implementación.**

- Antes de finalize, obtener git diff --stat y git diff -- .
- Aplicar límite de tamaño; si el diff excede, resumir por archivos y marcar truncated.
- Incluir plan y acceptance criteria en el prompt de review.

**Tests/verificación.**

- pytest diff collector con repo fixture.

**Criterios de aceptación.**

- Diff disponible para reviewer.
- Diff enorme no rompe el proceso; queda truncated=true.

**Brief corto para LLM.**

```text
Implementa PIPE-08 (Recolectar diff para review) en Niwa. Objetivo: Preparar entrada confiable al reviewer. Toca principalmente `backend/app/reviewing`, `backend/app/executor/core.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest diff collector con repo fixture.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-09 — LLM review adapter

**Objetivo.** Añadir revisión autónoma antes del finalize.

**Archivos probables.**

- `backend/app/reviewing`
- `backend/app/executor/core.py`

**Instrucciones de implementación.**

- Prompt debe pedir hallazgos accionables y decisión: approve/request_changes/needs_input/fail.
- Validar JSON y persistir TaskReview.
- Si needs_input, mover task a waiting_input con pregunta concreta.
- Si fail, marcar failed con evento claro.

**Tests/verificación.**

- pytest adapter fake.
- executor tests review transitions.

**Criterios de aceptación.**

- Una review approve permite finalize.
- request_changes no abre PR todavía.
- needs_input funciona igual que aclaración de ejecución.

**Brief corto para LLM.**

```text
Implementa PIPE-09 (LLM review adapter) en Niwa. Objetivo: Añadir revisión autónoma antes del finalize. Toca principalmente `backend/app/reviewing`, `backend/app/executor/core.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest adapter fake.; executor tests review transitions.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-10 — Fix loop tras request_changes

**Objetivo.** Permitir que Claude corrija antes de PR.

**Archivos probables.**

- `backend/app/executor/core.py`
- `backend/app/reviewing`

**Instrucciones de implementación.**

- Añadir max_review_iterations por proyecto o config global, default 1 o 2.
- Cuando review=request_changes, construir prompt de corrección con findings y ejecutar otra iteración.
- Cada iteración crea run/review nuevos, no sobrescribe historial.
- Al exceder límite, dejar failed o waiting_human_review según política.

**Tests/verificación.**

- pytest loop limit.
- make smoke ampliado.

**Criterios de aceptación.**

- Hay límite duro para evitar loops infinitos.
- UI muestra iteraciones.
- Smoke fake cubre request_changes→fix→approve.

**Brief corto para LLM.**

```text
Implementa PIPE-10 (Fix loop tras request_changes) en Niwa. Objetivo: Permitir que Claude corrija antes de PR. Toca principalmente `backend/app/executor/core.py`, `backend/app/reviewing`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest loop limit.; make smoke ampliado.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-11 — Políticas de autonomía por proyecto

**Objetivo.** Hacer configurable qué etapas son automáticas.

**Archivos probables.**

- `backend/app/models/project.py`
- `backend/app/schemas/project.py`

**Instrucciones de implementación.**

- Añadir campos: auto_plan, require_plan_approval, auto_execute, auto_review, auto_pr, auto_merge, auto_deploy o un JSON policy versionado.
- Preferir un modelo claro y migrable; si se usa JSON, validar con Pydantic.
- Mantener safe/dangerous como compatibilidad o mapearlo a policy.

**Tests/verificación.**

- migration tests.
- Project API patch tests.

**Criterios de aceptación.**

- Los proyectos existentes conservan comportamiento safe/dangerous.
- La UI/API puede leer política efectiva.
- Los tests cubren compatibilidad.

**Brief corto para LLM.**

```text
Implementa PIPE-11 (Políticas de autonomía por proyecto) en Niwa. Objetivo: Hacer configurable qué etapas son automáticas. Toca principalmente `backend/app/models/project.py`, `backend/app/schemas/project.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: migration tests.; Project API patch tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### PIPE-12 — Actualizar smoke y documentación del pipeline

**Objetivo.** Cerrar fase con pruebas E2E.

**Archivos probables.**

- `scripts/smoke_v1_1.py`
- `docs/HANDBOOK.md`
- `docs/AGENTS.md`

**Instrucciones de implementación.**

- Extender make smoke con planning approve auto, waiting_approval manual simulado y review approve/request_changes.
- Actualizar HANDBOOK con pipeline nuevo y diagramas textuales.
- Actualizar AGENTS/brief template con plan/review rules.

**Tests/verificación.**

- make smoke
- make test.

**Criterios de aceptación.**

- make smoke cubre nuevas etapas.
- Docs reflejan estados y transiciones reales.

**Brief corto para LLM.**

```text
Implementa PIPE-12 (Actualizar smoke y documentación del pipeline) en Niwa. Objetivo: Cerrar fase con pruebas E2E. Toca principalmente `scripts/smoke_v1_1.py`, `docs/HANDBOOK.md`, `docs/AGENTS.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke; make test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
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