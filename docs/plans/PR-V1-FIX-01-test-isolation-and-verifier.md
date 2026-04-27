# PR-V1-FIX-01 — Test isolation + locale-independent verifier

**Semana:** post-MVP (hot-fix tras smoke v1.1)
**Esfuerzo:** S
**Depende de:** ninguna (sale directo de main `b5703cc`).

## Qué

Hot-fix de dos rojos detectados en el smoke técnico v1.1 (uno de
ellos environment-dependent, el otro reproducible):

1. **(A)** `test_readiness_api.py::test_all_checks_ok` se rompe en
   cualquier máquina con `~/.niwa/config.toml` que declare
   `[claude].cli` apuntando a una ruta absoluta. El stub de
   `shutil.which` en el test sólo cubre la clave literal
   `"claude"`, así que cuando `load_settings()` resuelve un path
   absoluto el stub devuelve `None`. Aislar la lectura de
   settings en el test.
2. **(B)** `test_artifacts.py::test_non_git_cwd_skips_e3_gracefully`
   se rompe en cualquier máquina cuyo `git` emita stderr
   localizado (p. ej. `LANG=es_ES.UTF-8` con git-i18n
   instalado). `check_artifacts_in_cwd` mira el substring
   inglés `"not a git repository"` en stderr para decidir el
   skip gracioso; con stderr `"fatal: no es un repositorio
   git ..."` la rama no casa, cae al else, setea
   `error_code='no_artifacts'` y retorna `False`. Hacer la
   detección locale-independent forzando `LANG=C` en el
   subprocess.
3. **(C)** Documentar `pip install -e ".[dev]"` (con extras) en
   `docs/HANDBOOK.md` para que un fresh install ejecute la
   suite sin pasos extra.

## Por qué

El smoke detectó la fragilidad del único gate de confianza del
ciclo v1.1 (no hay CI). Los dos tests rojos son síntomas del
mismo patrón sistemático ("el proceso confía en algo que no se
está verificando"): (1) confía en que el sandbox del sub-agente
representa el entorno real del humano; (2) confía en que el
locale del subprocess es siempre inglés. Antes de meter CI
(PR-V1-37) hay que dejar la suite verde y determinística.

## Scope — archivos que toca

- `backend/app/verification/artifacts.py` — pasar
  `env={**os.environ, "LANG": "C", "LC_ALL": "C", "LANGUAGE": "C"}`
  a `subprocess.run`. **Orden obligatorio**: `os.environ` primero
  (spread base), overrides después; el último `**` /  par clave-valor
  pisa al anterior, así que la forma inversa
  (`{"LANG": "C", ..., **os.environ}`) deja el bug intacto cuando el
  proceso hereda `LANG=es_ES.UTF-8`. **`LANGUAGE`** se incluye
  porque git en Linux respeta `LANGUAGE` por encima de `LANG` en
  varias distros (Ubuntu de la pareja entre ellas). Comentario
  inline de 1 línea explicando el porqué.
- `backend/tests/test_readiness_api.py` — en
  `test_all_checks_ok` añadir `monkeypatch` de
  `app.api.readiness.load_settings` para devolver un `Settings`
  con `claude_cli=None`. La función ya existe; sólo se inyecta.
  El resto de la suite no necesita el patch porque sólo
  `test_all_checks_ok` chequea `cli_details["path"] ==
  "/usr/local/bin/claude"` literalmente; los otros sólo miran
  `claude_cli_ok` boolean. **Decisión a verificar in situ**: si
  `load_settings` resultase estar cacheada al startup (no es el
  caso a día de hoy según `app/config.py:63`, pero el sub-agente
  debe confirmar leyendo el endpoint), el `monkeypatch.setattr`
  no surte efecto. En ese supuesto, conmutar a
  `app.dependency_overrides[load_settings] = lambda: Settings(
  claude_cli=None, ...)` sobre el `client.app`. Documentar la
  decisión tomada (monkeypatch vs dependency_override) en el
  cuerpo del commit.
- `backend/tests/verification/test_artifacts.py` — añadir un
  test nuevo `test_check_artifacts_passes_lang_c_env_to_subprocess`
  que monkeypatchea `subprocess.run` para capturar el `env=`
  recibido y verifica que contiene `LANG=C`, `LC_ALL=C`,
  `LANGUAGE=C`. El subprocess fingido devuelve un
  `CompletedProcess` con `returncode=0` para que la función
  retorne sin entrar en la rama except. **Test contract-on-env**:
  prueba el wiring del fix directamente, no las consecuencias
  en stderr — así la impl queda mínima (solo `env=`, sin
  defensas paralelas).
- `docs/HANDBOOK.md` — sección "Arranque en dev" o "Tests":
  asegurar que `pip install -e ".[dev]"` (con `[dev]`) está
  documentado explícitamente. Hoy menciona
  `make install` (que internamente lo hace) pero un fresh
  install que skip-ea el Makefile (p. ej. CI mínimo en
  PR-V1-37) necesita el comando exacto.

## Fuera de scope (explícito)

- No tocamos `services/github_pulls.py` aunque también parsea
  substrings de `gh` stderr. `gh` es English-only en la
  práctica; si alguna vez se localiza, follow-up dedicado.
- No tocamos otras invocaciones de `git` en
  `executor/git_workspace.py`, `finalize.py`,
  `readiness_checks.check_git`. Repasadas: ninguna parsea
  substrings de stderr (sólo `returncode`, o stderr propagado
  verbatim a mensajes de error). Locale-safe ya.
- No introducimos `LANG=C` como wrapper genérico ni helper. Lo
  aplicamos puntualmente en el sitio donde la falta del flag es
  un bug demostrable. Helper si volviese a aparecer en otro
  PR — YAGNI.
- No metemos CI ni github-actions. Eso es PR-V1-37, sesión
  siguiente.

## Dependencias nuevas

- Python: ninguna.
- npm: ninguna.

## Tests

- **Nuevos:**
  - `backend/tests/verification/test_artifacts.py::test_check_artifacts_passes_lang_c_env_to_subprocess`
    — monkeypatch de `subprocess.run` que **captura el `env=`**
    recibido y verifica `env["LANG"] == env["LC_ALL"] ==
    env["LANGUAGE"] == "C"`. El fingido devuelve
    `CompletedProcess(args=cmd, returncode=0, stdout="",
    stderr="")` para que `check_artifacts_in_cwd` no caiga en
    la rama except. **Test contract-on-env**: ejerce
    directamente el contrato del fix; no necesita stderr
    localizado. Patrón:

    ```python
    def test_check_artifacts_passes_lang_c_env_to_subprocess(
        tmp_path, monkeypatch
    ):
        captured: dict = {}
        def fake_run(*args, **kwargs):
            captured["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(
                args=args[0], returncode=0, stdout="", stderr=""
            )
        monkeypatch.setattr(subprocess, "run", fake_run)
        repo = tmp_path / "repo"; repo.mkdir()
        check_artifacts_in_cwd(repo, {})
        env = captured["env"]
        assert env is not None
        assert env["LANG"] == "C"
        assert env["LC_ALL"] == "C"
        assert env["LANGUAGE"] == "C"
    ```
  - `backend/tests/verification/test_artifacts.py::test_check_artifacts_real_subprocess_under_localized_lang`
    — ejerce el subprocess **real** con `LANG`/`LC_ALL`/`LANGUAGE`
    forzados a un locale instalado (`es_ES.UTF-8` por defecto).
    Garantiza que el override de `env` propaga end-to-end al
    `git status --porcelain`, no sólo a la rama de detección. Skip
    automático si el locale no está disponible en el sandbox vía
    helper privado (`_has_locale("es_ES.UTF-8")` que parsea
    `locale -a` o usa `subprocess.run(["locale","-a"])`). Patrón:

    ```python
    @pytest.mark.skipif(
        not _has_locale("es_ES.UTF-8"),
        reason="es_ES.UTF-8 locale not generated in this sandbox",
    )
    def test_check_artifacts_real_subprocess_under_localized_lang(
        tmp_path, monkeypatch
    ):
        monkeypatch.setenv("LANG", "es_ES.UTF-8")
        monkeypatch.setenv("LC_ALL", "es_ES.UTF-8")
        monkeypatch.setenv("LANGUAGE", "es")
        plain = tmp_path / "not-a-repo"
        plain.mkdir()
        evidence: dict = {}
        assert check_artifacts_in_cwd(plain, evidence) is True
        assert evidence.get("error_code") is None
        assert evidence.get("git_available") is False
    ```

    El test contract-on-env (mockeado) cubre el **contrato
    del wiring** sin depender de locales instalados; este
    cubre el **end-to-end real** con git ejerciéndose bajo un
    locale no-C. Sin el segundo, un futuro refactor que
    cambie la forma de pasar el env (p. ej. via `os.environ`
    en lugar de `env=`) podría seguir cumpliendo el primer
    test pero romper el comportamiento real.
- **Modificados:**
  - `backend/tests/test_readiness_api.py::test_all_checks_ok`
    — sólo añade `monkeypatch.setattr` sobre
    `app.api.readiness.load_settings`. Mantiene asserts
    actuales sobre body completo.
- **Existentes que deben seguir verdes:** los 194 tests
  actuales del baseline backend (incluyendo
  `test_non_git_cwd_skips_e3_gracefully` original, que sigue
  documentando el caso "stderr inglés"). El nuevo cubre
  "stderr no-inglés".

## Criterio de hecho

Lista verificable:

- [ ] `cd backend && python -m pytest -q` reporta `196 passed`
      (194 previos + 2 nuevos: locale-stderr monkeypatched +
      real-subprocess locale-skipif). El segundo aparece como
      `skipped` si el sandbox no tiene `es_ES.UTF-8` instalado.
- [ ] El sub-agente ejecuta antes de codex, en este orden:
      `LANG=es_ES.UTF-8 LC_ALL=es_ES.UTF-8 LANGUAGE=es cd backend && python -m pytest -q tests/verification/test_artifacts.py`
      y `cd backend && python -m pytest -q tests/test_readiness_api.py`.
      Pega el **output literal** de ambos comandos (incluyendo el
      summary final `N passed/skipped/failed in Xs`) en el body
      del PR. Sin esa evidencia, **no merge**.
- [ ] El reporte literal del `pytest -q` completo se incluye
      también en el body — sin `✓` ni resúmenes humanos.
- [ ] El test contract-on-env, ejecutado contra `artifacts.py`
      SIN el fix de `env=LANG=C`, falla por `KeyError` o
      `AssertionError` al pedir `env["LANG"]` (porque el `env`
      capturado es `None` cuando no se pasa el kwarg). El
      sub-agente escribe el test en rojo primero, confirma el
      fallo, y sólo entonces edita `artifacts.py`. Commit
      `test: failing case for env wiring` antes del fix.
- [ ] HANDBOOK menciona `pip install -e ".[dev]"` en la
      sección de arranque o tests.
- [ ] `cd frontend && npm test` sigue verde (no se toca
      frontend; sanity check).
- [ ] Codex obligatorio sobre el diff. Resolución pegada en
      el body del PR.

## Riesgos conocidos

- **Cap S = 80 LOC.** Si el sub-agente proyecta exceder, paras
  y consultas. Cuatro muestras en el ciclo v1.1
  (`FOUND-20260426-loc-cap-pattern.md`) — la disciplina aquí
  es no comerse el cap por silencio.
- **`os.environ` puede traer `LANG`/`LC_ALL`/`LANGUAGE` ya
  seteados.** El fix usa
  `{**os.environ, "LANG": "C", "LC_ALL": "C", "LANGUAGE": "C"}`.
  **Orden importa**: el spread va primero (base), los overrides
  últimos (ganan). La forma inversa
  (`{"LANG": "C", ..., **os.environ}`) deja el bug intacto
  cuando el padre exporta `LANG=es_ES.UTF-8`. **Doble cobertura
  de test** garantiza el contrato:
  1. Test contract-on-env (mockeado) ejerce el contrato del
     wiring directamente — verifica que el `env` pasado al
     subprocess contiene `LANG=C` etc. Independiente de
     locales instalados, vale en cualquier sandbox.
  2. Test con `monkeypatch.setenv` + subprocess real ejerce el
     end-to-end con git ejecutándose bajo un locale no-C
     (skip-if-no-locale).
  El primer test atrapa olvidos del kwarg `env=`; el segundo
  atrapa cambios semánticos del fix (e.g., setear `os.environ`
  global en vez de pasar `env=`).
- **`load_settings` cacheada.** Confirmar in-situ que el
  endpoint llama `load_settings()` por request y no usa
  `lru_cache`/cache-at-startup. Lectura rápida actual:
  `app/config.py:63` no está cacheada y `app/api/readiness.py:44`
  invoca `load_settings()` por request, así que el
  `monkeypatch.setattr("app.api.readiness.load_settings", ...)`
  funciona. Si en algún momento eso cambia, el sub-agente debe
  conmutar a `app.dependency_overrides[load_settings]` con
  cleanup en teardown — y dejarlo escrito en el cuerpo del
  commit.
- **Si Codex marca blocker non-trivial** — verifier es área
  crítica, sin excusa para skip de codex aunque sea S. Brief
  asume codex obligatorio; si codex marca algo y el fix-up
  excede el cap, se para y se consulta al humano.

## Notas para Claude Code

- **Una sesión = un PR.** Al abrir PR, terminas. No empieces
  PR-V1-37 ni PR-V1-36.
- **Tests primero**: escribir test contract-on-env rojo
  (commit `test: failing case for env wiring`), confirmar
  que falla porque `env` capturado es `None` o no contiene
  `LANG=C`, y luego el fix de `artifacts.py` (impl mínima:
  añadir `env={**os.environ, "LANG":"C", "LC_ALL":"C",
  "LANGUAGE":"C"}` al `subprocess.run`, sin defensas
  paralelas tipo `not_a_repo`).
- **Output literal de pytest**: cuando reportes "tests
  verdes", pega el output exacto de `python -m pytest -q`. No
  reescribas a `✓` ni a `OK`. El gate del ciclo v1.1 fue
  precisamente "reportes sin evidencia literal mienten".
- **Gate pre-codex obligatorio**: antes de invocar
  `codex-reviewer`, ejecuta y pega en el body del PR (o en el
  reporte al orquestador) el output literal de:
  - `cd backend && python -m pytest -q`
  - `cd backend && LANG=es_ES.UTF-8 LC_ALL=es_ES.UTF-8 LANGUAGE=es python -m pytest -q tests/verification/test_artifacts.py`
  - `cd backend && python -m pytest -q tests/test_readiness_api.py`
  - `cd frontend && npm test`
  Si alguno reporta `failed`, no procedes a codex — paras y
  reportas al orquestador.
- **Commits pequeños, imperativos, en inglés.**
- Codex obligatorio: lanza `codex-reviewer` sobre el diff
  antes de abrir PR. El brief lo pide explícito porque toca
  verifier (área crítica) y la suite (gate de confianza).
- Cap LOC: 80. Si te excedes, paras y consultas. No metas
  refactor de helper ni endurezcas otras invocaciones de
  subprocess.
