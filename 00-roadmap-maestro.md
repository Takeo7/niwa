# Niwa — Roadmap de implementación por fases

Fecha de preparación: 2026-04-30

Este documento maestro resume la ruta para llevar Niwa desde el estado actual de `main` hasta la visión objetivo: un sistema local de gestión de proyectos donde un LLM pueda triar, desglosar, planificar, ejecutar, revisar y desplegar tareas, con UI, deploy local/online por subdominios y una capa MCP para OpenClaw u otros clientes.

## Lectura del estado actual

Niwa ya tiene una base funcional para proyectos/tareas, executor local, Claude Code CLI, verificación, finalize con commit/push/PR y modo dangerous para auto-merge. El ciclo v1.1 aparece cerrado en `docs/STATE.md`, y el siguiente paso explícito es un smoke completo de v1.1. En paralelo, el SPEC histórico deja claro que auth, acceso por red, MCP y wildcard subdomains quedaron fuera del MVP; por eso esas piezas se tratan como fases posteriores.

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

## Mapa de fases

| Fase | Nombre | Resultado esperado | Dependencia principal |
|---:|---|---|---|
| 0 | Smoke automatizado y confianza en v1.1 | Convertir el smoke manual de v1.1 en un comando reproducible que valide el flujo E2E sin credenciales reales. | Ninguna |
| 1 | Operabilidad, documentación y deuda inmediata | Hacer que el repo sea confiable para trabajar: estado documental coherente, diagnóstico local, logs útiles y errores accionables. | Fase 0 |
| 2 | Pipeline formal: planificación, aprobación y review LLM | Pasar de triage→execute→verify→finalize a triage→plan→approve?→execute→verify→review→fix-loop→finalize. | Fase 1 |
| 3 | UI de gestión de proyectos y tareas | Convertir Niwa de executor con UI básica a gestor operativo de proyectos, tareas, subtareas, colas, PRs y decisiones humanas. | Fase 2 |
| 4 | Deploy local serio y versionado | Sustituir el deploy estático mínimo por un sistema local de deploys versionados, procesos gestionados, healthchecks, logs y rollback. | Fase 3 |
| 5 | Dominio, subdominios y acceso online | Publicar la UI de Niwa y los proyectos con reverse proxy, TLS y controles de exposición, manteniendo operación local/VPS/casa. | Fase 4 |
| 6 | Seguridad, aislamiento y recuperación | Hacer seguro operar Niwa con un LLM que ejecuta código y con UI potencialmente accesible online. | Fase 5 |
| 7 | MCP para OpenClaw y otros clientes | Exponer Niwa como servidor MCP seguro para que otros agentes creen tareas, consulten estado, respondan preguntas, gestionen PRs y disparen deploys. | Fase 6 |
| 8 | QA, robustez, packaging y mantenimiento | Convertir Niwa en una herramienta mantenible: tests de integración, migraciones, CI, observabilidad, limpieza, releases y runbooks. | Fase 7 |

## Orden recomendado

No empieces por MCP ni por subdominios. Primero hay que demostrar que el motor local funciona, después añadir planificación/review, luego mejorar UI, luego deploy local, después exposición online, y solo entonces abrir una superficie MCP segura.

## Paquetes de trabajo sugeridos

### Fase 0: Smoke automatizado y confianza en v1.1

Convertir el smoke manual de v1.1 en un comando reproducible que valide el flujo E2E sin credenciales reales.

- **PR-SMOKE-01.** Smoke fake básico: sandbox aislado, bootstrap, backend readiness, fixture repo, project create, execute/verify/finalize.
- **PR-SMOKE-02.** Split, waiting_input/resume, attachments, deploy estático, fake gh para PR/merge.
- **PR-SMOKE-03.** CI smoke en GitHub Actions y reportes .smoke/report.md + .json.
- **PR-SMOKE-04.** smoke-live opcional con Claude Code y GitHub CLI reales.

### Fase 1: Operabilidad, documentación y deuda inmediata

Hacer que el repo sea confiable para trabajar: estado documental coherente, diagnóstico local, logs útiles y errores accionables.

- **PR-OPS-01.** Alinear docs y estado del repo.
- **PR-OPS-02.** niwa doctor + checks de entorno.
- **PR-OPS-03.** Logs/eventos visibles y normalización de errores finalize/executor.
- **PR-OPS-04.** Mejoras de system/readiness y ayuda operativa.

### Fase 2: Pipeline formal: planificación, aprobación y review LLM

Pasar de triage→execute→verify→finalize a triage→plan→approve?→execute→verify→review→fix-loop→finalize.

- **PR-PIPE-01.** Modelo TaskPlan + API read.
- **PR-PIPE-02.** Planner adapter + etapa planning en executor.
- **PR-PIPE-03.** Plan UI + aprobación opcional.
- **PR-PIPE-04.** TaskReview model + diff collection.
- **PR-PIPE-05.** LLM review + fix loop con límites.
- **PR-PIPE-06.** Políticas de autonomía por proyecto y smoke actualizado.

### Fase 3: UI de gestión de proyectos y tareas

Convertir Niwa de executor con UI básica a gestor operativo de proyectos, tareas, subtareas, colas, PRs y decisiones humanas.

- **PR-UI-01.** Dashboard y navegación por estado.
- **PR-UI-02.** Backlog, filtros, jerarquía de subtareas.
- **PR-UI-03.** Cancel/retry/edit/priority.
- **PR-UI-04.** Settings de proyecto y políticas.
- **PR-UI-05.** Timeline unificado y test coverage.

### Fase 4: Deploy local serio y versionado

Sustituir el deploy estático mínimo por un sistema local de deploys versionados, procesos gestionados, healthchecks, logs y rollback.

- **PR-DEPLOY-01.** Modelo deployments + API.
- **PR-DEPLOY-02.** Build runner + static deploy versionado.
- **PR-DEPLOY-03.** Process manager + port allocator + healthchecks.
- **PR-DEPLOY-04.** UI Deploys + logs + rollback.
- **PR-DEPLOY-05.** Triggers de auto-deploy y smoke deploy.

### Fase 5: Dominio, subdominios y acceso online

Publicar la UI de Niwa y los proyectos con reverse proxy, TLS y controles de exposición, manteniendo operación local/VPS/casa.

- **PR-NET-01.** Auth local-first + tokens.
- **PR-NET-02.** Domain config + Caddy generator.
- **PR-NET-03.** Wildcard/subdomain routing para projects.
- **PR-NET-04.** TLS y modos VPS/casa/tunnel.
- **PR-NET-05.** UI de exposición y smoke de red local.

### Fase 6: Seguridad, aislamiento y recuperación

Hacer seguro operar Niwa con un LLM que ejecuta código y con UI potencialmente accesible online.

- **PR-SEC-01.** Threat model + redaction + audit log.
- **PR-SEC-02.** Policies/scopes por proyecto y checks de workspace.
- **PR-SEC-03.** Kill switch, cancellation robusta y process limits.
- **PR-SEC-04.** Backups/restore y disaster drill.
- **PR-SEC-05.** Security smoke/regression tests.

### Fase 7: MCP para OpenClaw y otros clientes

Exponer Niwa como servidor MCP seguro para que otros agentes creen tareas, consulten estado, respondan preguntas, gestionen PRs y disparen deploys.

- **PR-MCP-01.** Spec MCP + auth/scopes.
- **PR-MCP-02.** Servidor MCP con project/task tools read/create/status/respond.
- **PR-MCP-03.** Herramientas PR/deploy con scopes.
- **PR-MCP-04.** Resources/prompts + OpenClaw guide.
- **PR-MCP-05.** Tests y smoke MCP.

### Fase 8: QA, robustez, packaging y mantenimiento

Convertir Niwa en una herramienta mantenible: tests de integración, migraciones, CI, observabilidad, limpieza, releases y runbooks.

- **PR-QA-01.** Fixture repos + integration tests.
- **PR-QA-02.** Migration tests + CI matrix.
- **PR-QA-03.** Frontend E2E + smoke UI.
- **PR-QA-04.** Observabilidad, locks, concurrency.
- **PR-QA-05.** Cleanup, packaging, releases y runbooks.

## Definición global de done

Una fase no está cerrada solo porque el código compile. Debe cumplir: tests verdes, smoke correspondiente verde, docs actualizadas, errores accionables, compatibilidad con instalaciones existentes, y estado actualizado en `docs/STATE.md`.

## Cómo usar los documentos por fase

Para pasárselo a un LLM, usa el documento de fase completo y copia una sola tarea o un solo PR block. Añade al prompt el estado de la rama, cualquier fallo de tests y la restricción de no implementar fases futuras. Si el LLM detecta que la tarea necesita ampliar scope, debe detenerse y proponer una subdivisión, no improvisar una reescritura.

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