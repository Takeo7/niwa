# PR-D1 — E2E smoke del happy path completo

**Hito:** D
**Esfuerzo:** M
**Depende de:** PR-00, PR-A1…A7, PR-B1…B4b, PR-C1…C4 (todos merged).
**Bloquea a:** ninguno (cierra roadmap MVP).

## Qué

Un único test de integración, `tests/test_e2e_happy_path_completo.py`,
que encadena en un solo proceso las piezas ya mergeadas del happy path
MVP y falla ruidosamente si alguna regresa. Fases, en orden:

1. **Install-state fixture.** `fresh_niwa` (nuevo, en el propio test o
   `tests/conftest.py`) crea `tmp_path/niwa-home`, aplica `schema.sql`
   + todas las migraciones con `_apply_sql_idempotent` (copiado del
   patrón de `tests/test_installer_bootstrap_db.py:44-56`), setea
   env `NIWA_HOME`, `NIWA_DB_PATH`, `NIWA_PROJECTS_ROOT`, y siembra
   un usuario admin vía `INSERT INTO users` con hash mock. **No**
   invoca `setup.py` (demasiado lento y fuera de scope — ver
   "Fuera de scope").
2. **Setup-token Claude mock.** Siembra una fila `oauth_tokens`
   `provider='claude_subscription'` con access_token placeholder, y
   setea `NIWA_LLM_COMMAND_CLAUDE=python3 tests/fixtures/fake_claude.py`.
   Es el equivalente de test al flujo "usuario pega setup-token"
   — lo que importa aguas abajo es que el adapter tenga un comando
   que ejecutar y un token que inyectar.
3. **Crear tarea con `decompose=1` en un proyecto nuevo con
   `autonomy_mode='dangerous'`.** Vía `tasks_service.create_task`
   directo (no HTTP). El proyecto se siembra con INSERT
   `projects(autonomy_mode='dangerous')` para bypass de approvals
   (ver `capability_service.py:416`).
4. **Ejecutar planner tier.** Invoca en-proceso las funciones
   `_should_run_planner`, `_parse_planner_output`, `_create_subtasks`
   de `bin/task-executor.py` (ya cargado vía `importlib`,
   patrón idéntico a `tests/test_e2e_auto_project_happy_path.py:66-72`),
   con un `NIWA_LLM_COMMAND_PLANNER` apuntando a un nuevo
   `tests/fixtures/fake_planner.py` que emite un bloque
   `<SUBTASKS>` con 3 hijas. Asserta 3 rows nuevas con
   `parent_task_id = <parent_id>`.
5. **Ejecutar hijas sin approval.** Para cada hija:
   `tasks_service.update_task(id, {'status':'hecha'})` simulando
   que el executor + fake_claude las acabó. El test **no** corre el
   loop completo de `task-executor.py` — sería 1-2 minutos y frágil.
   Lo que asserta es que el gate de approvals no las bloqueó y que
   al marcar la última hija `hecha`, `close_parent_if_children_done`
   cierra al padre (PR-B4b) y dispara `_maybe_autodeploy`
   (`tasks_service.py:253-259`).
6. **Auto-deploy.** Monkeypatch `hosting.deploy_project` a un spy que
   registra la llamada y devuelve un dict sintético. Asserta que se
   llamó con el `project_id` del padre (patrón idéntico a
   `tests/test_task_autodeploy_on_success.py:98-126`). Inserta a mano
   la fila en `deployments` con `url='http://stub/'` y `status='active'`
   para las fases 7-8.
7. **Healthcheck.** Llama `scheduler.check_deployments_health(
   db_conn_fn, opener=fake_opener)` tres veces seguidas, donde
   `fake_opener` levanta `URLError` siempre. Tras la tercera
   invocación asserta que existe 1 task con
   `source='routine:product_healthcheck'` y que `deployments.consecutive_failures==3`.
8. **Rutina `improve:stability`.** Llama
   `scheduler._exec_improve({'project_id': pid}, 'stability', db_conn_fn)`
   directo. Asserta `(message, success) == (..., True)` y que
   existe 1 task `pendiente` con `source='routine:improve:stability'`.

**CI integration.** Nueva job `e2e-happy-path` en
`.github/workflows/mcp-smoke.yml` (o workflow nuevo
`.github/workflows/e2e-smoke.yml` — **decisión pendiente**, ver
"Trade-offs"). La job corre `python3 -m pytest -q
tests/test_e2e_happy_path_completo.py -v` en Ubuntu latest, sin
Docker, sin nada externo. Timeout 10 min.

## Por qué

Criterio del Hito D: "CI verde, smoke completo corre en ≤5 min con
adapters fakeados." Sin este test, cualquier regresión en la
secuencia decompose → autonomous exec → auto-deploy → healthcheck
→ improve pasa sin detectarse hasta un smoke manual. Los tests
unitarios de cada fase existen pero no cubren el orden ni los
side-effects transversales (ej.: un `_maybe_autodeploy` que ignora
`autonomy_mode` rompería B3 sin romper C1).

## Scope — archivos que toca

- **Nuevo:** `tests/test_e2e_happy_path_completo.py` (~280-350 LOC).
  Contiene: fixture local `fresh_niwa` (o importada de conftest),
  fixtures `patched_hosting`, `fake_opener`, y 1 test monolítico
  `test_happy_path_completo` con 8 fases separadas por
  `# --- Phase N: ... ---` + subasserts. No uso un test por fase
  porque el estado del anterior es precondición del siguiente
  (montar 8 fixtures encadenadas vs. 1 test con pasos es más
  legible y más rápido).
- **Nuevo:** `tests/fixtures/fake_planner.py` (~40 LOC). CLI mock que
  lee prompt de stdin, emite `<SUBTASKS>[{"title":"Write hello.py"},
  {"title":"Write test_hello.py"},{"title":"Run tests"}]</SUBTASKS>`
  por stdout, exit 0. Sigue el patrón y shebang de
  `tests/fixtures/fake_claude.py:1-89`.
- **Nuevo:** `.github/workflows/e2e-smoke.yml` (~40 LOC). Workflow
  nuevo — **NO** se toca `mcp-smoke.yml` (Docker-based, scope
  diferente, no quiero acoplar fallos). Instala Python 3.12,
  corre `pytest` sobre el nuevo fichero, sube JUnit XML como
  artefacto. Trigger: push/PR a `v0.2`.

**Estimación LOC total:** ≈360-430. Si paso de 400 paro y
divido — probable ruta de división: mover la fixture a
`tests/conftest.py` o dividir en "infra" (fake_planner.py + CI
workflow + fresh_niwa fixture) + "test" en 2 PRs.

## Fuera de scope (explícito)

- **No** ejecuta `setup.py` ni `./niwa install`. Eso es un test de
  installer aparte; PR-D1 prueba la lógica post-install.
- **No** arranca el servidor Flask ni va por HTTP (`app.test_client`).
  Todas las llamadas son a `tasks_service` / `scheduler` / `hosting`
  directos. Motivo: el contrato que necesitamos sellar es la
  secuencia de operaciones sobre la DB + hooks, no los endpoints
  (ya cubiertos por sus tests dedicados).
- **No** corre el loop `while True` de `bin/task-executor.py`.
  Demasiado frágil y no determinista (polling, scheduling). Se
  invocan en-proceso las funciones puntuales que interesan.
- **No** verifica el contenido del artifact que el fake Claude
  escribe ni lo valida con `collect_artifacts`. Eso ya lo cubre
  `tests/test_claude_adapter_integration.py`.
- **No** exercises OAuth OpenAI (PR-A7) — el happy path MVP está
  redactado sobre Claude suscripción.
- **No** toca ni renombra tests existentes. Ningún `e2e_*` anterior
  se fusiona con este.
- **No** sube la baseline de `pass` desde el brief (tests del PR
  añaden 1 pass — el test principal —; no toco tests ya verdes).
- **No** introduce markers pytest nuevos (`@pytest.mark.e2e`). Si
  aparecen en el futuro se añaden en PR propio.
- **No** añade dependencias (Python ni npm).
- **No** cambia `hosting.py`, `scheduler.py`, `tasks_service.py`,
  `capability_service.py`, `task-executor.py`. Solo se monkeypatch-ean.
  **Excepción admitida:** si al correr el test descubro un bug real
  (ej.: `_maybe_autodeploy` no bypassea autonomy_mode), PARO y
  abro issue separado. No fix en este PR.
- **No** toca `docs/MVP-ROADMAP.md` ni otros docs (fuera del brief).

## Tests

- **Nuevos:**
  - `tests/test_e2e_happy_path_completo.py::test_happy_path_completo`
    (1 test, 8 fases). Cada fase con sus propios asserts; si una
    falla, pytest corta y las siguientes no corren (no necesito
    sub-tests independientes porque la fase N+1 depende de N).
  - `tests/fixtures/fake_planner.py` — no es test, es fixture
    ejecutable. Sin pytest.
- **Existentes que deben seguir verdes:**
  - `tests/test_e2e_auto_project_happy_path.py` (patrón fuente).
  - `tests/test_task_autodeploy_on_success.py` (patrón hosting spy).
  - `tests/test_routines_improve_check.py` (healthcheck).
  - `tests/test_routines_exec_improve.py` (improve templates).
  - `tests/test_pr62_release_e2e.py` (release smoke).
  - `tests/test_smoke.py`, `tests/test_mcp_smoke.py`.
- **Baseline esperada tras el PR:** `pass ≥ 1034` (baseline +1 del
  test nuevo). `errors`/`failed` no aumentan. Sin regresiones.
  Duración del test individual: esperado ≤ 10s en local, ≤ 30s en
  CI (dentro del budget de 5 min del Hito D con margen amplio).

## Criterio de hecho

- [ ] `python3 -m pytest -q tests/test_e2e_happy_path_completo.py`
      verde en local, ≤ 10s.
- [ ] `python3 -m pytest -q` global no regresa ningún test verde
      del baseline 1033.
- [ ] El test cubre las 8 fases declaradas arriba con al menos un
      assert observable por fase (grep `assert ` en el test da
      ≥ 8).
- [ ] `tests/fixtures/fake_planner.py` es ejecutable
      (`chmod +x`) y, alimentado con stdin arbitrario, emite JSON
      válido en `<SUBTASKS>...</SUBTASKS>`.
- [ ] `.github/workflows/e2e-smoke.yml` existe; el workflow corre
      solo el fichero nuevo; sube JUnit XML; timeout ≤ 10 min.
- [ ] CI pasa en el PR (verificar tras abrir).
- [ ] Review Codex resuelto.

## Riesgos conocidos

- **Acoplamiento al monolito `task-executor.py`.** Cargar el módulo
  vía `importlib.util.spec_from_file_location` funciona hoy
  (`test_e2e_auto_project_happy_path.py` lo hace), pero si el
  módulo adquiere side-effects en el import (abrir DBs, arrancar
  schedulers), el test pete en collection. **Mitigación:** uso el
  mismo patrón y orden que el test existente; si algo cambió,
  paro. No intento reescribir la carga.
- **Fallo silencioso de `_maybe_autodeploy`.** El hook traga
  excepciones (`tasks_service.py:272-296`) para no revertir la
  transición. Si mi spy recibe kwargs inesperados y peta, no se
  detecta. **Mitigación:** el spy verifica `project_id` como
  positional y asserta explícitamente que fue llamado 1 vez.
- **Orden no determinista de `check_deployments_health`.** La
  función itera sobre rows de SQLite. Con 1 deployment no hay
  problema, pero si algún fixture previo deja otro deployment
  flotando, el assert de 1 task healthcheck falla. **Mitigación:**
  fresh DB por test; verificar `SELECT COUNT(*) FROM deployments`
  == 1 antes de la fase 7.
- **Scope de "install fixture".** El roadmap dice literalmente
  "install fixture". Lo interpreto como "estado post-install",
  no como "ejecutar setup.py". **Si el usuario quiere install
  real**, el PR se reescribe para subprocessear setup.py en un
  tmpdir y se parte en 2 — aviso en el preámbulo y espero ok.
- **Flakiness de importlib en CI.** `bin/task-executor.py` importa
  módulos relativos vía `sys.path`. El fixture mete `bin/` y
  `niwa-app/backend/` en `sys.path` igual que el E2E existente.
  Si Python 3.12 del runner se comporta distinto, el test falla
  en CI pero no en local. **Mitigación:** workflow usa
  `actions/setup-python@v5` con `python-version: '3.12'`, igual
  que el entorno local.
- **Baseline real del repo.** CLAUDE.md dice 1033 pass. No lo he
  re-verificado en esta sesión — si el baseline vivo es otro tras
  los merges más recientes, ajusto en el PR description.

## Trade-offs reales (elijo en el brief, no en código)

1. **Un test vs. varios.** Elegido: **uno** con fases. Cada fase
   depende de la DB de la anterior; separar en tests implica
   serializar fixtures o duplicar bootstrap. Contras: un fallo
   oculta los siguientes. Mitigación: `# --- Phase N ---`
   comments + nombres de variables fase-específicos para que el
   trace apunte al step concreto.
2. **HTTP vs. service-layer.** Elegido: **service-layer**.
   Fidelidad menor pero estabilidad mucho mayor y alineado con el
   test existente. Contras: un bug de serialización de API no se
   detecta. Fuera de scope del Hito D (ya hay tests HTTP por
   endpoint).
3. **Workflow nuevo vs. job en `mcp-smoke.yml`.** Elegido:
   **workflow nuevo** (`e2e-smoke.yml`). Contras: duplica algo de
   boilerplate (checkout, setup-python). Pros: no acopla un fallo
   pytest al smoke MCP, run times independientes, más fácil de
   desactivar si surge flakiness.
4. **Planner fake en fichero separado vs. extender `fake_claude.py`.**
   Elegido: **fichero separado** (`fake_planner.py`). Contras: 40
   LOC de overhead. Pros: el planner emite `<SUBTASKS>` y el
   adapter Claude no — mezclar los dos comportamientos en un
   único script se vuelve condicional sobre args y se enmarra.
5. **Mock setup-token vs. OAuth real.** Elegido: **solo inyectar
   token en `oauth_tokens` + env**. Contras: no prueba el
   endpoint de guardar setup-token. Pros: scope realista —
   `oauth_tokens` upsert ya tiene su propio test.

## Notas para Claude Code

- **Abandona a la primera señal de scope creep.** Si al implementar
  detectas que hace falta tocar producción (hosting.py,
  scheduler.py, etc.) para que el test pase, **para** y revisa el
  brief. Probablemente encontraste un bug real — sale a otro PR.
- **Reutiliza, no reinventes.** La fixture de
  `test_e2e_auto_project_happy_path.py:42-72` es la plantilla.
  El spy de `test_task_autodeploy_on_success.py:98-126` es la
  plantilla. El fake_claude.py es la plantilla del fake_planner.
- **Commits pequeños, mensaje imperativo en inglés:**
  - `test: scaffold fresh_niwa fixture and phase skeletons`
  - `test: add fake_planner fixture for subtasks emission`
  - `test: wire decompose + autonomous exec + auto-deploy phases`
  - `test: wire healthcheck + improve:stability phases`
  - `ci: add e2e-smoke workflow running full happy path test`
- **Antes de abrir PR:**
  - `python3 -m pytest -q` completo. Pegar diff pass/fail/error vs
    baseline en el PR body.
  - Invocar `codex-reviewer` sobre `git diff origin/v0.2...HEAD`.
    Pegar resultado como `🤖 Codex review` en el PR.
- **Si el scope rebasa 400 LOC, para y divide.** Split propuesto:
  - PR-D1a: `fresh_niwa` fixture (conftest) + `fake_planner.py`
    + workflow CI (infra).
  - PR-D1b: el test E2E en sí.
