# Fase 6 — Seguridad, aislamiento y recuperación

Fecha de preparación: 2026-04-30

**Resumen.** Hacer seguro operar Niwa con un LLM que ejecuta código y con UI potencialmente accesible online.

## Contexto

- El adapter usa Claude Code CLI y el MVP confía en ramas/verificación como barrera principal.
- Al exponer Niwa online, hay que proteger tokens, comandos, workspaces, logs, deploys y acciones de merge/deploy.
- Esta fase debe convertir riesgos implícitos en políticas, auditoría y mecanismos de contención.

## No-objetivos

- No prometer sandbox perfecto.
- No meter Kubernetes obligatorio.
- No desbloquear multi-tenant.

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

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 6 — Seguridad, aislamiento y recuperación.

Contexto: Hacer seguro operar Niwa con un LLM que ejecuta código y con UI potencialmente accesible online.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-SEC-01.** Threat model + redaction + audit log.
- **PR-SEC-02.** Policies/scopes por proyecto y checks de workspace.
- **PR-SEC-03.** Kill switch, cancellation robusta y process limits.
- **PR-SEC-04.** Backups/restore y disaster drill.
- **PR-SEC-05.** Security smoke/regression tests.

## Tareas

### SEC-01 — Threat model mínimo

**Objetivo.** Documentar riesgos y límites reales.

**Archivos probables.**

- `docs/SECURITY.md`

**Instrucciones de implementación.**

- Crear docs/SECURITY.md con activos: repos, tokens, DB, config, deploys, PRs, Claude session, logs.
- Amenazas: task maliciosa, repo malicioso, prompt injection, token leakage, public endpoint, auto-merge, runaway process.
- Mitigaciones existentes y faltantes.

**Tests/verificación.**

- Revisión manual.

**Criterios de aceptación.**

- Documento honesto; no promete aislamiento que no existe.
- Incluye matriz riesgo/impacto/mitigación.

**Brief corto para LLM.**

```text
Implementa SEC-01 (Threat model mínimo) en Niwa. Objetivo: Documentar riesgos y límites reales. Toca principalmente `docs/SECURITY.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Revisión manual.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-02 — Redacción de secretos en logs/eventos

**Objetivo.** Evitar filtrar tokens en UI/reportes.

**Archivos probables.**

- `backend/app/security/redaction.py`
- `backend/app/events/logging.py`

**Instrucciones de implementación.**

- Crear redactor central para patrones: tokens GitHub, Anthropic, Bearer, env vars comunes, URLs con credentials.
- Aplicarlo antes de persistir logs largos y antes de renderizar UI.
- No redaccionar paths normales ni mensajes útiles innecesariamente.

**Tests/verificación.**

- Unit tests de redactor.
- Frontend snapshot si aplica.

**Criterios de aceptación.**

- Secretos simulados aparecen como [REDACTED].
- Logs siguen siendo útiles para debug.

**Brief corto para LLM.**

```text
Implementa SEC-02 (Redacción de secretos en logs/eventos) en Niwa. Objetivo: Evitar filtrar tokens en UI/reportes. Toca principalmente `backend/app/security/redaction.py`, `backend/app/events/logging.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Unit tests de redactor.; Frontend snapshot si aplica.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-03 — Audit log

**Objetivo.** Registrar acciones humanas y automáticas importantes.

**Archivos probables.**

- `backend/app/models/audit.py`
- `backend/app/services/audit.py`

**Instrucciones de implementación.**

- Tabla audit_events con actor_type, actor_id/token_id nullable, action, target_type/id, payload_json, ip/user_agent si aplica, created_at.
- Eventos: login, token create/revoke, project update, task create/respond/cancel/retry, approve plan, merge, deploy, settings exposure.

**Tests/verificación.**

- Backend audit tests.

**Criterios de aceptación.**

- Acciones críticas quedan auditadas.
- No se guardan secretos en payload.
- Endpoint admin lista eventos con paginación.

**Brief corto para LLM.**

```text
Implementa SEC-03 (Audit log) en Niwa. Objetivo: Registrar acciones humanas y automáticas importantes. Toca principalmente `backend/app/models/audit.py`, `backend/app/services/audit.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend audit tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-04 — Políticas/scopes por proyecto

**Objetivo.** Limitar capacidades de cada repo.

**Archivos probables.**

- `backend/app/policies`
- `backend/app/executor/core.py`

**Instrucciones de implementación.**

- Campos/policy: allow_network, allow_shell, allow_deploy, allow_auto_merge, allowed_paths, max_runtime_seconds.
- Integrar con executor antes de lanzar adapter y deploy runner.
- Policy effective debe mostrarse en UI settings.

**Tests/verificación.**

- Policy validation tests.
- Executor policy tests.

**Criterios de aceptación.**

- Proyecto puede impedir auto-merge/deploy aunque token tenga permiso.
- Policy default conservadora.

**Brief corto para LLM.**

```text
Implementa SEC-04 (Políticas/scopes por proyecto) en Niwa. Objetivo: Limitar capacidades de cada repo. Toca principalmente `backend/app/policies`, `backend/app/executor/core.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Policy validation tests.; Executor policy tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-05 — Workspace isolation checks

**Objetivo.** Detectar escrituras fuera del repo.

**Archivos probables.**

- `backend/app/verification`
- `backend/app/services/attachments.py`
- `backend/app/api/deploy.py`

**Instrucciones de implementación.**

- Reforzar verificación de artifacts_outside_cwd.
- Snapshot de archivos antes/después si viable.
- Rechazar symlinks peligrosos para attachments/artifacts.

**Tests/verificación.**

- Security regression tests.

**Criterios de aceptación.**

- Una escritura fuera de cwd falla la tarea.
- Symlink traversal en attachment/deploy no sirve archivos fuera.

**Brief corto para LLM.**

```text
Implementa SEC-05 (Workspace isolation checks) en Niwa. Objetivo: Detectar escrituras fuera del repo. Toca principalmente `backend/app/verification`, `backend/app/services/attachments.py`, `backend/app/api/deploy.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Security regression tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-06 — Process limits y timeouts

**Objetivo.** Evitar procesos runaway.

**Archivos probables.**

- `backend/app/executor`
- `backend/app/deployments/process_manager.py`

**Instrucciones de implementación.**

- Configurar timeouts por adapter, build, start, healthcheck.
- Limitar concurrencia global y por proyecto si aún no está.
- Propagar cancellation al subprocess group, no solo proceso padre.

**Tests/verificación.**

- Executor/process manager tests.

**Criterios de aceptación.**

- Un fake process infinito se mata correctamente.
- No quedan procesos huérfanos en tests controlados.

**Brief corto para LLM.**

```text
Implementa SEC-06 (Process limits y timeouts) en Niwa. Objetivo: Evitar procesos runaway. Toca principalmente `backend/app/executor`, `backend/app/deployments/process_manager.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Executor/process manager tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-07 — Kill switch global

**Objetivo.** Parar cola y procesos gestionados.

**Archivos probables.**

- `backend/app/ops`
- `frontend/src/routes/SystemRoute.tsx`

**Instrucciones de implementación.**

- Añadir comando/API para pause executor y stop managed deployments.
- UI muestra estado paused y botón resume si está autorizado.
- Kill switch debe registrar audit event.

**Tests/verificación.**

- Backend tests.
- Manual smoke.

**Criterios de aceptación.**

- Al activar kill switch no se toman nuevas tareas.
- Procesos deploy gestionados se detienen o quedan marcados con error si no.

**Brief corto para LLM.**

```text
Implementa SEC-07 (Kill switch global) en Niwa. Objetivo: Parar cola y procesos gestionados. Toca principalmente `backend/app/ops`, `frontend/src/routes/SystemRoute.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend tests.; Manual smoke.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-08 — Backups

**Objetivo.** Proteger DB/config/metadata.

**Archivos probables.**

- `backend/app/ops/backup.py`

**Instrucciones de implementación.**

- Comando niwa-executor backup crea archivo versionado con DB, config redaccionada si procede, deployment metadata, no repos completos por defecto.
- Opciones include-deploy-artifacts e include-logs.
- Guardar manifest con checksums.

**Tests/verificación.**

- Backup command tests con HOME temporal.

**Criterios de aceptación.**

- Backup se crea y puede inspeccionarse.
- No incluye secretos en claro salvo opt-in consciente.

**Brief corto para LLM.**

```text
Implementa SEC-08 (Backups) en Niwa. Objetivo: Proteger DB/config/metadata. Toca principalmente `backend/app/ops/backup.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backup command tests con HOME temporal.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-09 — Restore

**Objetivo.** Recuperar Niwa en otra máquina.

**Archivos probables.**

- `backend/app/ops/backup.py`
- `backend/app/ops/restore.py`

**Instrucciones de implementación.**

- Comando restore valida manifest, recrea DB/config, advierte si local_path no existe.
- No sobrescribe instalación activa sin --force.
- Después de restore, doctor indica tareas de reparación.

**Tests/verificación.**

- Backup/restore integration test.

**Criterios de aceptación.**

- Restore de backup de fixture funciona.
- Paths faltantes se reportan claramente.

**Brief corto para LLM.**

```text
Implementa SEC-09 (Restore) en Niwa. Objetivo: Recuperar Niwa en otra máquina. Toca principalmente `backend/app/ops/backup.py`, `backend/app/ops/restore.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backup/restore integration test.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-10 — Dependency/security checks

**Objetivo.** Detectar vulnerabilidades básicas.

**Archivos probables.**

- `.github/workflows/security.yml`
- `docs/SECURITY.md`

**Instrucciones de implementación.**

- Añadir comandos/documentación para pip/npm audit según herramientas disponibles.
- CI puede correr audit no bloqueante inicialmente.
- Registrar excepciones conocidas.

**Tests/verificación.**

- CI job opcional.

**Criterios de aceptación.**

- Hay un procedimiento repetible para revisar dependencias.
- No introduce flakiness excesiva en CI principal.

**Brief corto para LLM.**

```text
Implementa SEC-10 (Dependency/security checks) en Niwa. Objetivo: Detectar vulnerabilidades básicas. Toca principalmente `.github/workflows/security.yml`, `docs/SECURITY.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: CI job opcional.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SEC-11 — Security smoke

**Objetivo.** Automatizar regresiones críticas.

**Archivos probables.**

- `scripts/smoke_security.py`
- `Makefile`

**Instrucciones de implementación.**

- Extender make smoke o añadir make smoke-security para: auth required, token scopes, secret redaction, outside-cwd fail, kill switch.
- No requerir red externa.

**Tests/verificación.**

- make smoke-security o make smoke.

**Criterios de aceptación.**

- Smoke de seguridad falla ante regresiones críticas.
- Reportes señalan riesgo exacto.

**Brief corto para LLM.**

```text
Implementa SEC-11 (Security smoke) en Niwa. Objetivo: Automatizar regresiones críticas. Toca principalmente `scripts/smoke_security.py`, `Makefile`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke-security o make smoke.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
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