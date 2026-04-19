# PR-C4 — `_exec_improve()` + `improvement_type` selector en RoutinesPanel

**Hito:** C
**Esfuerzo:** M
**Depende de:** PR-C3 (merged en #89)
**Bloquea a:** ninguno

## Qué

Cerrar el camino de la routine `action='improve'` que PR-C3 dejó
stub-eada. Dos piezas:

1. **Backend — `_exec_improve()` en `scheduler.py`.** Dada una
   routine con `action='improve'`, `improvement_type ∈
   {'functional','stability','security'}` y `action_config.project_id`,
   resuelve el proyecto, renderiza el template de prompt
   correspondiente con el contexto del proyecto (nombre +
   `directory`) y **crea una task** con ese prompt como
   `description`. La task queda `status='pendiente'`, `area='sistema'`,
   `source='routine:improve:<type>'`, `project_id=<resolved>`. La
   ejecución LLM la hace el executor normal al recoger la task — el
   scheduler NO invoca `NIWA_LLM_COMMAND_PLANNER` directamente. Se
   wirea en `_execute_routine`: la rama `elif action == "improve"`
   deja de devolver el stub `[error] ... not implemented yet
   (PR-C4)` y llama a `_exec_improve(config, improvement_type,
   db_conn_fn)`.
2. **Frontend — selector en `RoutinesPanel.tsx`.** El modal de
   crear/editar routine gana 3 controles nuevos, visibles solo
   cuando `action='improve'`:
   - `Select` de `action` con opciones `script | improve` (default
     `script` — backward-compat con routines existentes).
   - `Select` de `improvement_type` con `functional | stability |
     security`.
   - `Select` de proyecto (usa `useProjects()`), persistido en
     `action_config.project_id`.
   La card de routine muestra un `Badge` pequeño con el
   `improvement_type` cuando está presente.

## Por qué

Happy path MVP §1.6 ("salud + mejora continua sobre los productos
desplegados") y criterio del Hito C: "una rutina `improve:stability`
manual añade un test al proyecto". PR-C3 metió el schema y el stub
`501`; sin este PR una routine `improve` enabled **siempre** falla
visible (`[error] improve action not implemented yet (PR-C4)`) y no
hay UI para crearla.

## Scope — archivos que toca

- `niwa-app/backend/scheduler.py`:
  - Constante `_IMPROVE_PROMPT_TEMPLATES: dict[str, str]` con los 3
    strings del roadmap §4 Hito C (literales, no reglas dinámicas).
  - Función `_exec_improve(config: dict, improvement_type: str,
    db_conn_fn: Callable) -> tuple[str, bool]` que retorna
    `(message, success)`. Errores (no `project_id`, proyecto no
    existe, `improvement_type` no válido) → `success=False`,
    mensaje claro con prefijo `[error]`.
  - En `_execute_routine`, sustituir el stub `elif action ==
    "improve":` por la llamada real, respetando el manejo de
    `result`/`success` para que el update de `routines.last_status`
    / `last_error` funcione igual que las otras ramas.
- `niwa-app/frontend/src/shared/types/index.ts`:
  - `Routine` gana `action?: 'script'|'improve'|'create_task'|'webhook'`
    y `improvement_type?: 'functional'|'stability'|'security'|null`.
- `niwa-app/frontend/src/features/system/components/RoutinesPanel.tsx`:
  - Estado local `action`, `improvementType`, `projectId` en el
    editor modal.
  - 3 controles Mantine `Select` condicionales descritos arriba.
  - `handleSave` construye el payload con `action`,
    `improvement_type`, y `action_config: {project_id}` cuando
    `action==='improve'`. Para `action==='script'` mantiene el
    shape actual (`{script: command}`).
  - La card renderiza `Badge` con el `improvement_type` si existe.
- `tests/test_routines_exec_improve.py` (nuevo): ver sección Tests.

## Fuera de scope (explícito)

- **No** invoca `NIWA_LLM_COMMAND_PLANNER` ni ningún LLM desde el
  scheduler. El LLM corre cuando el executor recoge la task. Si se
  necesita ejecución inmediata, sale a PR aparte.
- **No** cambia `task-executor.py`. Las tasks creadas por
  `improve` usan la ruta estándar.
- **No** soporta `improve` multi-proyecto por routine. Una
  routine = un `project_id`. Si un usuario quiere 3 proyectos,
  crea 3 routines.
- **No** toca `product_healthcheck` ni otras routines seed.
- **No** añade routines seed `improve:*`. El usuario las crea
  manualmente desde la UI.
- **No** añade `cwd` al proyecto ni valida que el `directory`
  exista. El executor ya lo hace (PR-B2).
- **No** añade endpoints nuevos. Reusa `POST/PATCH /api/routines`
  con la validación de PR-C3.
- **No** refactoriza `RoutinesPanel.tsx` (ej. extraer el modal a
  su propio componente), aunque sea tentador. Cambio quirúrgico.
- **No** toca la UI de `ProjectDetail` ni muestra las routines
  improve desde el proyecto. Se ven desde SystemView.

## Tests

- **Nuevos:** `tests/test_routines_exec_improve.py`:
  1. **`_exec_improve` sin `project_id`** en `config` →
     `(message.startswith('[error]'), False)`; mensaje menciona
     `project_id`.
  2. **`_exec_improve` con `project_id` inexistente** →
     `(message.startswith('[error]'), False)`; mensaje menciona el id.
  3. **`_exec_improve` con `improvement_type` inválido** →
     `ValueError` (defensivo; la validación HTTP ya lo bloquea, pero
     el callsite interno también debe fallar fuerte).
  4. **Happy path `functional`**: fixture con project (id, name,
     directory). Llamar `_exec_improve({'project_id': pid},
     'functional', conn_fn)` → success=True, mensaje con
     `Task created:`, en DB existe 1 row en `tasks` con
     `source='routine:improve:functional'`, `project_id=pid`,
     `area='sistema'`, `status='pendiente'`, `description` contiene
     el nombre del proyecto y el directorio, y contiene la frase
     clave del template (`"functional improvement"`).
  5. **Happy path `stability`**: igual, con frase clave
     (`"pytest/vitest"` o `"stability"`).
  6. **Happy path `security`**: igual, con frase clave
     (`"pip-audit"` o `"npm audit"`).
  7. **Integración con `_execute_routine`**: crear routine con
     `action='improve'`, `improvement_type='stability'`,
     `action_config={'project_id': pid}`, `enabled=1`. Llamar
     `scheduler._execute_routine(routine_dict)` → tras la llamada,
     `routines.last_status == 'ok'`, existe exactamente 1 task con
     `source='routine:improve:stability'`.
  8. **Error persistido**: `_execute_routine` con `improve` +
     `project_id` inexistente → `routines.last_status == 'error'`,
     `last_error` no vacío, ninguna task creada.
- **Existentes que deben seguir verdes:**
  - `tests/test_routines_improve_check.py` (PR-C3, HTTP layer + CHECK).
  - `tests/test_routines_*` otros si existen.
  - `tests/test_smoke.py`.
  - `tests/test_oauth_scheduler_refresh.py` (scheduler shared path).
- **Baseline esperada tras el PR:** `pass ≥ 1033 + ~8 nuevos` (los
  del test_routines_exec_improve.py). Sin regresión de `pass`
  existentes. `errors`/`failed` no aumentan.

## Criterio de hecho

- [ ] `python3 -m pytest -q tests/test_routines_exec_improve.py`
      verde.
- [ ] `python3 -m pytest -q` no regresa tests que estaban verdes en
      el baseline (≥1033 pass).
- [ ] Una routine `action='improve'`, `improvement_type='stability'`,
      `action_config={'project_id': '<id real>'}` disparada vía
      `POST /api/routines/<id>/run` crea una task `pendiente` con
      `source='routine:improve:stability'`.
- [ ] Routine con `action='improve'` y `project_id` inexistente deja
      `routines.last_status='error'` y no crea task.
- [ ] Modal de crear routine en la UI:
      a) Selector `action` cambia entre `script | improve`.
      b) Al elegir `improve`, aparecen los selectores de
         `improvement_type` y `project_id`.
      c) El botón Guardar queda disabled si `improvement_type` o
         `project_id` están vacíos cuando `action='improve'`.
      d) Tras crear, la card muestra el badge `improvement_type`.
- [ ] `vite build` del frontend compila sin errores de tipos.
- [ ] Review Codex resuelto (o "LGTM").

## Riesgos conocidos

- **Prompt templates en el código vs. DB.** Los templates viven
  como constante Python. Si en el futuro queremos per-tenant
  templates, hay que moverlos a DB — fuera de scope. Riesgo:
  ninguno inmediato.
- **Proyecto borrado tras crear la routine.** La FK
  `tasks.project_id REFERENCES projects(id) ON DELETE SET NULL`
  no protege al `_exec_improve`: si el `project_id` en
  `action_config` apunta a un proyecto ya borrado, el routine
  fallará (caso de test 2). **Mitigación:** mensaje claro,
  `last_error` persistido, el usuario lo ve en SystemView.
- **Overlap con `idle-project-review`.** Esa routine seed ya crea
  "improvement tasks" genéricas. No colisiona: usa
  `action='create_task'` y `source='routine'`. PR-C4 usa
  `action='improve'` y `source='routine:improve:<type>'`.
- **Selector UI sin validación fuerte en el cliente.** Si el usuario
  manda `action='improve'` sin `improvement_type`, el 400 del
  backend (PR-C3) es el que lo bloquea. **Mitigación:** botón
  Guardar disabled + `notifications.show({color:'red'})` en el
  catch. No se añade lib extra de validación (mantener convención
  del panel actual).
- **Tipos de `Routine` en TS.** Si alguna otra vista consume
  `Routine` y espera `action` ausente, al añadir el campo opcional
  no rompe nada (opcional). Verificar grep antes.
- **Task creada con `description` largo.** Los templates son
  relativamente cortos (<2 KB), pero conviene truncar a 4 KB para
  no asustar al planner. **Decisión:** no truncar en este PR. Si
  surge, PR aparte.

## Notas para Claude Code

- **No** toques `task-executor.py`. La task creada se procesa con
  la ruta normal.
- **No** añadas dependencias nuevas (ni Python ni npm).
- **Templates literales** del roadmap §4 Hito C — cópialos tal cual
  (no los reescribas "mejor"). Rellena solo `{project_name}` y
  `{project_directory}` con `str.format`. Si hace falta
  escapar `{` en el template que no es placeholder, duplícalo
  (`{{ }}`).
- Commits pequeños, mensaje imperativo en inglés:
  - `test: failing cases for _exec_improve and routine wiring`
  - `feat(scheduler): _exec_improve creates task per improvement_type`
  - `feat(ui): improvement_type + project selector in RoutinesPanel`
  - `chore(types): add action + improvement_type to Routine`
- Antes de abrir PR:
  - `python3 -m pytest -q` completo, pegar diff vs baseline.
  - Invocar `codex-reviewer` sobre `git diff origin/v0.2...HEAD`.
- Si descubres que el scope excede 400 LOC, **para y replantea**.
