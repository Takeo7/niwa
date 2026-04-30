# Fase 8 — QA, robustez, packaging y mantenimiento

Fecha de preparación: 2026-04-30

**Resumen.** Convertir Niwa en una herramienta mantenible: tests de integración, migraciones, CI, observabilidad, limpieza, releases y runbooks.

## Contexto

- Cuando el producto tenga pipeline, deploy, online y MCP, la complejidad exigirá pruebas y mantenimiento más sistemáticos.
- Esta fase no añade nuevas capacidades de negocio; reduce regresiones y coste operativo.
- Debe consolidar todo lo anterior en releases instalables y verificables.

## No-objetivos

- No añadir nuevas features de producto salvo las necesarias para mantenimiento.
- No convertirlo aún en SaaS/multiusuario.

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

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 8 — QA, robustez, packaging y mantenimiento.

Contexto: Convertir Niwa en una herramienta mantenible: tests de integración, migraciones, CI, observabilidad, limpieza, releases y runbooks.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-QA-01.** Fixture repos + integration tests.
- **PR-QA-02.** Migration tests + CI matrix.
- **PR-QA-03.** Frontend E2E + smoke UI.
- **PR-QA-04.** Observabilidad, locks, concurrency.
- **PR-QA-05.** Cleanup, packaging, releases y runbooks.

## Tareas

### QA-01 — Fixture repos de integración

**Objetivo.** Probar Niwa contra proyectos representativos.

**Archivos probables.**

- `backend/tests/fixtures/repos`
- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Crear fixtures: script-python, library-python, web-vite/static, process-node.
- Cada fixture debe tener tests/build/start controlados.
- Usarlos en smoke y tests de integración con fake Claude.

**Tests/verificación.**

- pytest integration fixtures.
- make smoke.

**Criterios de aceptación.**

- Fixtures reproducibles y rápidos.
- Cubren project.kind script/library/web-deployable.

**Brief corto para LLM.**

```text
Implementa QA-01 (Fixture repos de integración) en Niwa. Objetivo: Probar Niwa contra proyectos representativos. Toca principalmente `backend/tests/fixtures/repos`, `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest integration fixtures.; make smoke.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-02 — Tests de migraciones

**Objetivo.** Garantizar upgrades limpios.

**Archivos probables.**

- `backend/tests/test_migrations.py`

**Instrucciones de implementación.**

- Crear DBs snapshot antiguas o factories por versión.
- Ejecutar Alembic upgrade head y validar tablas/campos.
- Cubrir migraciones de estados/policies/deployments/tokens.

**Tests/verificación.**

- pytest migration tests.

**Criterios de aceptación.**

- Una DB v1.1 puede migrar a head sin pérdida básica.
- Campos default correctos.

**Brief corto para LLM.**

```text
Implementa QA-02 (Tests de migraciones) en Niwa. Objetivo: Garantizar upgrades limpios. Toca principalmente `backend/tests/test_migrations.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest migration tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-03 — CI matrix

**Objetivo.** Aumentar confianza cross-platform razonable.

**Archivos probables.**

- `.github/workflows/*.yml`

**Instrucciones de implementación.**

- CI: Python 3.11/3.12 si soportado, Node 22, Ubuntu.
- Jobs: backend, frontend, smoke fake, optional security.
- Cache pip/npm sin esconder fallos de lockfile.

**Tests/verificación.**

- GitHub Actions verde.

**Criterios de aceptación.**

- CI cubre make test y make smoke.
- Artifacts de logs en fallo.

**Brief corto para LLM.**

```text
Implementa QA-03 (CI matrix) en Niwa. Objetivo: Aumentar confianza cross-platform razonable. Toca principalmente `.github/workflows/*.yml`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: GitHub Actions verde.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-04 — Playwright smoke UI

**Objetivo.** Validar flujos reales de navegador.

**Archivos probables.**

- `frontend/e2e`
- `playwright.config.ts`
- `Makefile`

**Instrucciones de implementación.**

- Añadir make smoke-ui con backend/frontend arrancados en puertos libres.
- Flujos: login si existe, create project, create task, task detail, respond waiting_input, PR tab, deploy tab.
- Usar fake backend/fixture para estabilidad.

**Tests/verificación.**

- make smoke-ui.

**Criterios de aceptación.**

- smoke-ui corre headless sin intervención.
- Screenshots/logs se guardan en fallo.

**Brief corto para LLM.**

```text
Implementa QA-04 (Playwright smoke UI) en Niwa. Objetivo: Validar flujos reales de navegador. Toca principalmente `frontend/e2e`, `playwright.config.ts`, `Makefile`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke-ui.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-05 — Modo demo/fake completo

**Objetivo.** Probar UX sin Claude/GitHub reales.

**Archivos probables.**

- `backend/app/config.py`
- `backend/app/adapters`
- `frontend/src/routes/SystemRoute.tsx`

**Instrucciones de implementación.**

- Config global para fake adapter desde UI/dev.
- Fake scenarios: success, split, waiting_input, review changes, deploy failed.
- No activar fake por accidente en producción sin señal clara.

**Tests/verificación.**

- Backend/frontend tests.

**Criterios de aceptación.**

- Demo local permite enseñar Niwa sin credenciales.
- UI indica modo fake si está activo.

**Brief corto para LLM.**

```text
Implementa QA-05 (Modo demo/fake completo) en Niwa. Objetivo: Probar UX sin Claude/GitHub reales. Toca principalmente `backend/app/config.py`, `backend/app/adapters`, `frontend/src/routes/SystemRoute.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Backend/frontend tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-06 — Observabilidad básica

**Objetivo.** Medir salud y rendimiento.

**Archivos probables.**

- `backend/app/api/system.py`
- `frontend/src/routes/SystemRoute.tsx`

**Instrucciones de implementación.**

- Métricas: queue length, tasks by status, run durations, failure rates, deploy health, executor heartbeat.
- Endpoint /api/system/metrics o sección System.
- No meter Prometheus obligatorio si no hace falta; JSON basta al principio.

**Tests/verificación.**

- API tests metrics.

**Criterios de aceptación.**

- System muestra métricas relevantes.
- No filtra secretos.

**Brief corto para LLM.**

```text
Implementa QA-06 (Observabilidad básica) en Niwa. Objetivo: Medir salud y rendimiento. Toca principalmente `backend/app/api/system.py`, `frontend/src/routes/SystemRoute.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: API tests metrics.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-07 — Límites de concurrencia

**Objetivo.** Evitar sobrecarga y carreras.

**Archivos probables.**

- `backend/app/executor/core.py`
- `backend/app/config.py`

**Instrucciones de implementación.**

- Config max_concurrent_tasks global.
- Config max_concurrent_tasks_per_project default 1.
- Executor respeta límites al reclamar queued.

**Tests/verificación.**

- Executor concurrency tests.

**Criterios de aceptación.**

- No se ejecutan dos tareas del mismo proyecto por defecto.
- Global limit se respeta.

**Brief corto para LLM.**

```text
Implementa QA-07 (Límites de concurrencia) en Niwa. Objetivo: Evitar sobrecarga y carreras. Toca principalmente `backend/app/executor/core.py`, `backend/app/config.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Executor concurrency tests.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-08 — Locks por proyecto/workspace

**Objetivo.** Proteger repos de cambios concurrentes.

**Archivos probables.**

- `backend/app/executor/locks.py`

**Instrucciones de implementación.**

- Implementar lock persistente o file lock por project local_path.
- Detectar stale locks con heartbeat.
- UI/System debe mostrar locks activos.

**Tests/verificación.**

- Lock tests con procesos/threads fake.

**Criterios de aceptación.**

- Dos executor instances no procesan el mismo repo a la vez.
- Lock stale se puede limpiar con comando seguro.

**Brief corto para LLM.**

```text
Implementa QA-08 (Locks por proyecto/workspace) en Niwa. Objetivo: Proteger repos de cambios concurrentes. Toca principalmente `backend/app/executor/locks.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Lock tests con procesos/threads fake.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-09 — Limpieza de ramas, worktrees y artifacts

**Objetivo.** Evitar acumulación local.

**Archivos probables.**

- `backend/app/ops/cleanup.py`

**Instrucciones de implementación.**

- Comando niwa-executor cleanup con dry-run default.
- Limpiar ramas niwa/task-* mergeadas/canceladas según política.
- Limpiar deployments/logs antiguos con retención configurable.

**Tests/verificación.**

- Cleanup tests con repo fixture.

**Criterios de aceptación.**

- Dry-run muestra qué borraría.
- No borra ramas no-Niwa.
- Retención configurable.

**Brief corto para LLM.**

```text
Implementa QA-09 (Limpieza de ramas, worktrees y artifacts) en Niwa. Objetivo: Evitar acumulación local. Toca principalmente `backend/app/ops/cleanup.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Cleanup tests con repo fixture.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-10 — Packaging/release

**Objetivo.** Hacer instalación menos artesanal.

**Archivos probables.**

- `docs/RELEASE.md`
- `bootstrap.sh`
- `backend/app/niwa_cli.py`

**Instrucciones de implementación.**

- Definir versionado semver o calendar version.
- Release notes automáticas/manuales.
- Script install/update estable que preserve ~/.niwa.
- Checks post-update: migrations + doctor + smoke opcional.

**Tests/verificación.**

- Release dry run.

**Criterios de aceptación.**

- Existe proceso de release reproducible.
- Update no rompe DB sin backup/aviso.

**Brief corto para LLM.**

```text
Implementa QA-10 (Packaging/release) en Niwa. Objetivo: Hacer instalación menos artesanal. Toca principalmente `docs/RELEASE.md`, `bootstrap.sh`, `backend/app/niwa_cli.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Release dry run.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-11 — Runbooks de operación

**Objetivo.** Documentar incidentes comunes.

**Archivos probables.**

- `docs/runbooks/*.md`

**Instrucciones de implementación.**

- Runbooks: Claude no auth, gh no auth, repo sucio, migration failed, task stuck, deploy unhealthy, proxy TLS failed, restore backup.
- Cada runbook: síntomas, diagnóstico, solución, comandos.

**Tests/verificación.**

- Docs review.

**Criterios de aceptación.**

- Un operador puede resolver fallos comunes sin revisar código.
- System/doctor enlaza a runbooks si aplica.

**Brief corto para LLM.**

```text
Implementa QA-11 (Runbooks de operación) en Niwa. Objetivo: Documentar incidentes comunes. Toca principalmente `docs/runbooks/*.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Docs review.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### QA-12 — Retrospectiva y deuda viva

**Objetivo.** Mantener roadmap honesto.

**Archivos probables.**

- `docs/DEBT.md`
- `docs/STATE.md`

**Instrucciones de implementación.**

- Crear docs/DEBT.md o actualizar STATE con deuda abierta, owner, severidad y fase.
- Cada PR grande debe añadir deuda explícita si deja atajos.
- Evitar que STATE sea solo historial; añadir sección next decisions.

**Tests/verificación.**

- Docs review.

**Criterios de aceptación.**

- La deuda no queda enterrada en comentarios de PR.
- Cada fase cierra con decisiones/documentación actualizadas.

**Brief corto para LLM.**

```text
Implementa QA-12 (Retrospectiva y deuda viva) en Niwa. Objetivo: Mantener roadmap honesto. Toca principalmente `docs/DEBT.md`, `docs/STATE.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Docs review.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
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