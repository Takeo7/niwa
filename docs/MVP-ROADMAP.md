# Niwa — MVP Roadmap

**Fecha:** 2026-04-18
**Estado actual:** post-PR-73. v0.2 pipeline funciona end-to-end en producción
(UI → tarea → executor → routing → adapter → ficheros creados → resultado
visible). Baseline pytest: **1033 pass / 60 failed / 104 errors / 87 subtests
pass** en 228s. Faltan piezas para cerrar el happy path **declarado**.
**Reemplaza** a `docs/archive/HAPPY-PATH-ROADMAP-2026-04-16.md`.

---

## 1. Happy path objetivo (v1 MVP)

Recorrido nominal que el MVP debe cerrar **extremo a extremo**:

1. **Instalación sin fricción.** `./niwa install --quick --mode core --yes`
   en máquina limpia — incluyendo Docker si falta — termina mostrando
   credenciales admin al usuario.
2. **Transparencia de modelos.** El usuario (no-técnico) ve en la UI qué
   modelo/backend ejecuta cada parte, qué falta para estar listo, y puede
   configurarlo sin editar ficheros.
3. **Auth prioriza suscripciones.** Claude Pro/Max (setup-token) y ChatGPT
   Plus/Pro (OAuth PKCE) son los caminos por defecto. API key queda como
   fallback visible pero relegado.
4. **Tarea → ejecución autónoma.** El usuario crea una tarea para un
   proyecto nuevo o existente. Niwa la triaja, la desgrana si procede,
   ejecuta sin pedir interacción (dangerous mode por defecto en MVP),
   escribe código/docs/nuevos proyectos, y revisa el resultado.
5. **Cierre del ciclo.** Al completar, Niwa despliega al subdominio
   configurado — o a `localhost:port/<slug>/` si no hay DNS — sin que el
   usuario toque nada.
6. **Salud + mejora continua.** Niwa hace health-checks periódicos sobre
   los productos desplegados (no solo sobre sí mismo) y expone rutinas de
   auto-mejora seleccionables por tipo (`functional | stability |
   security`).

**Fuera del MVP:** Gemini/Google OAuth, multi-tenant/multi-instancia,
planner tier que decompone a N niveles, auto-merge, rollback automático de
deploys, mejora de dependencias major.

---

## 2. Workflow por PR

**Regla de oro:** cada PR ≤ 400 LOC, una cosa, mergeable sola, `pytest -q`
sin regresiones respecto al baseline declarado.

Bucle de 6 pasos por PR:

1. **Plan (Claude genera, humano aprueba).** Claude Code escribe
   `docs/plans/PR-NN-<slug>.md` siguiendo `docs/plans/_TEMPLATE.md`. **No
   toca código todavía.** El humano lo lee en ≤2 min y responde "ok" o
   "cambia X". Aprobado = lock de scope; lo que no esté ahí va a otro PR.
   Obligatorio para PRs ≥ M; en PRs S puede comprimirse en el mensaje de
   commit.
2. **Scaffold de tests primero** (cuando aplique). Para lógica no-trivial:
   test rojo → commit `test: failing cases for X` → confirmar que falla
   por el motivo esperado.
3. **Implementación.** Commits pequeños, mensaje imperativo. Hasta que los
   tests de (2) pasen y los 1033 anteriores sigan verdes.
4. **Self-review + revisión Codex.** Antes de pedir revisión humana:
   - `pytest -q` completo; pegar en el PR el diff vs baseline (nº pass/fail/error).
   - Invocar agente `codex-reviewer` sobre el diff. Pegar sus comentarios
     marcados como "🤖 Codex review".
5. **Iteración sobre feedback.** Responder a cada comment (aceptar+fix o
   rechazar con motivo). No mergear hasta: tests verdes + review humano +
   review Codex resuelto.
6. **Merge + post-mortem de 3 líneas** en `DECISIONS-LOG.md` solo si hubo
   decisión no trivial.

### Rol de Codex como reviewer

Existe `niwa-app/backend/backend_adapters/codex.py` — usable vía
subagente dedicado. Crea `.claude/agents/codex-reviewer.md`:

- **Descripción:** revisor crítico de diffs en Python/TypeScript.
- **Prompt de sistema:** "Eres un revisor crítico. Recibes un diff y los
  ficheros tocados. Comentas SÓLO problemas reales, no estilo. Formato:
  `archivo:línea — problema — severidad (blocker|major|minor)`. Si no
  hay nada, dices 'LGTM'. No propones features nuevas."
- **Cuándo invocarlo:** siempre en PRs L, opcional en M, skip en S.
- **Cuándo NO hacerle caso:** "añade más validación", "añade logs sin
  causa", "considera refactorizar" — ruido. Blockers reales: null
  pointer, SQL injection, pérdida de datos, estado inconsistente,
  regresión de tests.

---

## 3. Qué NO hacer

- No dos PRs abiertos a la vez en la misma rama.
- No refactors "aprovechando que estoy por aquí". Si Claude los propone,
  sacarlos a PR aparte.
- No mergear con `pytest` en rojo respecto al baseline. Si un fallo es
  "del propio PR y esperado", el brief lo tenía que declarar.
- No confiar en "LGTM" de Codex para lógica de negocio; él ve código, no
  intención.
- No usar auto-merge hasta 3 PRs mergeados con el loop completo.
- No borrar approval gates sin reemplazarlos por el flag
  `autonomy_mode=dangerous` explícito (PR-B3).

---

## 4. Hitos y PRs

### Hito 0 — Baseline verde (precondición)

Sin esto, los PRs siguientes no pueden confirmar "no regresé nada".

| PR | Título | Esfuerzo | Depende |
|----|--------|----------|---------|
| **PR-00** | Fix collection-errors en `test_capability_profile_endpoints.py`, `test_chat_sessions_v02_endpoint.py`, `test_run_events_contract.py`. Probable import común roto. | **S** | — |

**Criterio de hecho:** baseline sube a `≥1060 pass / ≤75 errors`; los 3
ficheros colectan y ejecutan.

---

### Hito A — Onboarding sin fricción (7 PRs)

| PR | Título | Esfuerzo | Depende | Archivos principales |
|----|--------|----------|---------|----------------------|
| **PR-A1** | Mostrar credenciales admin en el summary del installer (username + password generado). | S | — | `setup.py:3564-3578,3780-3808` |
| **PR-A2** | Step 0 del installer: detectar falta de Docker, ofrecer `get.docker.com` (Linux) / Homebrew (macOS) con confirmación explícita. | S | — | `setup.py:3483-3491` + `niwa` wrapper |
| **PR-A3** | Retirar naming `{instance}` de systemd/env/update. Instancia única. | S-M | — | `setup.py:3541-3549`, `bin/update_engine.py` |
| **PR-A4** | Reordenar precedencia de credenciales: suscripción > sesión CLI > API key, en Claude y Codex. Tests con fixtures de los 3 casos. | S | — | `setup.py:3298-3388`, `bin/task-executor.py:925-934` |
| **PR-A5** | Endpoint `GET /api/readiness` + widget "Qué falta" en `SystemView`. Devuelve `{docker_ok, db_ok, admin_ok, backends:[{slug, has_credential, auth_mode, model_present, reachable}], hosting_ok}`. | M | PR-A4 | `niwa-app/backend/app.py`, `health_service.py`, `frontend/src/features/system/components/SystemView.tsx` |
| **PR-A6** | AuthPanel React "suscripción-first" para Claude (pegar setup-token + status "autenticado vía suscripción"). Portar lo que hoy vive en `frontend/static/app.js` (legacy). | M | PR-A5 | `frontend/src/features/system/components/AuthPanel.tsx` (nuevo) |
| **PR-A7** | OAuth OpenAI end-to-end: endpoints `/api/auth/openai/start|callback`, persistencia en `oauth_tokens`, refresher en scheduler (margen 5 min), integración en AuthPanel. Reaprovecha `niwa-app/backend/oauth.py` (ya al 40%). | M | PR-A5, PR-A6 | `oauth.py`, `app.py`, `scheduler.py`, `AuthPanel.tsx`, `backend_adapters/codex.py` |

**Criterio de hito A:** un usuario nuevo instala, ve su password en
pantalla, pega su setup-token de Claude Pro, y `/api/readiness` devuelve
todo verde — sin haber tocado ninguna API key.

---

### Hito B — Ejecución autónoma fiable (4 PRs)

| PR | Título | Esfuerzo | Depende | Archivos principales |
|----|--------|----------|---------|----------------------|
| **PR-B1** | Fix Bug 32 regresión (2026-04-18): heurística "último mensaje tras todos los tool_use termina en pregunta sin tool_use posterior" → `waiting_input`. Tests regresión con fixture "1 tool_use + pregunta". | S-M | — | `backend_adapters/claude_code.py:880-1110`, `tests/test_claude_adapter_clarification.py` |
| **PR-B2** | Fix Bug 34: forzar `cwd=project_directory` en Popen + validación post-run. Si artefactos fuera del path → `waiting_input` con mensaje claro. | M | — | `bin/task-executor.py:349-385,899-1000` |
| **PR-B3** | Flag `autonomy_mode=dangerous` por proyecto. Desactiva approval_gate cuando está on. Banner rojo en `ProjectDetail.tsx` "modo autónomo activo". Por defecto off; doc que explica el riesgo. | S-M | — | `capability_service.py`, `approval_service.py`, `ProjectDetail.tsx` |
| **PR-B4** | Planner tier. Si tarea tiene flag `decompose=true` o `description` > N chars, invocar `NIWA_LLM_COMMAND_PLANNER` para crear hijas con `parent_task_id`. Scheduler consume hijas antes que padre. UI agrupa. | **L** | PR-B1, PR-B2 | `bin/task-executor.py:187`, `scheduler.py`, `tasks_service.py`, nueva vista `TaskTreeView.tsx` |

**Criterio de hito B:** tarea "crea un hello world en Python con tests"
con `autonomy_mode=dangerous` y `decompose=true` genera 3 hijas, las
ejecuta sin intervención, y el padre termina `hecha` con artefactos
dentro del `project_directory`.

---

### Hito C — Cierre del ciclo producto (4 PRs)

| PR | Título | Esfuerzo | Depende | Archivos principales |
|----|--------|----------|---------|----------------------|
| **PR-C1** | Hook `on_task_completed → deploy_project()` cuando `status → hecha` y tarea tiene `project_id` y flag `deploy_on_success=true` (default true en v1). Mostrar URL resultante en `TaskDetailsTab`. | S-M | PR-B2 | `tasks_service.py` (trigger), `hosting.py:91-139`, `TaskDetailsTab.tsx` |
| **PR-C2** | Guardado de dominio desde `HostingDomainWizard` (ya existe) hasta Caddyfile + reload. Asume Cloudflare proxy (no ACME). Validar DNS + HTTP + wildcard antes de aceptar. | S-M | — | `hosting.py:345-376`, `HostingDomainWizard.tsx` (ya hecho el UI), endpoints `/api/hosting/domain*` |
| **PR-C3** | Migración **015**: añadir `improvement_type` a `routines` y actualizar CHECK constraint de `action` para incluir `'improve'`. Routine seed `product_healthcheck` cron `*/10 * * * *` que itera `deployments`, GET HTTP, 3 strikes → tarea hija de fix. | M | — | `niwa-app/db/migrations/015_routines_improve.sql` (nuevo), `schema.sql:127-144`, `scheduler.py:313-336,395-407,575-620` |
| **PR-C4** | Implementar `_exec_improve()` en scheduler con 3 prompts templated (`functional`, `stability`, `security`). Selector `improvement_type` en `RoutinesPanel.tsx`. | M | PR-C3 | `scheduler.py`, `RoutinesPanel.tsx:1-259` |

**Prompts base para PR-C4** (derivados de la rutina `daily-improvement`
en `scheduler.py:582-588`):

- `functional`: "Review recent commits + README of project X. Propose and
  implement ONE small functional improvement (max 15 min). No API
  breaking changes. Output: commit + child task 'review'."
- `stability`: "Run pytest/vitest for project X. If failing → create
  child task 'fix <test>'. If green → run ruff/eslint --fix + typecheck.
  No major dep upgrades."
- `security`: "Run pip-audit / npm audit --audit-level=high for project
  X. Create one child task per high|critical vuln. No major dep
  upgrades."

**Criterio de hito C:** tras cerrar tarea (hito B), el producto queda
accesible en una URL real, se health-checkea cada 10 min, y una rutina
`improve:stability` manual añade un test al proyecto.

---

### Hito D — Smoke extremo a extremo (1 PR)

| PR | Título | Esfuerzo | Depende | Archivos |
|----|--------|----------|---------|----------|
| **PR-D1** | `tests/test_e2e_happy_path_completo.py`: install fixture → admin creds → setup-token Claude mock → crear tarea "hello world" en proyecto nuevo → decompose → ejecutar sin approval → auto-deploy → healthcheck → rutina `improve:stability` añade test. Integrar en CI. | M | Todos | `tests/test_e2e_happy_path_completo.py`, `.github/workflows/*` |

**Criterio de hito D:** CI verde, smoke completo corre en ≤5 min con
adapters fakeados.

---

## 5. Totales

- **16 PRs** organizados en 5 hitos.
- **Esfuerzo estimado:** ~19–25 días-persona.
- **Distribución:** 4×S, 7×S-M, 4×M, 1×L.
- Claude Code con supervisión activa: ~3 PR-S o 1-2 PR-M por día.

---

## 6. Cómo proceder (orden concreto)

1. **Hoy:**
   - Crear `.claude/agents/codex-reviewer.md` (sección 2).
   - `docs/plans/_TEMPLATE.md` ya listo (este commit).
2. **PR-00 primero.** Precondición absoluta. Si no pasa rápido,
   descubriremos un problema estructural antes de todo lo demás.
3. **En paralelo tras PR-00:** PR-A1 y PR-A4 (ambos S, independientes).
   Sirven para calibrar el loop con tareas pequeñas antes de L's.
4. **Después siguen el orden del plan.** PR-A3 y PR-B1 se paralelizan
   (áreas distintas).
5. **Antes de PR-A7 o PR-B4 (los L's / M grandes):** una sesión entera
   de plan aprobado por el humano antes de empezar a codear.
6. **Cada 3-4 PRs mergeados, smoke E2E manual** (`./niwa install
   --quick` en VM/container limpio). No esperar a PR-D1 para detectar
   regresiones no unitarias.

**Orden recomendado para una persona sola:**
PR-00 → PR-A1 → PR-A4 → PR-B1 → PR-A2 → PR-B2 → PR-A5 → PR-A6 → PR-A7
→ PR-C1 → PR-C2 → PR-B3 → PR-A3 → PR-C3 → PR-C4 → PR-B4 → PR-D1.

---

## 7. Referencias cruzadas

- Arquitectura: `docs/ARCHITECTURE.md`
- Spec v0.2 congelada: `docs/SPEC-v0.2.md`
- State machines: `docs/state-machines.md`
- Plan de auth por suscripción (detalle técnico): `docs/PLAN-AUTH-SUBSCRIPTION.md`
- Bugs vivos: `docs/BUGS-FOUND.md` (Bug 32, Bug 34, Bug 33 abiertos relevantes)
- Release runbook: `docs/RELEASE-RUNBOOK.md`
- Decisiones históricas: `docs/DECISIONS-LOG.md`
- ADRs: `docs/adr/0001-niwa-yume-separation.md`, `docs/adr/0002-v02-architecture.md`
- Briefs de PR (uno por PR): `docs/plans/PR-NN-<slug>.md`
- Docs archivados (históricos): `docs/archive/`
