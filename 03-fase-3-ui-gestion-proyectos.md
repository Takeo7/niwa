# Fase 3 — UI de gestión de proyectos y tareas

Fecha de preparación: 2026-04-30

**Resumen.** Convertir Niwa de executor con UI básica a gestor operativo de proyectos, tareas, subtareas, colas, PRs y decisiones humanas.

## Contexto

- La UI actual ya cubre proyectos, tareas, detalle, runs, adjuntos y PRs, pero no es aún un sistema de gestión amplio.
- Esta fase debe priorizar control operativo: backlog, filtros, cancel/retry, jerarquía y settings.
- Las vistas deben reflejar el pipeline formal de Fase 2 sin introducir lógica duplicada en frontend.

## No-objetivos

- No rediseñar branding.
- No hacer multiusuario.
- No implementar deploy avanzado; solo mostrar el estado si ya existe.

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

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 3 — UI de gestión de proyectos y tareas.

Contexto: Convertir Niwa de executor con UI básica a gestor operativo de proyectos, tareas, subtareas, colas, PRs y decisiones humanas.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-UI-01.** Dashboard y navegación por estado.
- **PR-UI-02.** Backlog, filtros, jerarquía de subtareas.
- **PR-UI-03.** Cancel/retry/edit/priority.
- **PR-UI-04.** Settings de proyecto y políticas.
- **PR-UI-05.** Timeline unificado y test coverage.

## Tareas

### UI-01 — Dashboard global

**Objetivo.** Dar una vista de mando de Niwa.

**Archivos probables.**

- `backend/app/api/summary.py`
- `frontend/src/routes/ProjectsRoute.tsx`

**Instrucciones de implementación.**

- Crear o ampliar ruta / con cards: proyectos, tareas activas, waiting_input, waiting_approval, failed, PRs abiertos, deploys si existen.
- Backend: endpoint summary o composición desde endpoints existentes; preferir endpoint si evita N+1.
- Frontend: estados loading/error/empty.

**Tests/verificación.**

- Backend summary tests.
- Frontend tests dashboard states.

**Criterios de aceptación.**

- La portada muestra qué requiere atención sin entrar en cada proyecto.
- No se bloquea si gh no está disponible.

**Brief corto para LLM.**

```text
Implementa UI-01 (Dashboard global) en Niwa. Objetivo: Dar una vista de mando de Niwa. Toca principalmente `backend/app/api/summary.py`, `frontend/src/routes/ProjectsRoute.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend summary tests.; Frontend tests dashboard states.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-02 — Tabs de proyecto orientados a flujo

**Objetivo.** Ordenar el detalle del proyecto.

**Archivos probables.**

- `frontend/src/features/projects/ProjectDetail.tsx`

**Instrucciones de implementación.**

- Tabs sugeridas: Backlog, Running, Done, PRs, Deploys, Settings.
- Mantener compatibilidad con PullsTab actual.
- No montar tabs costosas si no están activas.

**Tests/verificación.**

- Frontend tests de tabs y empty states.

**Criterios de aceptación.**

- El usuario entiende dónde están tareas, PRs y settings.
- PR tab conserva comportamiento existente.

**Brief corto para LLM.**

```text
Implementa UI-02 (Tabs de proyecto orientados a flujo) en Niwa. Objetivo: Ordenar el detalle del proyecto. Toca principalmente `frontend/src/features/projects/ProjectDetail.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Frontend tests de tabs y empty states.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-03 — Backlog con filtros y búsqueda

**Objetivo.** Gestionar muchas tareas sin perder contexto.

**Archivos probables.**

- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Añadir query params o estado local para status, texto, parent, branch, pr_url, fecha.
- Backend: endpoint list con filtros si la lista crece; si no, filtrado cliente como primer PR.
- Mostrar chips de estado y contadores.

**Tests/verificación.**

- Frontend tests filtros.

**Criterios de aceptación.**

- Se puede filtrar por waiting_input, failed y texto.
- El filtro persiste al navegar al detalle y volver si es viable.

**Brief corto para LLM.**

```text
Implementa UI-03 (Backlog con filtros y búsqueda) en Niwa. Objetivo: Gestionar muchas tareas sin perder contexto. Toca principalmente `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Frontend tests filtros.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-04 — Vista jerárquica de subtareas

**Objetivo.** Mostrar splits como árbol, no como lista plana confusa.

**Archivos probables.**

- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Agrupar por parent_task_id.
- Mostrar progreso del padre: x/y done, failed, cancelled.
- En detalle de padre, listar hijos con links.

**Tests/verificación.**

- Frontend tests con fixture de subtareas.

**Criterios de aceptación.**

- Una tarea split enseña su árbol completo.
- El padre no parece terminado sin explicar hijos.

**Brief corto para LLM.**

```text
Implementa UI-04 (Vista jerárquica de subtareas) en Niwa. Objetivo: Mostrar splits como árbol, no como lista plana confusa. Toca principalmente `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Frontend tests con fixture de subtareas.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-05 — Editar tareas antes de ejecución

**Objetivo.** Permitir corregir prompts malos antes de que el executor los tome.

**Archivos probables.**

- `backend/app/api/tasks.py`
- `backend/app/services/tasks.py`
- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Añadir PATCH /api/tasks/{id} para title/description/priority si status in inbox/queued y no run started.
- UI modal edit en backlog.
- Bloquear edición si running/executing/etc. y explicar por qué.

**Tests/verificación.**

- Backend tests 200/409.
- Frontend edit modal tests.

**Criterios de aceptación.**

- Tarea queued editable.
- Tarea ya empezada devuelve 409.
- Eventos registran cambios.

**Brief corto para LLM.**

```text
Implementa UI-05 (Editar tareas antes de ejecución) en Niwa. Objetivo: Permitir corregir prompts malos antes de que el executor los tome. Toca principalmente `backend/app/api/tasks.py`, `backend/app/services/tasks.py`, `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend tests 200/409.; Frontend edit modal tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-06 — Prioridad y orden de cola

**Objetivo.** Controlar qué ejecuta primero Niwa.

**Archivos probables.**

- `backend/app/models/task.py`
- `backend/app/executor/core.py`
- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Añadir campo priority con default 0 o enum low/normal/high.
- Executor reclama queued por priority desc y created_at asc.
- UI permite cambiar prioridad en tareas no empezadas.

**Tests/verificación.**

- Executor ordering test.
- Migration test.

**Criterios de aceptación.**

- Una tarea high se procesa antes que normal si ambas están queued.
- Migración asigna prioridad default a tareas existentes.

**Brief corto para LLM.**

```text
Implementa UI-06 (Prioridad y orden de cola) en Niwa. Objetivo: Controlar qué ejecuta primero Niwa. Toca principalmente `backend/app/models/task.py`, `backend/app/executor/core.py`, `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Executor ordering test.; Migration test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-07 — Cancelar tarea/run

**Objetivo.** Dar control para detener trabajo en curso.

**Archivos probables.**

- `backend/app/services/tasks.py`
- `backend/app/executor/core.py`
- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Añadir POST /api/tasks/{id}/cancel.
- Si queued/waiting_approval/waiting_input: marcar cancelled.
- Si running/executing: pedir al executor que cancele subprocess; si no es viable en primer PR, marcar cancellation_requested y hacer que executor lo lea.
- Registrar evento con actor user.

**Tests/verificación.**

- Backend cancel tests.
- Executor cancellation test con fake long process.

**Criterios de aceptación.**

- Queued cancela inmediatamente.
- Running no queda en estado incoherente.
- UI muestra acción y resultado.

**Brief corto para LLM.**

```text
Implementa UI-07 (Cancelar tarea/run) en Niwa. Objetivo: Dar control para detener trabajo en curso. Toca principalmente `backend/app/services/tasks.py`, `backend/app/executor/core.py`, `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend cancel tests.; Executor cancellation test con fake long process.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-08 — Reintentar tarea fallida

**Objetivo.** Reusar contexto y evitar recrear tareas a mano.

**Archivos probables.**

- `backend/app/api/tasks.py`
- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Añadir POST /api/tasks/{id}/retry.
- Opción A: reencolar la misma tarea con nuevo run. Opción B: crear nueva tarea linked a original. Elegir y documentar.
- Permitir editar instrucciones adicionales antes del retry.

**Tests/verificación.**

- Backend retry tests.
- Frontend retry modal tests.

**Criterios de aceptación.**

- Una tarea failed puede generar nuevo run.
- Historial anterior se conserva.
- Retry no borra pr_url/branch sin criterio claro.

**Brief corto para LLM.**

```text
Implementa UI-08 (Reintentar tarea fallida) en Niwa. Objetivo: Reusar contexto y evitar recrear tareas a mano. Toca principalmente `backend/app/api/tasks.py`, `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend retry tests.; Frontend retry modal tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-09 — Timeline unificado

**Objetivo.** Mostrar la historia completa de una tarea.

**Archivos probables.**

- `backend/app/api/tasks.py`
- `frontend/src/features/tasks/Timeline.tsx`

**Instrucciones de implementación.**

- Unificar task_events, run_events, verification, finalize, plan y review en una vista cronológica.
- Agrupar eventos ruidosos y permitir expandir JSON/raw.
- Mostrar timestamps y estado resultante.

**Tests/verificación.**

- Frontend tests timeline fixtures.
- Backend endpoint si se crea.

**Criterios de aceptación.**

- Timeline permite diagnosticar cualquier task sin logs externos.
- Eventos raw largos se truncan/expandibles.

**Brief corto para LLM.**

```text
Implementa UI-09 (Timeline unificado) en Niwa. Objetivo: Mostrar la historia completa de una tarea. Toca principalmente `backend/app/api/tasks.py`, `frontend/src/features/tasks/Timeline.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Frontend tests timeline fixtures.; Backend endpoint si se crea.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-10 — Settings de proyecto

**Objetivo.** Editar configuración del proyecto desde UI.

**Archivos probables.**

- `frontend/src/features/projects/ProjectSettings.tsx`
- `backend/app/schemas/project.py`

**Instrucciones de implementación.**

- Formulario para name, kind, local_path, git_remote, autonomy/policy, deploy settings existentes.
- Validar slug no editable.
- Mostrar warnings si local_path no existe o repo sucio usando endpoint de diagnostics.

**Tests/verificación.**

- Backend PATCH tests ya existentes ampliados.
- Frontend settings tests.

**Criterios de aceptación.**

- Project settings edita campos permitidos.
- No permite romper slug.
- Errores 422/409 se muestran claramente.

**Brief corto para LLM.**

```text
Implementa UI-10 (Settings de proyecto) en Niwa. Objetivo: Editar configuración del proyecto desde UI. Toca principalmente `frontend/src/features/projects/ProjectSettings.tsx`, `backend/app/schemas/project.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend PATCH tests ya existentes ampliados.; Frontend settings tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-11 — Accesibilidad y responsive mínimo

**Objetivo.** Evitar UI difícil de usar en portátil/VPS browser.

**Archivos probables.**

- `frontend/src`

**Instrucciones de implementación.**

- Revisar labels, focus states, contraste, keyboard navigation para acciones críticas.
- Tablas/listas deben colapsar bien en pantallas estrechas.
- No hacer rediseño visual completo.

**Tests/verificación.**

- RTL tests de labels básicos.
- Manual smoke UI.

**Criterios de aceptación.**

- Flujos crear tarea, responder, aprobar plan, merge y cancel son navegables por teclado.
- No hay overflow horizontal crítico en vistas principales.

**Brief corto para LLM.**

```text
Implementa UI-11 (Accesibilidad y responsive mínimo) en Niwa. Objetivo: Evitar UI difícil de usar en portátil/VPS browser. Toca principalmente `frontend/src`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: RTL tests de labels básicos.; Manual smoke UI.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### UI-12 — Cobertura frontend para flujos críticos

**Objetivo.** Evitar regresiones de UI.

**Archivos probables.**

- `frontend/tests`
- `frontend/src/features`

**Instrucciones de implementación.**

- Añadir fixtures de tareas por estado.
- Tests para dashboard, backlog filters, task detail, plan/review panels, cancel/retry, settings.
- No depender de backend real; mock API.

**Tests/verificación.**

- npm test -- --run.

**Criterios de aceptación.**

- Frontend test suite cubre rutas críticas.
- make test sigue estable.

**Brief corto para LLM.**

```text
Implementa UI-12 (Cobertura frontend para flujos críticos) en Niwa. Objetivo: Evitar regresiones de UI. Toca principalmente `frontend/tests`, `frontend/src/features`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: npm test -- --run.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
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