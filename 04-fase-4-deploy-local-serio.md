# Fase 4 — Deploy local serio y versionado

Fecha de preparación: 2026-04-30

**Resumen.** Sustituir el deploy estático mínimo por un sistema local de deploys versionados, procesos gestionados, healthchecks, logs y rollback.

## Contexto

- El deploy actual sirve dist/ desde FastAPI bajo /api/deploy/{slug}/.
- La visión requiere proyectos visibles por subdominios y, para eso, primero hace falta un modelo local de deploys sólido.
- Esta fase aún es local; Caddy, TLS y dominio van en Fase 5.

## No-objetivos

- No configurar dominio público.
- No hacer Kubernetes/Docker obligatorio.
- No publicar proyectos por defecto.

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

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 4 — Deploy local serio y versionado.

Contexto: Sustituir el deploy estático mínimo por un sistema local de deploys versionados, procesos gestionados, healthchecks, logs y rollback.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-DEPLOY-01.** Modelo deployments + API.
- **PR-DEPLOY-02.** Build runner + static deploy versionado.
- **PR-DEPLOY-03.** Process manager + port allocator + healthchecks.
- **PR-DEPLOY-04.** UI Deploys + logs + rollback.
- **PR-DEPLOY-05.** Triggers de auto-deploy y smoke deploy.

## Tareas

### DEPLOY-01 — Modelo deployments

**Objetivo.** Registrar cada deploy como entidad auditable.

**Archivos probables.**

- `backend/app/models`
- `backend/app/api/deployments.py`
- `backend/migrations/versions`

**Instrucciones de implementación.**

- Crear tabla deployments: id, project_id, commit_sha, task_id nullable, type static/process, status, artifact_path, port, url_local, healthcheck_path, started_at, finished_at, created_at.
- Estados sugeridos: queued, building, starting, healthy, unhealthy, failed, stopped, rolled_back.
- Schemas DeploymentRead y endpoints list/detail.

**Tests/verificación.**

- Model/service/API tests.

**Criterios de aceptación.**

- Cada deploy queda persistido y visible por proyecto.
- Migración no afecta deploy estático legacy.

**Brief corto para LLM.**

```text
Implementa DEPLOY-01 (Modelo deployments) en Niwa. Objetivo: Registrar cada deploy como entidad auditable. Toca principalmente `backend/app/models`, `backend/app/api/deployments.py`, `backend/migrations/versions`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Model/service/API tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-02 — Settings de deploy por proyecto

**Objetivo.** Definir cómo construir y servir cada proyecto.

**Archivos probables.**

- `backend/app/models/project.py`
- `backend/app/schemas/project.py`

**Instrucciones de implementación.**

- Añadir campos o tabla project_deploy_settings: deploy_type, build_command, start_command, dist_dir, healthcheck_path, env_json, public_enabled default false.
- Validar comandos vacíos y paths relativos.
- UI settings los mostrará en Fase 3/4.

**Tests/verificación.**

- Project schema/service tests.
- Migration test.

**Criterios de aceptación.**

- Proyecto web-deployable puede declarar dist_dir y build_command.
- Default conserva comportamiento actual para dist/.

**Brief corto para LLM.**

```text
Implementa DEPLOY-02 (Settings de deploy por proyecto) en Niwa. Objetivo: Definir cómo construir y servir cada proyecto. Toca principalmente `backend/app/models/project.py`, `backend/app/schemas/project.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Project schema/service tests.; Migration test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-03 — Build runner

**Objetivo.** Ejecutar build con logs persistidos.

**Archivos probables.**

- `backend/app/deployments/runner.py`

**Instrucciones de implementación.**

- Crear service que ejecuta build_command en local_path con timeout configurable.
- Capturar stdout/stderr en deployment_logs o archivo bajo ~/.niwa/deployments/logs.
- Si no hay build_command, saltar build para static si dist_dir ya existe.

**Tests/verificación.**

- pytest con comandos fake.
- Smoke fixture static sin build.

**Criterios de aceptación.**

- Build success crea deployment status building→built/starting.
- Build failure queda failed con logs.
- Timeout controlado.

**Brief corto para LLM.**

```text
Implementa DEPLOY-03 (Build runner) en Niwa. Objetivo: Ejecutar build con logs persistidos. Toca principalmente `backend/app/deployments/runner.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest con comandos fake.; Smoke fixture static sin build.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-04 — Static deploy versionado

**Objetivo.** No servir directamente desde working tree.

**Archivos probables.**

- `backend/app/api/deploy.py`
- `backend/app/deployments`

**Instrucciones de implementación.**

- Copiar dist_dir a ~/.niwa/deployments/{project_slug}/{sha_or_deploy_id}/.
- Actualizar handler para servir el deployment activo.
- Mantener fallback legacy solo si no hay deployment activo, o eliminarlo con migration/brief claro.

**Tests/verificación.**

- Static deploy tests.
- make smoke actualizado.

**Criterios de aceptación.**

- Un deploy estático queda inmutable aunque cambie el working tree.
- GET /api/deploy/{slug}/ sirve el deployment activo.
- Rollback puede apuntar a deployment anterior.

**Brief corto para LLM.**

```text
Implementa DEPLOY-04 (Static deploy versionado) en Niwa. Objetivo: No servir directamente desde working tree. Toca principalmente `backend/app/api/deploy.py`, `backend/app/deployments`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Static deploy tests.; make smoke actualizado.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-05 — Process manager local

**Objetivo.** Soportar proyectos que necesitan proceso propio.

**Archivos probables.**

- `backend/app/deployments/process_manager.py`

**Instrucciones de implementación.**

- Implementar start/stop/restart para start_command.
- Gestionar PID, cwd, env, stdout/stderr y status.
- No usar systemd por proyecto en primer PR; proceso hijo controlado por Niwa basta para MVP local.

**Tests/verificación.**

- pytest con servidor HTTP fake.
- Manual local smoke.

**Criterios de aceptación.**

- Proyecto process puede arrancar y detenerse desde API.
- Niwa conoce PID/status.
- Logs disponibles.

**Brief corto para LLM.**

```text
Implementa DEPLOY-05 (Process manager local) en Niwa. Objetivo: Soportar proyectos que necesitan proceso propio. Toca principalmente `backend/app/deployments/process_manager.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest con servidor HTTP fake.; Manual local smoke.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-06 — Asignador de puertos

**Objetivo.** Evitar conflictos entre proyectos process.

**Archivos probables.**

- `backend/app/deployments/ports.py`
- `backend/app/config.py`

**Instrucciones de implementación.**

- Crear rango configurable, por ejemplo 41000-41999.
- Reservar puerto por deployment/proyecto.
- Detectar puerto ocupado y elegir otro.
- Persistir puerto asignado.

**Tests/verificación.**

- Unit tests port allocator.

**Criterios de aceptación.**

- Dos proyectos no reciben el mismo puerto activo.
- Si el puerto fijo está ocupado, error claro o reasignación según policy.

**Brief corto para LLM.**

```text
Implementa DEPLOY-06 (Asignador de puertos) en Niwa. Objetivo: Evitar conflictos entre proyectos process. Toca principalmente `backend/app/deployments/ports.py`, `backend/app/config.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Unit tests port allocator.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-07 — Healthchecks

**Objetivo.** Saber si un deploy está realmente vivo.

**Archivos probables.**

- `backend/app/deployments/health.py`

**Instrucciones de implementación.**

- Para static: comprobar index o archivo esperado.
- Para process: HTTP GET a localhost:port + healthcheck_path.
- Registrar últimas comprobaciones y estado.

**Tests/verificación.**

- Tests con server fake.
- Endpoint health tests.

**Criterios de aceptación.**

- Deploy process pasa healthy solo si responde.
- Un proceso muerto cambia a unhealthy/stopped.
- UI muestra última comprobación.

**Brief corto para LLM.**

```text
Implementa DEPLOY-07 (Healthchecks) en Niwa. Objetivo: Saber si un deploy está realmente vivo. Toca principalmente `backend/app/deployments/health.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Tests con server fake.; Endpoint health tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-08 — API/UI de Deploys y logs

**Objetivo.** Operar deploys desde Niwa.

**Archivos probables.**

- `backend/app/api/deployments.py`
- `frontend/src/features/deployments`

**Instrucciones de implementación.**

- Endpoints: list deployments, trigger deploy, stop, restart, rollback, logs.
- UI tab Deploys con estado, commit, fecha, URLs, botones permitidos.
- Logs paginados o truncados con expand.

**Tests/verificación.**

- API tests.
- Frontend tests.

**Criterios de aceptación.**

- Usuario puede lanzar deploy manual, ver logs y parar/reiniciar si process.
- Acciones peligrosas piden confirmación.

**Brief corto para LLM.**

```text
Implementa DEPLOY-08 (API/UI de Deploys y logs) en Niwa. Objetivo: Operar deploys desde Niwa. Toca principalmente `backend/app/api/deployments.py`, `frontend/src/features/deployments`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: API tests.; Frontend tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-09 — Rollback

**Objetivo.** Volver a una versión anterior.

**Archivos probables.**

- `backend/app/deployments/service.py`

**Instrucciones de implementación.**

- Para static: cambiar deployment activo a artifact_path anterior.
- Para process: parar activo y arrancar comando/artifact anterior si aplica.
- Registrar evento rollback_from/rollback_to.

**Tests/verificación.**

- Static rollback test.
- UI rollback test.

**Criterios de aceptación.**

- Rollback funciona para static.
- Para process se documentan limitaciones si no hay artifacts versionados completos.

**Brief corto para LLM.**

```text
Implementa DEPLOY-09 (Rollback) en Niwa. Objetivo: Volver a una versión anterior. Toca principalmente `backend/app/deployments/service.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Static rollback test.; UI rollback test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-10 — Triggers de auto-deploy

**Objetivo.** Conectar deploy con task/PR según política.

**Archivos probables.**

- `backend/app/executor/core.py`
- `backend/app/finalize.py`
- `backend/app/deployments`

**Instrucciones de implementación.**

- Añadir deploy_trigger: manual, on_task_done, on_pr_merge.
- En safe mode, on_pr_merge requiere detectar merge o acción UI de merge.
- En dangerous, puede desplegar tras auto-merge si policy lo permite.

**Tests/verificación.**

- Executor/finalize tests.
- Smoke deploy trigger.

**Criterios de aceptación.**

- Manual no despliega automáticamente.
- on_task_done/on_pr_merge se comportan según config.
- Eventos explican por qué se desplegó o no.

**Brief corto para LLM.**

```text
Implementa DEPLOY-10 (Triggers de auto-deploy) en Niwa. Objetivo: Conectar deploy con task/PR según política. Toca principalmente `backend/app/executor/core.py`, `backend/app/finalize.py`, `backend/app/deployments`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Executor/finalize tests.; Smoke deploy trigger.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DEPLOY-11 — Smoke deploy local

**Objetivo.** Cerrar fase con validación automática.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Extender make smoke para static versionado, process fake, healthcheck y rollback.
- No requerir red externa.
- Incluir logs de deploy en report.md.

**Tests/verificación.**

- make smoke.
- make test.

**Criterios de aceptación.**

- make smoke valida deploys nuevos.
- Deploy legacy deja de ser único check.

**Brief corto para LLM.**

```text
Implementa DEPLOY-11 (Smoke deploy local) en Niwa. Objetivo: Cerrar fase con validación automática. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke.; make test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
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