# PR-00 — Fix collection-time errors en 3 tests

**Hito:** 0
**Esfuerzo:** S
**Depende de:** ninguna
**Bloquea a:** todo el MVP-ROADMAP (los PRs siguientes necesitan
baseline verde para medir regresiones)

## Qué

Los 3 ficheros de test siguientes fallan durante setup con
`SystemExit: FATAL: migration 005_services_and_settings_unify.sql
failed: no such table: main.settings`, generando **104 errores** en el
baseline. Hay que arreglar la causa raíz (fixture o init_db) para que
estos ficheros ejecuten.

- `tests/test_capability_profile_endpoints.py` (21 errors)
- `tests/test_chat_sessions_v02_endpoint.py` (5 errors)
- `tests/test_run_events_contract.py` (14 errors)

## Por qué

Sin baseline verde no podemos medir regresiones en los 16 PRs
siguientes. Es precondición dura del workflow (ver
`docs/MVP-ROADMAP.md §2 paso 3` y `§4 Hito 0`).

## Contexto — causa raíz probable

Cuando la fixture monta una DB fresca en `tempfile` y llama a
`app.init_db()`, `_run_migrations` (niwa-app/backend/app.py:912-969)
aplica las migraciones en orden. La migración 005
(`niwa-app/db/migrations/005_services_and_settings_unify.sql:6`)
ejecuta:

```sql
CREATE INDEX IF NOT EXISTS idx_settings_key ON settings(key);
```

La tabla `settings` **solo está definida en `schema.sql:172`**, NO en
migraciones 001-004. Hipótesis: `init_db` aplica migraciones antes (o
sin) aplicar `schema.sql`, o `schema.sql` no se está aplicando en el
flujo de la fixture por alguna condición (p.ej. DB ya inicializada por
otro test, import caching de `app` con DB_PATH estale).

Evidencia: en ejecución aislada (`pytest <fichero>.py`) los 3
ficheros reproducen el fallo, por lo que **no es contaminación
cruzada entre tests** — es defecto propio de init_db o de las
fixtures cuando empiezan con DB completamente vacía.

## Scope — archivos que toca

- `niwa-app/backend/app.py` (probable fix en `init_db` o
  `_run_migrations`: garantizar que `schema.sql` se aplica antes de
  migraciones cuando la DB está vacía, o que `settings` existe antes
  de migración 005).
- O, alternativamente, `niwa-app/db/migrations/005_*.sql` (añadir
  `CREATE TABLE IF NOT EXISTS settings (...)` antes del `CREATE
  INDEX`, reproduciendo el schema de `schema.sql:172`).
- Posiblemente un `tests/conftest.py` nuevo si el fix es a nivel
  fixture (pero preferible no — arregla la causa raíz, no el síntoma).

## Fuera de scope (explícito)

- No reescribir `init_db`.
- No tocar otras migraciones (001-004, 006+).
- No modificar los 3 ficheros de test salvo que su fixture esté
  objetivamente rota.
- No añadir tests nuevos — este PR resucita tests existentes.

## Tests

- **Nuevos:** ninguno.
- **Que deben pasar tras el PR:** los 40 tests de los 3 ficheros
  listados arriba.
- **Baseline esperada tras el PR:** `≥1060 pass / ≤75 errors`
  (recuperar ≥29 tests; los 11 restantes pueden seguir en `failed`
  por motivos no relacionados con collection).

## Criterio de hecho

- [ ] `pytest tests/test_capability_profile_endpoints.py
  tests/test_chat_sessions_v02_endpoint.py
  tests/test_run_events_contract.py -q` termina sin errores de
  collection/setup.
- [ ] `pytest -q` completo en root muestra `errors` ≤ 75.
- [ ] `pytest -q` completo no regresa ningún test que hoy esté en
  `pass` (verificable comparando listado de tests pass entre HEAD y
  el nuevo commit).
- [ ] Rama `claude/pr-00-fix-collection-errors` con commits pequeños
  y PR abierto apuntando a este brief.

## Riesgos conocidos

- **Falso fix en migration 005**: añadir `CREATE TABLE IF NOT
  EXISTS settings` en la migración crea drift con `schema.sql`
  (doble definición). Si optas por esta ruta, asegúrate de que
  ambos definen exactamente los mismos columns/constraints. Mejor
  ruta: fix en `init_db` para aplicar `schema.sql` primero.
- **Impacto en fresh install real**: el bug podría estar afectando
  también a instaladores que arrancan con DB vacía y ejecutan
  migraciones antes de schema. Verifica que tu fix funciona tanto
  en test fixtures como en `setup.py install --quick`.
- **Los 11 tests sobrantes**: los 40 tests-in-3-files menos los 29
  que probablemente se recuperan. Es posible que algunos tengan
  fallos reales no relacionados con la collection. Si aparecen, NO
  los arregles en este PR — repórtalos como hallazgos en el PR
  description para abrir un `FIX-` aparte.

## Notas para Claude Code

- Reproduce primero: `python3 -m pytest
  tests/test_capability_profile_endpoints.py --tb=short` para
  confirmar el error antes de tocar nada.
- Lee `niwa-app/backend/app.py` alrededor de `init_db`,
  `_run_migrations`, `_apply_sql_idempotent` para entender el orden
  real.
- Preferencia: fix en `init_db` (una fuente de verdad para el
  schema). Fallback: fix en migración 005 solo si el fix anterior
  es desproporcionado.
- Esfuerzo S — puedes saltarte la invocación del codex-reviewer,
  pero corre `pytest` completo antes de abrir el PR.
