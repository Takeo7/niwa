# Fase 0 — Smoke automatizado y confianza en v1.1

Fecha de preparación: 2026-04-30

**Resumen.** Convertir el smoke manual de v1.1 en un comando reproducible que valide el flujo E2E sin credenciales reales.

## Contexto

- El estado operativo declara el ciclo v1.1 cerrado y marca como próximo paso smoke-v1.1.
- El Makefile actual no incluye target smoke; solo install, dev, test y clean.
- El repo ya tiene un fake Claude CLI y el executor soporta modo --once; conviene usar esas piezas en vez de hacer pruebas manuales.

## No-objetivos

- No añadir planning/review.
- No tocar deploy real con Caddy.
- No depender de Claude real ni de GitHub real en make smoke.

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

Trabaja en el repo `Takeo7/niwa`, rama `main`. Implementa únicamente Fase 0 — Smoke automatizado y confianza en v1.1.

Contexto: Convertir el smoke manual de v1.1 en un comando reproducible que valide el flujo E2E sin credenciales reales.

Primero lee `docs/SPEC.md`, `docs/HANDBOOK.md`, `docs/STATE.md`, este documento y los archivos directamente afectados por la tarea. Mantén el PR pequeño, añade tests y no adelantes fases posteriores.

Entrega esperada por cada tarea:

- cambios de código/documentación necesarios;
- tests añadidos o actualizados;
- comandos ejecutados y resultado;
- limitaciones o desviaciones explícitas;
- instrucciones de smoke/manual check si aplica.

## Bloques de PR recomendados

- **PR-SMOKE-01.** Smoke fake básico: sandbox aislado, bootstrap, backend readiness, fixture repo, project create, execute/verify/finalize.
- **PR-SMOKE-02.** Split, waiting_input/resume, attachments, deploy estático, fake gh para PR/merge.
- **PR-SMOKE-03.** CI smoke en GitHub Actions y reportes .smoke/report.md + .json.
- **PR-SMOKE-04.** smoke-live opcional con Claude Code y GitHub CLI reales.

## Tareas

### SMOKE-00 — Definir contrato de smoke v1.1

**Objetivo.** Fijar qué significa que v1.1 está operativo.

**Archivos probables.**

- `docs/plans/SMOKE-v1.1.md`

**Instrucciones de implementación.**

- Crear docs/plans/SMOKE-v1.1.md con alcance exacto, checks, criterios de fallo y no-objetivos.
- Declarar que make smoke debe ser determinista, sin red externa y sin credenciales.
- Definir que el smoke debe ejecutarse en un HOME temporal para no tocar ~/.niwa real.

**Tests/verificación.**

- No aplica; documentación.

**Criterios de aceptación.**

- Documento aprobado y referenciado por el script smoke.
- El scope queda cerrado: executor/API/finalize/deploy actual, no features nuevas.

**Brief corto para LLM.**

```text
Implementa SMOKE-00 (Definir contrato de smoke v1.1) en Niwa. Objetivo: Fijar qué significa que v1.1 está operativo. Toca principalmente `docs/plans/SMOKE-v1.1.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: No aplica; documentación.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-01 — Añadir scripts/smoke_v1_1.py

**Objetivo.** Crear el harness principal que orquesta el smoke de punta a punta.

**Archivos probables.**

- `scripts/smoke_v1_1.py`
- `Makefile`

**Instrucciones de implementación.**

- Crear un TemporaryDirectory o .smoke/sandbox y usarlo como HOME aislado.
- Ejecutar ./bootstrap.sh con NIWA_BOOTSTRAP_SKIP_LINGER=1.
- Arrancar uvicorn en puerto libre y esperar /api/readiness.
- Crear funciones helper para requests HTTP, comandos shell, assertions y escritura de reportes.
- Capturar logs por check en .smoke/logs/.

**Tests/verificación.**

- python -m py_compile scripts/smoke_v1_1.py
- make smoke en máquina limpia con Python/Node/git.

**Criterios de aceptación.**

- make smoke ejecuta el harness y falla con exit code 1 si un check falla.
- El script no modifica ~/.niwa del usuario real.
- Cada fallo imprime check, comando/request y path del log.

**Brief corto para LLM.**

```text
Implementa SMOKE-01 (Añadir scripts/smoke_v1_1.py) en Niwa. Objetivo: Crear el harness principal que orquesta el smoke de punta a punta. Toca principalmente `scripts/smoke_v1_1.py`, `Makefile`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: python -m py_compile scripts/smoke_v1_1.py; make smoke en máquina limpia con Python/Node/git.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-02 — Crear fixture repo local

**Objetivo.** Generar un repo git mínimo para probar todas las rutas.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Crear README.md, .gitignore, dist/index.html y dist/assets/app.js.
- Inicializar git con rama main y commit inicial.
- Ignorar .niwa/ en el fixture para que attachments no ensucien el working tree.
- Añadir helper para crear también un bare remote local cuando se pruebe PR/merge.

**Tests/verificación.**

- Assertion de git status limpio.
- curl a deploy estático tras crear proyecto.

**Criterios de aceptación.**

- El fixture queda con git status limpio antes de crear proyecto.
- El endpoint /api/deploy/{slug}/ puede servir dist/index.html.

**Brief corto para LLM.**

```text
Implementa SMOKE-02 (Crear fixture repo local) en Niwa. Objetivo: Generar un repo git mínimo para probar todas las rutas. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Assertion de git status limpio.; curl a deploy estático tras crear proyecto.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-03 — Registrar proyecto vía API

**Objetivo.** Validar el contrato ProjectCreate sin UI.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- POST /api/projects con slug smoke-web, kind web-deployable, local_path del fixture y autonomy_mode safe.
- Guardar project read en report.json.
- Validar GET/list si existe endpoint disponible.

**Tests/verificación.**

- Smoke assertion HTTP 201/200 según contrato.

**Criterios de aceptación.**

- Proyecto creado con slug smoke-web.
- La respuesta contiene local_path, kind y autonomy_mode esperados.

**Brief corto para LLM.**

```text
Implementa SMOKE-03 (Registrar proyecto vía API) en Niwa. Objetivo: Validar el contrato ProjectCreate sin UI. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Smoke assertion HTTP 201/200 según contrato.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-04 — Smoke execute/verify/finalize

**Objetivo.** Comprobar que una tarea simple llega a done con commit local.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Crear tarea con POST /api/projects/{slug}/tasks.
- Ejecutar python -m app.executor --once con NIWA_CLAUDE_CLI apuntando al fake.
- Usar FAKE_CLAUDE_TOUCH para crear un archivo dentro del fixture.
- Validar TaskRead status=done, Run outcome=verified y commit niwa:* en git log.

**Tests/verificación.**

- make smoke check execute.

**Criterios de aceptación.**

- Task final done.
- Run completed/verified.
- Hay commit en rama niwa/task-*.
- No quedan cambios no confirmados salvo lo esperado por el smoke.

**Brief corto para LLM.**

```text
Implementa SMOKE-04 (Smoke execute/verify/finalize) en Niwa. Objetivo: Comprobar que una tarea simple llega a done con commit local. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke check execute.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-05 — Smoke split y promoción de padre

**Objetivo.** Validar triaje split y semántica parent/subtasks.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Crear tarea compleja.
- Forzar FAKE_CLAUDE_TRIAGE_JSON con decision split y dos subtareas.
- Ejecutar executor --once las veces necesarias hasta drenar subtareas.
- Validar que el padre pasa a estado terminal y que las subtareas existen.

**Tests/verificación.**

- make smoke check split.

**Criterios de aceptación.**

- Padre con parent_task_id null queda done cuando hijos terminan done.
- Hay exactamente las subtareas esperadas o al menos dos subtareas hijas con títulos esperados.

**Brief corto para LLM.**

```text
Implementa SMOKE-05 (Smoke split y promoción de padre) en Niwa. Objetivo: Validar triaje split y semántica parent/subtasks. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke check split.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-06 — Smoke waiting_input y resume

**Objetivo.** Validar aclaración humana y reanudación.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Fake Claude emite una pregunta abierta y session_id.
- Validar task status waiting_input y pending_question.
- Responder con POST /api/tasks/{id}/respond.
- Reejecutar executor con fake success y session_id compatible.
- Validar dos runs: uno needs_input y otro verified.

**Tests/verificación.**

- make smoke check waiting_input.

**Criterios de aceptación.**

- Primer run necesita input.
- La respuesta reencola la tarea.
- Segundo run completa done.

**Brief corto para LLM.**

```text
Implementa SMOKE-06 (Smoke waiting_input y resume) en Niwa. Objetivo: Validar aclaración humana y reanudación. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke check waiting_input.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-07 — Smoke attachments

**Objetivo.** Validar endpoints y gating de adjuntos.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Crear tarea queued.
- Subir archivo con POST /api/tasks/{id}/attachments.
- Listar attachments y validar filename/content_type.
- Ejecutar tarea con fake success.
- Intentar subir otro adjunto tras inicio/completado y esperar 409 si aplica.

**Tests/verificación.**

- make smoke check attachments.

**Criterios de aceptación.**

- Attachment aparece antes de ejecutar.
- La tarea con adjunto termina done.
- Los adjuntos quedan congelados tras inicio.

**Brief corto para LLM.**

```text
Implementa SMOKE-07 (Smoke attachments) en Niwa. Objetivo: Validar endpoints y gating de adjuntos. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke check attachments.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-08 — Smoke deploy estático actual

**Objetivo.** Validar el handler existente de dist/.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Pedir GET /api/deploy/smoke-web/.
- Pedir GET /api/deploy/smoke-web/assets/app.js.
- No añadir Caddy, puertos por proyecto ni build runner en esta fase.

**Tests/verificación.**

- make smoke check static deploy.

**Criterios de aceptación.**

- HTML y JS devuelven 200 y contenido esperado.
- Si falla, el reporte distingue missing_dist, missing_index o HTTP error.

**Brief corto para LLM.**

```text
Implementa SMOKE-08 (Smoke deploy estático actual) en Niwa. Objetivo: Validar el handler existente de dist/. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke check static deploy.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-09 — Fake gh CLI y PR/merge local

**Objetivo.** Validar finalize/pulls/merge sin GitHub real.

**Archivos probables.**

- `scripts/fake_gh_cli.py`
- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Añadir scripts/fake_gh_cli.py compatible con gh pr create, gh pr list y gh pr merge.
- Prepend del directorio scripts/fakes al PATH durante smoke.
- Usar un remote bare local para que git push funcione sin red.
- El fake gh debe persistir PRs en un JSON temporal para que list/merge sean consistentes.

**Tests/verificación.**

- python -m py_compile scripts/fake_gh_cli.py
- make smoke check fake PR.

**Criterios de aceptación.**

- Task con git_remote local produce pr_url.
- GET /api/projects/{slug}/pulls devuelve el PR fake.
- POST merge devuelve merged true o equivalente según contrato.

**Brief corto para LLM.**

```text
Implementa SMOKE-09 (Fake gh CLI y PR/merge local) en Niwa. Objetivo: Validar finalize/pulls/merge sin GitHub real. Toca principalmente `scripts/fake_gh_cli.py`, `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: python -m py_compile scripts/fake_gh_cli.py; make smoke check fake PR.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-10 — Reportes .smoke/report.md y .json

**Objetivo.** Hacer que el resultado sea legible por humanos y máquinas.

**Archivos probables.**

- `scripts/smoke_v1_1.py`

**Instrucciones de implementación.**

- Crear report.md con tabla PASS/FAIL, duración, paths de logs y entorno.
- Crear report.json con checks, timestamps, command, stdout/stderr truncados y artifacts.
- Incluir versiones python/node/git si están disponibles.

**Tests/verificación.**

- make smoke y forzar fallo controlado para comprobar reporte.

**Criterios de aceptación.**

- Al terminar make smoke siempre queda report.md/json.
- En fallo parcial también se escribe reporte.

**Brief corto para LLM.**

```text
Implementa SMOKE-10 (Reportes .smoke/report.md y .json) en Niwa. Objetivo: Hacer que el resultado sea legible por humanos y máquinas. Toca principalmente `scripts/smoke_v1_1.py`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make smoke y forzar fallo controlado para comprobar reporte.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-11 — Añadir make smoke

**Objetivo.** Exponer el smoke como entrada canónica.

**Archivos probables.**

- `Makefile`
- `README.md`
- `docs/HANDBOOK.md`

**Instrucciones de implementación.**

- Añadir target .PHONY smoke en Makefile.
- No modificar targets existentes de forma destructiva.
- Documentar en README o docs/HANDBOOK cómo ejecutarlo.

**Tests/verificación.**

- make test
- make smoke.

**Criterios de aceptación.**

- make smoke funciona desde raíz del repo.
- make test sigue funcionando.

**Brief corto para LLM.**

```text
Implementa SMOKE-11 (Añadir make smoke) en Niwa. Objetivo: Exponer el smoke como entrada canónica. Toca principalmente `Makefile`, `README.md`, `docs/HANDBOOK.md`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: make test; make smoke.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-12 — Añadir CI smoke

**Objetivo.** Ejecutar smoke determinista en push/PR.

**Archivos probables.**

- `.github/workflows/smoke.yml`

**Instrucciones de implementación.**

- Crear .github/workflows/smoke.yml.
- Usar Python 3.11 y Node 22.
- Ejecutar make smoke.
- Subir .smoke/report.md/json/logs como artifact en caso de fallo.

**Tests/verificación.**

- CI verde en PR.

**Criterios de aceptación.**

- El workflow corre sin secretos.
- Falla si cualquier check de smoke falla.

**Brief corto para LLM.**

```text
Implementa SMOKE-12 (Añadir CI smoke) en Niwa. Objetivo: Ejecutar smoke determinista en push/PR. Toca principalmente `.github/workflows/smoke.yml`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: CI verde en PR.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
```

### SMOKE-13 — Añadir make smoke-live opcional

**Objetivo.** Validar Claude Code y GitHub reales sin obligarlos en CI.

**Archivos probables.**

- `scripts/smoke_v1_1.py`
- `Makefile`

**Instrucciones de implementación.**

- Crear modo --live que no usa fake Claude ni fake gh.
- Comprobar claude en PATH, gh auth status y consentimiento explícito para crear repo privado temporal.
- Permitir --no-merge por defecto y --merge opcional.

**Tests/verificación.**

- Prueba manual en máquina con Claude/GitHub.

**Criterios de aceptación.**

- make smoke-live falla temprano si faltan credenciales.
- Nunca se ejecuta en CI sin opt-in.
- Crea y limpia recursos temporales cuando sea posible.

**No hacer.**

- No mezclar live con smoke determinista.

**Brief corto para LLM.**

```text
Implementa SMOKE-13 (Añadir make smoke-live opcional) en Niwa. Objetivo: Validar Claude Code y GitHub reales sin obligarlos en CI. Toca principalmente `scripts/smoke_v1_1.py`, `Makefile`. Sigue las instrucciones del documento de fase, no adelantes otras fases y valida con: Prueba manual en máquina con Claude/GitHub.. Devuelve resumen de cambios, tests ejecutados y cualquier limitación.
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