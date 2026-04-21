# PR-V1-11 — Contrato de verificación evidence-based

**Semana:** 3
**Esfuerzo:** M
**Depende de:** PR-V1-10 (Semana 2 cerrada)

## Qué

Módulo `verification.py` que, tras cada run del adapter, recoge
evidencias concretas del resultado y decide si el run es `completed`
o `failed`. El executor llama al verificador entre `adapter.wait()`
y `_finalize`. Cierra el bug corazón de v0.2 ("tarea marcada hecha
sin output real"): en v1, ningún run llega a `completed` sin pasar
los cinco criterios del SPEC §5.

## Por qué

SPEC §5 define verificación evidence-based con cinco condiciones.
Semana 2 implementó solo la 1 (`exit_code == 0`). Este PR
implementa las cuatro restantes y las integra. Es el PR más
importante del MVP: sin él, la UI puede volver a mostrar "done"
cuando el adapter no hizo nada, y perdemos la razón de ser del
rewrite.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── verification/
│   │   ├── __init__.py             # re-export público
│   │   ├── models.py               # VerificationResult dataclass + Evidence fields
│   │   ├── stream.py               # decide stream_terminated_cleanly
│   │   ├── artifacts.py            # git-diff del cwd + scan de tool_use paths
│   │   └── tests_runner.py         # detect + run project tests, parse exit
│   └── executor/
│       └── core.py                 # integra verifier antes de _finalize
└── tests/
    ├── verification/
    │   ├── test_stream.py          # 4 casos (ok, pregunta abierta, tool_use sin respuesta, stream cortado)
    │   ├── test_artifacts.py       # 3 casos (hay cambios, no hay cambios, escritura fuera)
    │   └── test_tests_runner.py    # 3 casos (pass, fail, no-test-script skip)
    └── test_verification_integration.py  # 2 casos E2E con fake CLI + fake tree
```

**Hard cap: 400 LOC netas (código + tests, sin HANDBOOK).** Si la
implementación va a exceder, **paras** y pides al product partner
(no al humano cansado) que defina un split. No se acepta "opción
A": el precedente de PR-V1-07 no se repite en Semana 3.

## Fuera de scope (explícito)

- **No hay triage planner** — eso es PR-V1-12.
- **No hay modo safe con PR manual** — eso es PR-V1-13.
- **No hay auto-commit / auto-push tras verificar OK.** El branch
  queda en su estado, el adapter ya hizo sus writes. La finalización
  (commit, PR, deploy) llega en Semanas 4-5.
- **No hay retry automático** tras verification_failed.
- **No se toca el adapter de Claude Code.** El verificador consume
  lo que el adapter ya deja (exit_code, run_events, filesystem del
  cwd).
- **No hay UI nueva.** El `verification_json` se persiste en el Run;
  si la UI lo quiere mostrar, llega en otro PR.

## Dependencias nuevas

- **Ninguna.** Solo stdlib (`subprocess` para `git status`, `pathlib`,
  `json`, `dataclasses`).

## Contrato funcional

### `VerificationResult` (dataclass)

```python
@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    outcome: str                    # "verified" | "verification_failed"
    error_code: str | None          # None si passed; uno de los
                                    # error_codes listados abajo si no
    evidence: dict[str, Any]        # snapshot JSON-serializable
```

### Función pública: `verify_run(session, run, task, project, cwd) -> VerificationResult`

Recoge las **cinco evidencias** y decide. Orden de chequeo
importante — detenerse al primer fallo para poder señalar la causa
exacta.

### Las cinco evidencias (en este orden)

**E1. Exit code.** `run.exit_code == 0` y `run.outcome == "cli_ok"`.
Si falla → `error_code="exit_nonzero"` o `"adapter_failure"` según
outcome del adapter.

**E2. Stream terminado limpiamente.** Carga los `run_events` del
run, ordena por `id`. El último evento **significativo** (ignorando
heartbeats y frames de lifecycle sintéticos como `started`,
`completed`, `failed`, `error`) debe ser:

  - Un evento con `event_type == "result"` con `subtype` que indique
    terminación normal (e.g. `"success"`, `"end_turn"`), **O**
  - Un mensaje `assistant` cuyo texto **no termine** en `?` (si lo
    hace es una pregunta al usuario sin responder).

Fallo si:
  - El último evento es `tool_use` sin `tool_result` posterior →
    `error_code="tool_use_incomplete"`.
  - El último mensaje asistente termina en `?` →
    `error_code="question_unanswered"`.
  - No hay ningún evento semántico (stream vacío) →
    `error_code="empty_stream"`.

**E3. Al menos un artefacto dentro del cwd.** Ejecuta `git status
--porcelain` en `cwd`. Cuenta líneas. ≥1 → OK. 0 →
`error_code="no_artifacts"`.

**E4. Ningún artefacto fuera del cwd (heurística).** Escanea todos
los `tool_use` del stream con `name ∈ {Write, Edit, MultiEdit,
NotebookEdit}` y extrae `input.file_path`. Si **cualquier** path es
absoluto y **no** empieza por `cwd_resolved` → fail
`error_code="artifacts_outside_cwd"`. Paths relativos se aceptan
(se asumen relativos al cwd del adapter).

**Known limitation documentada:** comandos bash ejecutados vía
`tool_use` `Bash` pueden escribir fuera del cwd sin que esta
heurística los detecte. Es un trade-off MVP — snapshot hash de
filesystem es overkill aquí. Mejor que v0.2 pero no infalible.

**E5. Tests del proyecto (si aplica).** Si
`project.kind == "script"` → skip, `evidence.tests_ran = False`.
Si no:
  - Detecta en `cwd`:
    - `package.json` con script `"test"` → `npm test --silent`
    - `pyproject.toml` **o** `Makefile` con target `test` →
      `python -m pytest -q` / `make test -s`
    - Nada de lo anterior → skip con `evidence.tests_ran = False`
      y `evidence.test_reason = "no_test_script_detected"`.
  - Si hay script → correr con timeout 300s, capturar exit.
    - exit 0 → pass.
    - exit !=0 → fail `error_code="tests_failed"`.
    - timeout → fail `error_code="tests_timeout"`.

### Integración en `executor/core.py`

Entre `adapter.wait()` (dentro del try) y `_finalize`, insertar:

```python
from ..verification import verify_run
# ... tras el for loop de iter_events y adapter.wait():
result = verify_run(session, run, task, project, cwd=artifact_root)
run.verification_json = json.dumps(result.evidence)
session.commit()

if result.passed:
    _finalize(session, task, run, outcome="verified", exit_code=exit_code)
else:
    _finalize(session, task, run, outcome=result.outcome, exit_code=exit_code,
              error_code=result.error_code)
```

`_finalize` acepta un `error_code` opcional que se escribe en un
nuevo `TaskEvent(kind="verification", payload_json={...})` si no es
None.

El mapeo final de success:
- `outcome == "verified"` → run `completed`, task `done`.
- cualquier otro outcome → run `failed`, task `failed`.

## Tests

### Nuevos backend

**`tests/verification/test_stream.py`** (4 casos):
1. Stream con `result/success` final → E2 pasa.
2. Último mensaje asistente termina en "?" → E2 falla
   `question_unanswered`.
3. Último evento es `tool_use` sin `tool_result` después → E2 falla
   `tool_use_incomplete`.
4. Stream vacío → E2 falla `empty_stream`.

**`tests/verification/test_artifacts.py`** (3 casos):
1. `git status --porcelain` con ≥1 línea → E3 pasa.
2. `git status --porcelain` vacío → E3 falla `no_artifacts`.
3. `tool_use Write` con `file_path` absoluto fuera de cwd → E4 falla
   `artifacts_outside_cwd`.

**`tests/verification/test_tests_runner.py`** (3 casos):
1. `package.json` con `test` que devuelve exit 0 → E5 pasa.
2. `pyproject.toml` con pytest que falla → E5 falla `tests_failed`.
3. Ningún test script detectado, project.kind=library → E5 skip con
   `tests_ran=False, test_reason="no_test_script_detected"`.

**`tests/test_verification_integration.py`** (2 casos E2E):
1. Happy path: fake CLI emite stream-json válido + crea un fichero
   en cwd + no hay test script → run termina `completed` task `done`,
   `run.verification_json` contiene las 5 evidencias.
2. Sad path: fake CLI emite pregunta final sin responder → run
   termina `failed` outcome `verification_failed`
   `error_code=question_unanswered`, task `failed`.

### Baseline tras el PR

- Backend: 59 (actual) + ~12 nuevos = **~71 passed**.
- Frontend: 6 sin cambios.

## Criterio de hecho

- [ ] `cd v1/backend && pytest -q tests/verification` → 10 passed.
- [ ] `pytest -q tests/test_verification_integration.py` → 2 passed.
- [ ] `pytest -q` completo → ≥71 passed, 0 regresiones.
- [ ] Un run con fake CLI que no crea ningún fichero en cwd termina
      como `failed` con `error_code="no_artifacts"` — verificable
      en `run.outcome` y `run.verification_json`.
- [ ] Un run con fake CLI que escribe un fichero *fuera* del cwd
      termina como `failed` con `error_code="artifacts_outside_cwd"`.
- [ ] Un run con fake CLI que acaba con pregunta sin responder
      termina como `failed` con `error_code="question_unanswered"`.
- [ ] Un run exitoso tiene `run.verification_json` con los 5 campos
      de evidencia populados y JSON-serializable.
- [ ] Codex-reviewer ejecutado. Blockers resueltos en fixup antes
      del merge.
- [ ] Cero dependencias nuevas.
- [ ] `wc -l` del diff neto (código + tests, sin HANDBOOK ni STATE)
      ≤ **400 LOC**. Si excedes, **paras** y pides split al product
      partner.

## Riesgos conocidos

- **Detección de artefactos fuera del cwd es heurística.** Solo
  inspecciona `tool_use` de Write/Edit/MultiEdit/NotebookEdit.
  Bash escrituras no se detectan. Known limitation aceptada para
  MVP.
- **Ejecutar tests del proyecto puede ser lento.** Timeout 300s.
  En MVP con proyectos pequeños es OK; cuando un proyecto tenga
  una suite grande, habrá que decidir si verify corre *todos* los
  tests o un subset.
- **`git status --porcelain` asume `cwd` es un repo.** Si no lo es
  (e.g. `project.kind="script"` que no usa git), E3 debe adaptarse:
  en ese caso, contar ficheros creados/modificados en el cwd con
  `stat` en lugar de git. Para MVP y coherencia con PR-V1-08, se
  asume repo git. Script sin repo → skip E3 con
  `evidence.git_available = False` y confiar solo en E1/E2/E5.

## Notas para el implementador (REGLAS DURAS)

- **HARD-CAP 400 LOC.** Si al implementar te das cuenta de que el
  scope es mayor, PARAS y pides split al product partner. **NO
  aceptas "opción A"** del humano. Este PR no negocia el cap —
  establecimos en la revisión de Semana 2 que el precedente de
  PR-V1-07 no se repite.
- Nada de "añadir aquí un enhancer que podría ser útil". Solo las
  5 evidencias exactas. Cualquier idea extra → `FOUND-<date>.md`.
- Si al implementar descubres que el SPEC §5 es ambiguo en algún
  detalle (p. ej. qué cuenta como "mensaje asistente" exacto del
  stream-json), PARA y pregunta. No improvises.
- Los tests deben usar el fake-CLI fixture portado de PR-V1-07 —
  no inventar uno nuevo.
- Commits sugeridos:
  1. `feat(verification): result dataclass + public entry point`
  2. `feat(verification): E2 stream termination analyzer`
  3. `feat(verification): E3/E4 artifact scanner (git + tool_use)`
  4. `feat(verification): E5 project tests runner with detection`
  5. `feat(executor): integrate verifier between adapter.wait() and finalize`
  6. `test(verification): unit + integration suites`
