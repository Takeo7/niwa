# Niwa v1 — MVP

**Objetivo:** un motor que ejecuta tareas autónomas de código sobre
proyectos reales, útil de día 1 para el autor y su pareja.
**Plazo duro:** 6 semanas hasta usable en producción propia.
**No-objetivo:** ser producto open-source genérico, soportar N usuarios,
cubrir todos los stacks.

---

## 1. Qué hace

El usuario tiene proyectos (repos git existentes o nuevos). Abre Niwa,
escribe una tarea en lenguaje natural sobre un proyecto, y Niwa:

1. **Triaje.** Decide si la tarea se ejecuta directa o se descompone en
   subtareas. Sin LLM de más: una sola llamada, decisión binaria.
2. **Ejecución.** Crea rama `niwa/<task-slug>` en el repo del proyecto,
   lanza Claude Code CLI sobre el directorio local, stream-json, sin
   aprobaciones intermedias.
3. **Verificación.** Antes de marcar hecho, comprueba evidencia:
   artefactos dentro del cwd, exit code 0, tests del proyecto pasando si
   existen, no quedó una pregunta sin responder al final del stream.
4. **Cierre.** Commit + push de la rama. Abre PR automático si el repo
   tiene remote GitHub. Si `project.kind = web-deployable` y
   `autonomy_mode = dangerous`, mergea el PR y despliega.

La UI permite al usuario ver el progreso en vivo, responder si Niwa
hace una pregunta (clarification round-trip), y revisar el PR antes de
mergear en modo `safe`.

## 2. Qué NO hace

- No chat conversacional. Crear tarea = modal, no conversación.
- No multi-provider. Claude Code CLI único. Nada de OpenAI/Gemini/
  Ollama/Groq/Mistral/DeepSeek.
- No auth. Binding local (`127.0.0.1`). Acceso por red = out of scope.
- No multi-usuario, multi-instance, multi-tenant.
- No kanban, notes, metrics, dashboard, history views, approvals
  configurables, capability profiles, routing rules, scheduler de
  rutinas, image generation, web search, theme picker.
- No installer wizard. Bootstrap script personal, dos máquinas
  conocidas (autor + pareja).
- No configuración vía UI. `~/.niwa/config.toml` se edita a mano.
- No MCP en el MVP. Se añade como capa posterior cuando el motor
  funcione E2E y haya caso de uso real.
- No subdominios wildcard en el MVP. Deploy a `localhost:PORT/<slug>`.
  Cloudflare/Caddy se añade en v1.1 cuando sea necesario.

## 3. Modelo de datos (5 tablas)

```
projects
  id, slug (unique), name, kind (web-deployable|library|script),
  git_remote (nullable), local_path, deploy_port (nullable),
  autonomy_mode (safe|dangerous, default safe),
  created_at, updated_at

tasks
  id, project_id (fk), parent_task_id (nullable, fk),
  title, description,
  status (inbox|queued|running|waiting_input|done|failed|cancelled),
  branch_name (nullable), pr_url (nullable),
  pending_question (nullable),   -- texto si waiting_input
  created_at, updated_at, completed_at (nullable)

task_events
  id, task_id (fk),
  kind (created|status_changed|message|verification|error),
  message, payload_json, created_at

runs
  id, task_id (fk),
  status (queued|running|completed|failed|cancelled),
  model, started_at, finished_at (nullable),
  exit_code (nullable), outcome (nullable),
  session_handle (nullable),     -- para resume
  artifact_root,                 -- path absoluto del cwd del run
  verification_json (nullable),  -- snapshot de evidencias
  created_at

run_events
  id, run_id (fk), event_type, payload_json, created_at
```

Estados canónicos, sin ambigüedad. `inbox` solo si el usuario la creó
pero no la ha lanzado (botón de "ejecutar" manual). `queued` en cuanto
se envía al executor. `waiting_input` cuando el adapter devuelve
pregunta; se resuelve con `POST /api/tasks/:id/respond` que dispara un
resume del run.

## 4. Pipeline por tarea (4 pasos, en orden)

```
[triage]    → decide: execute|split     (1 LLM call)
[execute]   → Claude Code CLI sobre local_path, rama niwa/<slug>
[verify]    → evidence-based completion (ver §5)
[finalize]  → commit+push, PR, deploy condicional según project.kind
```

Sin approvals como tabla. El PR mismo es el gate:
- `autonomy_mode = safe` → Niwa abre PR, el humano mergea.
- `autonomy_mode = dangerous` → Niwa abre PR, auto-mergea si verify OK.

## 5. Contrato de verificación (evidence-based)

Un run se marca `completed` solo si **todas** se cumplen:

1. Exit code del CLI == 0.
2. El stream terminó con un mensaje de cierre (no con una tool_use sin
   respuesta ni con una pregunta abierta).
3. Al menos un artefacto (file creado/modificado) dentro de
   `artifact_root`. Si el adapter escribió fuera del cwd → `failed`
   con `error_code=artifacts_outside_cwd`.
4. Si `project.kind in (library, web-deployable)` y existe script de
   tests (`package.json` con `test`, `pyproject.toml` con `pytest`, o
   `Makefile` con `test`), se ejecuta y debe pasar.

Si falla cualquiera → `run.status = failed` con detalle en
`verification_json`. Nada de "hecho sin output" silencioso.

## 6. Stack

- **Backend:** FastAPI + SQLAlchemy 2 + Alembic + Pydantic v2.
- **DB:** SQLite (WAL).
- **Frontend:** React 19 + Vite + Mantine v7 + TanStack Query.
- **Executor:** Python daemon, systemd user unit. Polling 5s.
- **Adapter:** wrapper sobre `claude` CLI, stream-json parseado,
  portado y simplificado desde `niwa-app/backend/backend_adapters/
  claude_code.py`.
- **Bootstrap:** `v1/bootstrap.sh` — instala deps, crea `~/.niwa/`,
  migra DB, instala systemd unit. Sin wizard interactivo.
- **Tests:** pytest (backend) + vitest (frontend). Integración con
  Claude Code mockeado vía fake-CLI fixture (portado de v0.2).

## 7. UI (4 rutas, sin tabs sobrantes)

- `/` — Lista de proyectos, card con nombre + kind + estado + link a
  su página.
- `/projects/:slug` — Detalle proyecto: árbol de archivos read-only,
  lista de tareas (todos los estados, ordenadas por fecha), URL local
  de deploy si aplica, botón "Nueva tarea" → modal.
- `/projects/:slug/tasks/:id` — Detalle tarea: descripción, estado,
  rama, PR, stream en vivo del run activo, timeline de eventos,
  formulario para responder si `waiting_input`.
- `/system` — Readiness: DB OK, Claude CLI instalado + autenticado
  (via `claude whoami` o similar), systemd unit corriendo, disk free.
  Read-only.

## 8. Fuera del MVP (roadmap v1.1+)

En este orden, solo si el MVP se usa de verdad:

1. MCP server exponiendo `task_create`, `task_status`, `task_respond`
   (si hay caso de uso real).
2. Deploy con Caddy + subdominios wildcard.
3. Verificación extendida: lint, typecheck, build.
4. Planner 2-tier (subtareas dependientes).
5. OpenClaw como canal adicional para crear tareas por Telegram.

## 9. Hitos

- **Semana 1:** esqueleto FastAPI + React + DB + CRUD proyectos/tareas.
  Endpoint `POST /tasks` escribe, el executor lee pero hace echo.
- **Semana 2:** adapter Claude Code real, ejecución en rama nueva,
  stream de eventos hasta UI.
- **Semana 3:** contrato de verificación completo. Triaje planner.
  Modo safe (PR manual).
- **Semana 4:** autoverify con tests del proyecto, modo dangerous con
  auto-merge, bootstrap.sh reproducible.
- **Semana 5:** deploy local + página de readiness + clarification
  round-trip en UI. Instalación en la máquina de la pareja.
- **Semana 6:** bugfix de lo que aparezca en uso real. Jubilar v0.2.

## 10. Criterio de éxito

El autor y su pareja usan Niwa v1 para al menos una tarea real a la
semana, sin abrir el código de Niwa para arreglar Niwa. Si al final
de la semana 6 cualquiera de los dos se siente forzado a abrir un
editor para tocar Niwa durante su flujo normal de trabajo, el MVP ha
fallado y se repiensa antes de añadir features.
