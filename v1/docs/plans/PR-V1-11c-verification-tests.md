# PR-V1-11c — Verification E5 project tests runner

**Semana:** 3
**Esfuerzo:** M
**Depende de:** PR-V1-11b mergeado (E3+E4 ya integrados).

## Qué

Completa el contrato de verificación con E5: ejecutar los tests del
proyecto si existen, como evidencia final de que el adapter no rompió
nada.

- `project.kind == "script"` → skip, `evidence.tests_ran = False`,
  `evidence.test_reason = "kind_script"`.
- Detecta en `cwd`:
  - `package.json` con script `"test"` → `npm test --silent`.
  - `pyproject.toml` con `[tool.pytest]`/`[project.optional-dependencies]`
    que insinúe pytest **o** `Makefile` con target `test` →
    `python -m pytest -q` / `make test -s`. Prioridad: Makefile `test`
    si existe, si no pytest.
  - Nada detectado → skip con `evidence.tests_ran = False`,
    `evidence.test_reason = "no_test_script_detected"`.
- Timeout 300 s. exit 0 → pass. exit ≠ 0 → fail
  `error_code="tests_failed"`. timeout → fail
  `error_code="tests_timeout"`.

## Por qué

E5 es el último eslabón del contrato §5 del SPEC. Sin él, una task
puede dejar el proyecto roto (tests fallan) y aún así marcarse como
`verified`. Con E5, "verified" garantiza que los tests existentes
siguen pasando.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── verification/
│       ├── tests_runner.py               # NUEVO, ~100 LOC: detect + run
│       └── core.py                       # extiende verify_run con E5
└── tests/
    └── verification/
        └── test_tests_runner.py          # 3 casos del brief original §"Tests"
```

Posiblemente `test_verification_integration.py` se extiende con 1
caso E2E (fake CLI + fake proyecto con test script). Contabilízalo
en el cap.

**HARD-CAP: 400 LOC netas.** Si excedes, paras.

## Fuera de scope (explícito)

- **No se re-diseñan E1–E4** de 11a/11b.
- **No se toca el adapter, el frontend, ni la infra de git_workspace.**
- **No se añaden más runners** aparte de npm/pytest/make. Ruby, Go,
  etc. quedan follow-up.
- **No se parsea la salida de los tests** para mostrar qué falló.
  exit code es suficiente señal. El `stdout/stderr` se guarda en
  `evidence.test_output_tail` (últimos 4 KB) para diagnóstico.
- **No hay cancelación en vivo del subprocess** más allá del
  timeout global.
- **No se ejecutan subset** de tests (todos o nada en MVP).

## Dependencias nuevas

- **Ninguna.** `subprocess` stdlib, `shutil.which` para detectar
  `npm`/`make`.

## Contrato funcional

### `detect_test_runner(cwd: Path, project) -> TestRunnerChoice | None`

Devuelve la primera coincidencia en este orden:
1. Si `project.kind == "script"` → `None` con razón `kind_script`.
2. `cwd/Makefile` con una regla `test` (chequeo rápido: grep
   `^test:` con regex, sin invocar make) → `make test -s`.
3. `cwd/package.json` con `scripts.test` (parse JSON) → `npm test --silent`.
4. `cwd/pyproject.toml` (parse con `tomllib`) que indique pytest
   (`[tool.pytest]` o dependency `pytest` en
   `[project.optional-dependencies].test`) → `python -m pytest -q`.
5. Ninguno → `None` con razón `no_test_script_detected`.

`TestRunnerChoice` es un dataclass:
```python
@dataclass
class TestRunnerChoice:
    cmd: list[str]
    tool: str                  # "make" | "npm" | "pytest"
    cwd: Path
```

### `run_project_tests(choice, *, timeout=300) -> TestRunResult`

```python
@dataclass
class TestRunResult:
    passed: bool               # exit_code == 0 and not timed_out
    exit_code: int | None      # None si timeout
    timed_out: bool
    duration_s: float
    output_tail: str           # últimos 4 KB stdout+stderr combined
```

- Usa `subprocess.run(cmd, cwd=..., timeout=timeout, capture_output=True, text=True)`.
- Catch `subprocess.TimeoutExpired`: `timed_out = True`, kill el
  proceso (el `run()` ya lo hace), stdout/stderr lo que haya.
- `output_tail`: concatenar `stdout` y `stderr`, tomar últimos 4096
  chars para limitar volumen en DB.

### `verify_run` extendido con E5

```python
# Tras E4 passes (11b ya integrada):

choice = detect_test_runner(cwd, project)
if choice is None:
    evidence["tests_ran"] = False
    evidence["test_reason"] = ...  # "kind_script" | "no_test_script_detected"
    return passed(evidence)

result = run_project_tests(choice, timeout=300)
evidence["tests_ran"] = True
evidence["test_tool"] = choice.tool
evidence["test_exit_code"] = result.exit_code
evidence["test_duration_s"] = result.duration_s
evidence["test_output_tail"] = result.output_tail
if result.timed_out:
    return fail(evidence, error_code="tests_timeout")
if not result.passed:
    return fail(evidence, error_code="tests_failed")
return passed(evidence)
```

## Tests

### Nuevos backend — `tests/verification/test_tests_runner.py` (3 casos)

1. `test_npm_test_passes` — `tmp_path` con `package.json`
   `{"scripts":{"test":"exit 0"}}`. `detect_test_runner` devuelve
   npm; `run_project_tests` pasa; `result.passed == True`.
2. `test_pytest_failure` — `tmp_path` con `pyproject.toml`
   mínimo + un `test_dummy.py` con `def test_fail(): assert False`.
   `run_project_tests` devuelve `passed=False`,
   `exit_code != 0`. El orquestador (opcional en este test) mapea
   a `error_code="tests_failed"`.
3. `test_no_test_script_detected_skips` — `tmp_path` vacío y
   `project.kind="library"`. `detect_test_runner` devuelve `None`
   con razón `no_test_script_detected`; el orquestador marca
   `tests_ran=False`.

Posible 4º caso si cabe bajo cap:
4. `test_timeout` — `make` test con `sleep 999`; timeout 0.5 s →
   `timed_out=True`, `error_code="tests_timeout"`. **Solo si cabe
   en LOC budget.**

Posiblemente `test_verification_integration.py` añade 1 caso E2E
con fake CLI + fake proyecto con test script que pasa.

### Baseline tras 11c

- Backend: **~72 passed** (69 actuales + 3 tests_runner + 1 E2E).
  Cierra Semana 3 en ≥72.
- Frontend: 6 sin cambios.

## Criterio de hecho

- [ ] `pytest -q tests/verification/test_tests_runner.py` → 3
  passed (o 4 si metiste timeout bajo cap).
- [ ] `pytest -q` completo → ≥72 passed, 0 regresiones.
- [ ] Un run E2E con fake CLI + fake proyecto con test script que
  falla termina `task.status="failed"` con
  `error_code="tests_failed"`.
- [ ] Un run E2E con proyecto `kind=script` termina `verified`
  sin correr tests (`evidence.tests_ran=False`,
  `test_reason="kind_script"`).
- [ ] `run.verification_json` contiene E1–E5 al completo en un run
  exitoso.
- [ ] HANDBOOK sección "Verification tests runner (PR-V1-11c)"
  añadida; cierra el capítulo §5 del SPEC.
- [ ] Codex-reviewer ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests ≤ **400**.

## Riesgos conocidos

- **`npm test`/`pytest` pueden requerir `npm install`/`pip install`
  del proyecto** antes de poder correr. E5 NO los instala. Si las
  deps no están, el test runner falla y el run se marca como
  `tests_failed`. Documentar: el proyecto debe tener sus deps
  instaladas antes de encolar tasks.
- **`tomllib` es stdlib Python 3.11+.** Confirmar que v1 corre
  sobre 3.11+. Si es <3.11, usar `tomli` — pero es dep nueva;
  preguntar antes de añadir. (Nota: SPEC no fija versión; verificar
  en `pyproject.toml` de v1.)
- **Timeout 300 s es arbitrario.** MVP fine. Config `NIWA_VERIFY_TESTS_TIMEOUT`
  env var para override — fuera de scope de este PR, follow-up.
- **`output_tail` 4 KB puede cortar JSON/logs interesantes.**
  Suficiente para "¿qué test falló". Follow-up para log completo.

## Notas para Claude Code

- Mira el WIP `claude/v1-pr-11-verification` (local) para
  implementación de referencia de `tests_runner.py`.
- Commits sugeridos:
  1. `feat(verification): test runner detection logic`
  2. `feat(verification): subprocess test runner with timeout`
  3. `feat(verification): wire E5 into verify_run orchestrator`
  4. `test(verification): tests runner unit + E2E`
  5. `docs(v1): handbook verification tests runner section`
- **Verifica versión Python** en el skeleton del repo (`pyproject.toml`
  de v1/backend). Si es <3.11, para y pregunta antes de usar
  `tomllib`.
- Si E5 solo corre en happy-path de fake CLI (el proyecto fake del
  test tiene un package.json trivial que hace `exit 0`), verifica
  que la nota "`npm install` requerido" no aplica a la fixture.
