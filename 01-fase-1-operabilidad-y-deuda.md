# Fase 1 — Operabilidad, documentación y deuda inmediata

Fecha de preparación: 2026-04-30

**Resumen.** Hacer que el repo sea confiable para trabajar: estado documental coherente, diagnóstico local, logs útiles y errores accionables.

## Contexto

- README sigue comunicando v1 MVP mientras STATE dice v1.1-cycle-complete.
- El sistema local depende de Python, Node, git, Claude CLI, gh, DB/config y servicios; falta un diagnóstico integrado.
- Para que otro LLM trabaje bien, los errores deben aparecer como contratos claros, no como logs dispersos.

## No-objetivos

- No cambiar pipeline de negocio.
- No añadir auth ni dominio público.
- No implementar MCP.

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

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 1 — Operabilidad, documentación y deuda inmediata.

Contexto: Hacer que el repo sea confiable para trabajar: estado documental coherente, diagnóstico local, logs útiles y errores accionables.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-OPS-01.** Alinear docs y estado del repo.
- **PR-OPS-02.** niwa doctor + checks de entorno.
- **PR-OPS-03.** Logs/eventos visibles y normalización de errores finalize/executor.
- **PR-OPS-04.** Mejoras de system/readiness y ayuda operativa.

## Tareas

### DOC-01 — Alinear README, SPEC, HANDBOOK y STATE

**Objetivo.** Eliminar contradicciones y dejar claro qué está implementado y qué no.

**Archivos probables.**

- `README.md`
- `docs/SPEC.md`
- `docs/HANDBOOK.md`
- `docs/STATE.md`

**Instrucciones de implementación.**

- Actualizar README con estado v1.1 post-MVP si procede.
- Separar SPEC histórico de roadmap actual; si SPEC queda como MVP histórico, marcarlo explícitamente.
- Actualizar HANDBOOK con módulos añadidos en v1.1: dev CLI, attachments, pulls tab, merge button.
- Asegurar que STATE menciona make smoke cuando Fase 0 se cierre.

**Tests/verificación.**

- Revisión manual de docs.
- Opcional: script docs lint para links rotos.

**Criterios de aceptación.**

- Un lector nuevo puede instalar, correr smoke y entender límites sin leer historial completo.
- No hay frases que digan simultáneamente que algo está fuera de scope y ya implementado sin aclaración.

**Brief corto para LLM.**

```text
Implementa DOC-01 (Alinear README, SPEC, HANDBOOK y STATE) en Niwa. Objetivo: Eliminar contradicciones y dejar claro qué está implementado y qué no. Toca principalmente `README.md`, `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Revisión manual de docs.; Opcional: script docs lint para links rotos.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### DOC-02 — Limpiar comentarios/docstrings obsoletos

**Objetivo.** Evitar que el código engañe a un LLM o humano.

**Archivos probables.**

- `backend/app/**/*.py`
- `docs/STATE.md`

**Instrucciones de implementación.**

- Buscar referencias a PRs antiguos que digan que un módulo aún no está integrado.
- Corregir docstrings de triage/executor/finalize/pulls si contradicen el estado real.
- No borrar contexto histórico útil; moverlo a docs/STATE si hace falta.

**Tests/verificación.**

- pytest existente.
- grep manual documentado en PR.

**Criterios de aceptación.**

- grep de términos obsoletos no encuentra contradicciones evidentes.
- Docstrings describen comportamiento actual.

**Brief corto para LLM.**

```text
Implementa DOC-02 (Limpiar comentarios/docstrings obsoletos) en Niwa. Objetivo: Evitar que el código engañe a un LLM o humano. Toca principalmente `backend/app/**/*.py`, `docs/STATE.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest existente.; grep manual documentado en PR.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### OPS-01 — Implementar niwa doctor

**Objetivo.** Crear diagnóstico local accionable.

**Archivos probables.**

- `backend/app/niwa_cli.py`
- `backend/app/ops/doctor.py`
- `backend/tests/test_doctor.py`

**Instrucciones de implementación.**

- Añadir subcomando niwa-executor doctor o niwa doctor según convención actual.
- Checks: Python, Node, npm, git, gh, claude, claude auth smoke mínimo si viable, gh auth status, DB path, config path, migrations, service file, write permissions, ports.
- Emitir salida humana y JSON opcional (--json).
- No hacer llamadas destructivas ni crear tareas.

**Tests/verificación.**

- pytest unitario de checks con monkeypatch.
- Smoke parcial en host.

**Criterios de aceptación.**

- doctor devuelve exit 0 si checks críticos pasan y exit no-cero si falla un crítico.
- Cada check fallido incluye causa y remediation.
- Modo --json se puede usar en UI/System.

**Brief corto para LLM.**

```text
Implementa OPS-01 (Implementar niwa doctor) en Niwa. Objetivo: Crear diagnóstico local accionable. Toca principalmente `backend/app/niwa_cli.py`, `backend/app/ops/doctor.py`, `backend/tests/test_doctor.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest unitario de checks con monkeypatch.; Smoke parcial en host.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### OPS-02 — Integrar smoke en comandos operativos

**Objetivo.** Conectar Fase 0 con UX de operador.

**Archivos probables.**

- `backend/app/niwa_cli.py`
- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Si make smoke existe, añadir niwa-executor smoke que delegue o documentar por qué no.
- Mostrar ubicación de reportes.
- Permitir --keep-sandbox para depuración.

**Tests/verificación.**

- pytest CLI help.
- make smoke.

**Criterios de aceptación.**

- El usuario puede ejecutar smoke sin recordar paths internos.
- El comando no pisa ~/.niwa salvo que se indique explícitamente.

**Brief corto para LLM.**

```text
Implementa OPS-02 (Integrar smoke en comandos operativos) en Niwa. Objetivo: Conectar Fase 0 con UX de operador. Toca principalmente `backend/app/niwa_cli.py`, `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest CLI help.; make smoke.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### OPS-03 — Normalizar errores de finalize

**Objetivo.** Hacer que commit/push/PR/merge fallen de forma legible.

**Archivos probables.**

- `backend/app/finalize.py`
- `backend/app/models`
- `backend/app/services/events.py`

**Instrucciones de implementación.**

- Definir enum/códigos de errores para nothing_to_commit, no_remote, no_branch, push_failed, gh_missing, gh_pr_create_failed, gh_pr_merge_failed.
- Persistir resultado de finalize como task_event o run metadata.
- Mantener compatibilidad con commands_skipped actuales.

**Tests/verificación.**

- pytest finalize para cada error.
- Smoke PR fake.

**Criterios de aceptación.**

- UI/API puede mostrar qué parte de finalize falló.
- El usuario recibe comando manual cuando aplique.
- No se pierde el comportamiento best-effort.

**Brief corto para LLM.**

```text
Implementa OPS-03 (Normalizar errores de finalize) en Niwa. Objetivo: Hacer que commit/push/PR/merge fallen de forma legible. Toca principalmente `backend/app/finalize.py`, `backend/app/models`, `backend/app/services/events.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest finalize para cada error.; Smoke PR fake.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### OPS-04 — Logs por tarea en API/UI

**Objetivo.** Depurar sin entrar por SSH a logs del servidor.

**Archivos probables.**

- `backend/app/api/tasks.py`
- `frontend/src/features/tasks`

**Instrucciones de implementación.**

- Añadir endpoint o extender detalle de task/runs para traer eventos relevantes.
- Mostrar en UI timeline con filtros: task events, run events, verification, finalize.
- Truncar y redaccionar contenido sensible si procede.

**Tests/verificación.**

- Frontend tests con eventos mock.
- Backend tests de endpoint.

**Criterios de aceptación.**

- Detalle de tarea muestra historial suficiente para diagnosticar fallos.
- No se muestran secretos evidentes.
- La UI maneja empty/error states.

**Brief corto para LLM.**

```text
Implementa OPS-04 (Logs por tarea en API/UI) en Niwa. Objetivo: Depurar sin entrar por SSH a logs del servidor. Toca principalmente `backend/app/api/tasks.py`, `frontend/src/features/tasks`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Frontend tests con eventos mock.; Backend tests de endpoint.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### OPS-05 — Mejorar /system y readiness

**Objetivo.** Convertir readiness en panel operativo.

**Archivos probables.**

- `backend/app/api/readiness.py`
- `frontend/src/routes/SystemRoute.tsx`

**Instrucciones de implementación.**

- Añadir checks de executor service/dev server, DB migrations, claude path, gh path/auth opcional y queue counts.
- Separar readiness para salud técnica de diagnostics para ayuda humana.
- UI /system debe mostrar checks con severidad critical/warning/info.

**Tests/verificación.**

- pytest readiness.
- Frontend tests system page.

**Criterios de aceptación.**

- Un usuario sabe si puede crear tareas, PRs y smoke-live desde la UI.
- Errores de entorno se explican con pasos concretos.

**Brief corto para LLM.**

```text
Implementa OPS-05 (Mejorar /system y readiness) en Niwa. Objetivo: Convertir readiness en panel operativo. Toca principalmente `backend/app/api/readiness.py`, `frontend/src/routes/SystemRoute.tsx`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest readiness.; Frontend tests system page.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### OPS-06 — Config inspection y edición segura mínima

**Objetivo.** Exponer configuración sin editar TOML a ciegas.

**Archivos probables.**

- `backend/app/config.py`
- `backend/app/niwa_cli.py`

**Instrucciones de implementación.**

- Añadir comando niwa-executor config show.
- Mostrar paths efectivos, host/port, DB, logs y flags.
- No añadir aún configuración completa vía UI; eso va en Fase 3.

**Tests/verificación.**

- pytest config show con HOME temporal.

**Criterios de aceptación.**

- config show imprime valores efectivos y archivo de origen.
- No filtra secretos en claro.

**Brief corto para LLM.**

```text
Implementa OPS-06 (Config inspection y edición segura mínima) en Niwa. Objetivo: Exponer configuración sin editar TOML a ciegas. Toca principalmente `backend/app/config.py`, `backend/app/niwa_cli.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: pytest config show con HOME temporal.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### OPS-07 — Runbook de instalación/desinstalación

**Objetivo.** Reducir fricción para máquinas nuevas.

**Archivos probables.**

- `docs/OPERATIONS.md`
- `README.md`

**Instrucciones de implementación.**

- Documentar fresh install, update, stop, dev start/stop, clean local, backup básico.
- Incluir advertencia de que ~/.niwa comparte DB entre clones.
- Incluir cómo correr make smoke después de install.

**Tests/verificación.**

- Revisión manual.

**Criterios de aceptación.**

- docs/OPERATIONS.md existe y cubre Mac/Linux/WSL a nivel práctico.
- README enlaza al runbook.

**Brief corto para LLM.**

```text
Implementa OPS-07 (Runbook de instalación/desinstalación) en Niwa. Objetivo: Reducir fricción para máquinas nuevas. Toca principalmente `docs/OPERATIONS.md`, `README.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Revisión manual.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### OPS-08 — Actualizar patrones para sub-agentes/LLM

**Objetivo.** Hacer briefs más resistentes al scope creep.

**Archivos probables.**

- `docs/AGENTS.md`
- `docs/plans/TEMPLATE.md`

**Instrucciones de implementación.**

- Crear docs/AGENTS.md con reglas: leer SPEC/HANDBOOK/STATE, implementar solo el PR, tests obligatorios, reportar desviaciones, no tocar futuras fases.
- Añadir plantilla de PR brief con LOC cap, no-goals, acceptance y stop conditions.

**Tests/verificación.**

- No aplica; docs.

**Criterios de aceptación.**

- Un LLM puede recibir docs/AGENTS.md + fase/tarea y producir un PR acotado.
- Los briefs futuros incluyen stop conditions explícitas.

**Brief corto para LLM.**

```text
Implementa OPS-08 (Actualizar patrones para sub-agentes/LLM) en Niwa. Objetivo: Hacer briefs más resistentes al scope creep. Toca principalmente `docs/AGENTS.md`, `docs/plans/TEMPLATE.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: No aplica; docs.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
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