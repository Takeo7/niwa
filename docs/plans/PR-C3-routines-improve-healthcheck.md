# PR-C3 — Migration for `improvement_type` + `product_healthcheck` seed routine

**Hito:** C
**Esfuerzo:** M
**Depende de:** ninguna
**Bloquea a:** PR-C4 (`_exec_improve()` + `improvement_type` selector en UI)

## Qué

1. Migration **016** (no 015; 015 ya ocupado por `autonomy_mode`):
   - Añade columna `improvement_type TEXT` a `routines` (nullable).
   - Añade columna `consecutive_failures INTEGER NOT NULL DEFAULT 0`
     a `deployments` (para trackear strikes entre ticks).
2. Actualiza `schema.sql` para fresh installs:
   - CHECK constraint de `routines.action` incluye `'improve'`.
   - Columnas nuevas reflejadas en el `CREATE TABLE`.
3. Valida `'improve'` en la capa HTTP (endpoints que crean/modifican
   routines) y en `_execute_routine()` (bifurcación stub → 501 /
   placeholder hasta PR-C4).
4. Añade routine seed `product_healthcheck` a `BUILTIN_ROUTINES`:
   - `schedule="*/10 * * * *"`, `action="script"`, `enabled=True`.
   - Script Python inline: recorre `deployments WHERE status='active'`,
     `urllib.request.urlopen` con timeout 5 s, 2xx/3xx = ok (reset
     counter a 0), otro = fail (incrementa `consecutive_failures`).
     Cuando `consecutive_failures == 3`, crea task hija de fix
     (`parent_task_id=NULL`, `area='sistema'`, `priority='alta'`,
     `source='routine:product_healthcheck'`, `project_id=<deployment.project_id>`)
     y congela el counter (no vuelve a crear task hasta que se
     vuelva a resetear, i.e. hasta que el deployment responda 2xx/3xx
     de nuevo).

## Por qué

Happy path MVP §1.6: "salud + mejora continua sobre los productos
desplegados". Sin este PR, la columna `improvement_type` no existe,
`'improve'` no pasa por el CHECK, y nada vigila los deployments. PR-C4
(los 3 templates de improve) queda bloqueado hasta tener este schema.

## Scope — archivos que toca

- `niwa-app/db/migrations/016_routines_improve.sql` (nuevo): 2 ALTER.
- `niwa-app/db/schema.sql`:
  - `routines`: añadir `improvement_type TEXT`, actualizar CHECK de
    `action` (incluir `'improve'`).
  - `deployments`: añadir `consecutive_failures INTEGER NOT NULL
    DEFAULT 0`.
- `niwa-app/backend/scheduler.py`:
  - `BUILTIN_ROUTINES`: añadir `product_healthcheck` (script inline).
  - `_execute_routine()`: rama `elif action == "improve":` que
    devuelve `"[error] improve action not implemented yet (PR-C4)"`
    y marca `success=False`. Mantiene el CHECK operativo sin romper
    routines existentes.
- `niwa-app/backend/app.py`:
  - Endpoint(s) de routines que aceptan `action` (POST/PATCH
    `/api/routines*`): validar contra `{'create_task','script',
    'webhook','improve'}` y opcionalmente validar
    `improvement_type ∈ {'functional','stability','security'}` cuando
    `action == 'improve'`.
- `tests/test_routines_improve_check.py` (nuevo, ver "Tests" abajo).

## Fuera de scope (explícito)

- **No** implementa `_exec_improve()` ni los 3 prompts templated
  (`functional` / `stability` / `security`). Eso es **PR-C4**.
- **No** toca el selector UI `improvement_type` en
  `RoutinesPanel.tsx`. PR-C4.
- **No** recrea la tabla `routines` para aplicar el CHECK nuevo en
  instalaciones existentes (patrón establecido en PR-B3: el CHECK
  vive en `schema.sql` para fresh installs; el enforcement para DBs
  migradas vive en la capa HTTP/Python). Si se decide lo contrario,
  sale a PR aparte.
- **No** añade webhooks de notificación al routine
  `product_healthcheck`. El routine deja rastro vía
  `routines.last_status`/`last_error` y creando la task de fix.
- **No** cambia el comportamiento de ninguna otra routine seed.

## Tests

- **Nuevos:** `tests/test_routines_improve_check.py` con casos:
  1. **Migration aplica limpio** sobre una DB con `schema.sql` pre-016
     (simulada): columnas `improvement_type` y
     `deployments.consecutive_failures` existen tras apply.
  2. **Schema fresh install**: `CREATE TABLE routines` tras cargar
     `schema.sql` acepta `INSERT` con `action='improve'` y rechaza
     `action='foobar'`.
  3. **HTTP layer**: `POST /api/routines` con `action='improve'` y
     `improvement_type='stability'` responde 200/201; con
     `action='improve'` sin `improvement_type` o con valor inválido
     responde 400.
  4. **`product_healthcheck` builtin**: tras `seed_builtin_routines`,
     existe un row con `id='product_healthcheck'`, `enabled=1`,
     `schedule='*/10 * * * *'`, `action='script'`.
  5. **Strike logic** (unit test del script inline — extraído a una
     función puro-Python testable si hace falta, o ejecutando el
     script contra una DB temp): con 1 deployment inalcanzable, tras
     3 ejecuciones del script `consecutive_failures == 3` y existe
     exactamente **una** task con `source='routine:product_healthcheck'`;
     una 4ª ejecución **no** duplica la task.
  6. **Reset logic**: si tras 2 fallos el deployment vuelve a
     responder 2xx, `consecutive_failures` vuelve a 0 sin crear task.
- **Existentes que deben seguir verdes:**
  - `tests/test_smoke.py` (usa `routines`).
  - `tests/test_oauth_scheduler_refresh.py` (toca `scheduler.py`).
  - `tests/test_deployments_endpoints.py`.
  - `tests/test_task_autodeploy_on_success.py`.
- **Baseline esperada tras el PR:** `≥1033 pass / ≤60 failed / ≤104
  errors` (el baseline declarado en CLAUDE.md; los nuevos tests
  suman al pass count).

## Criterio de hecho

- [ ] `python3 -m pytest -q tests/test_routines_improve_check.py`
      verde.
- [ ] `python3 -m pytest -q` no regresa tests que estaban verdes en
      el baseline (pass no baja respecto a 1033).
- [ ] En una DB fresca (`schema.sql`), `INSERT INTO routines
      (... action, ...) VALUES (... 'improve', ...)` no lanza
      `CHECK constraint failed`.
- [ ] En una DB migrada desde pre-016, tras aplicar 016 las columnas
      `routines.improvement_type` y `deployments.consecutive_failures`
      existen con los defaults correctos.
- [ ] `curl -X POST /api/routines` con `action='improve',
      improvement_type='stability'` responde 2xx.
- [ ] `curl -X POST /api/routines` con `action='improve',
      improvement_type='foo'` responde 400 (o 422) con mensaje claro.
- [ ] Tras arrancar el backend en una instalación limpia,
      `SELECT id FROM routines WHERE id='product_healthcheck'`
      devuelve 1 fila.
- [ ] Review Codex resuelto (o "LGTM").

## Riesgos conocidos

- **DBs migradas con CHECK viejo.** Un `INSERT` con `action='improve'`
  desde SQL directo fallará contra el CHECK antiguo. **Mitigación:**
  la única ruta soportada para crear routines nuevas es la API HTTP,
  que valida + persiste. El stub en `_execute_routine()` protege si
  alguien introduce `'improve'` por otra vía. Lo documentamos en el
  PR body como limitación conocida, resuelto la próxima vez que se
  necesite recrear la tabla (migration aparte, fuera de este PR).
- **Creación duplicada de tasks de fix.** Si un deployment está KO
  durante horas, el routine podría generar múltiples tasks. **Mitigación:**
  "congelar" el counter en `3` en vez de seguir incrementando; el
  INSERT de la task va condicionado a `consecutive_failures == 3`
  (exactamente, no `>= 3`). Se vuelve a emitir solo tras un reset
  (2xx) + 3 fallos consecutivos nuevos.
- **Race condition script vs. scheduler.** El script inline lee y
  escribe `deployments.consecutive_failures` directamente. El
  scheduler tick es secuencial (un routine a la vez), así que no hay
  race con otros routines. Sí puede haberla con `deploy_project()`
  si redeploya mientras el script corre; impacto mínimo — el contador
  se resetea en la siguiente iteración.
- **HTTP timeout bajo carga.** `urlopen(url, timeout=5)` puede marcar
  falsos positivos si el host está lento. **Mitigación:** el umbral
  de 3 strikes (30 min de ventana con cron `*/10`) absorbe parpadeos.
  No reducir el timeout por debajo de 5 s.
- **Migration orden.** 016 depende de que 015 (`autonomy_mode`) esté
  aplicada. El runner de migrations lee ficheros en orden numérico,
  así que el orden `015 → 016` está garantizado.

## Notas para Claude Code

- El roadmap original decía "migración 015"; ese número se consumió
  en PR-B3. Uso **016** y lo noto en el body del PR.
- El CHECK de `action` **no se actualiza** en la tabla `routines`
  preexistente (SQLite no soporta ALTER CHECK). Se enforcea en capa
  HTTP + `_execute_routine()`. Es el mismo patrón de PR-B3
  documentado en `015_autonomy_mode.sql`. Si al implementar aparece
  un test que espera CHECK en la tabla viva, **paro y pregunto**.
- Verificar antes de codear:
  1. La validación de `action` en endpoints de routines existe hoy o
     es parte de este PR (grep `action` en `app.py` routines).
  2. `deployments.project_id` es TEXT (coincide con `tasks.project_id`).
  3. `source` en `tasks` acepta strings libres (no CHECK constraint
     que limite valores).
- Si alguno de (1)/(2)/(3) contradice el brief: paro y replanteo.
- Commits pequeños, mensaje imperativo en inglés:
  - `test: failing cases for routines improve + product healthcheck`
  - `feat(db): migration 016 improvement_type + deployment strikes`
  - `feat(scheduler): product_healthcheck seed routine`
  - `feat(api): validate action=improve + improvement_type`
- Antes de pedir review: `python3 -m pytest -q` completo, pegar diff
  de pass/fail/error respecto al baseline en el PR description.
