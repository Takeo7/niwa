# PR-V1-11b — Verification E3+E4 artifact scanning

**Semana:** 3
**Esfuerzo:** M
**Depende de:** PR-V1-11a mergeado (skeleton + E1+E2 + executor
integration + fake CLI extendido con `FAKE_CLAUDE_TOUCH`).

## Qué

Añade las evidencias E3 y E4 al orquestador `verify_run` de 11a:

- **E3 — Al menos un artefacto dentro del cwd.** `git status
  --porcelain` en `cwd`. ≥1 línea → pasa. 0 → falla
  `error_code="no_artifacts"`.
- **E4 — Ningún artefacto fuera del cwd** (heurística).
  Escanea los `run_events` del run filtrando `event_type ==
  "tool_use"` con `payload.name ∈ {Write, Edit, MultiEdit,
  NotebookEdit}`. Extrae `payload.input.file_path`. Si alguno es
  absoluto y NO empieza por `cwd_resolved` → falla
  `error_code="artifacts_outside_cwd"`. Paths relativos se aceptan.

## Por qué

E3+E4 consolidan el contrato §5 del SPEC: "un artefacto dentro de
cwd" + "ningún artefacto fuera de cwd" son las dos condiciones que
garantizan que el adapter escribió algo en el lugar correcto.
Separar en 11b permite mantener cada PR bajo 400 LOC.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── verification/
│       ├── artifacts.py                  # NUEVO, ~100 LOC
│       └── core.py                       # extiende verify_run con E3+E4
└── tests/
    └── verification/
        └── test_artifacts.py             # 3 casos del brief original §"Artifacts"
```

Posiblemente también `test_verification_integration.py` se
extiende con 1 caso sad-path (artifact_outside). Contabilízalo en
el cap.

**HARD-CAP: 400 LOC netas.** Si excedes, paras.

## Fuera de scope (explícito)

- **No E5** (tests del proyecto). 11c.
- **No se reconsidera el diseño de E1+E2** de 11a.
- **No se toca el adapter** ni frontend ni el fake CLI (11a ya
  añadió `FAKE_CLAUDE_TOUCH`, que es suficiente para los tests
  de E3).
- **No se detectan escrituras vía `tool_use` `Bash`**.
  Known limitation aceptada (snapshot hash overkill para MVP).
- **No se compara checksum pre/post**: `git status --porcelain`
  es suficiente señal.

## Dependencias nuevas

- **Ninguna**. Solo `subprocess`, `pathlib`.

## Contrato funcional

### `verify_run` extendido

Tras 11a, el orquestador `core.py` del verification tiene estos
pasos:

```python
def verify_run(session, run, task, project, cwd, *,
               adapter_outcome, exit_code) -> VerificationResult:
    evidence = {}

    # E1 (11a)
    if not check_exit_ok(adapter_outcome, exit_code, evidence):
        return fail(evidence, outcome=..., error_code=...)

    # E2 (11a)
    if not check_stream_terminated(session, run, evidence):
        return fail(...)

    # E3 (11b — nuevo)
    if not check_artifacts_in_cwd(cwd, evidence):
        return fail(..., error_code="no_artifacts")

    # E4 (11b — nuevo)
    if not check_no_artifacts_outside_cwd(session, run, cwd, evidence):
        return fail(..., error_code="artifacts_outside_cwd")

    # E5 (11c) — stub vacuo: evidence.tests_ran = False
    ...

    return passed(evidence)
```

### E3 — `check_artifacts_in_cwd(cwd: Path, evidence: dict) -> bool`

Ejecuta:
```
subprocess.run(["git", "status", "--porcelain"],
               cwd=cwd, check=True, capture_output=True, text=True)
```

- `stdout.splitlines()` — contar líneas no vacías.
- `count >= 1` → E3 pasa, `evidence.artifacts_count = count`.
- `count == 0` → E3 falla, `error_code="no_artifacts"`.

**Known limitation del brief original #3**: si el adapter llega a
commitear su trabajo (futuro finalize), el árbol queda limpio y
E3 falla. Solución futura: contar también commits
`HEAD~..HEAD_original`. Para el MVP, el adapter NO commitea, así
que el working tree queda con cambios untracked/modified →
`--porcelain` los cuenta correctamente. Documentar.

**Si `cwd` no es repo git** (project.kind=script sin git): skip E3
con `evidence.git_available = False`. Para 11a esto se trataba
stub; en 11b si `subprocess` falla con `fatal: not a git
repository`, skip graceful.

### E4 — `check_no_artifacts_outside_cwd(session, run, cwd, evidence)`

Carga `run_events` del run; filtra:
```python
records = session.execute(
    select(RunEvent).where(RunEvent.run_id == run.id,
                           RunEvent.event_type == "tool_use")
    .order_by(RunEvent.id.asc())
).scalars().all()
```

Para cada `event.payload` (parsed JSON):
1. Si `payload.get("name")` no está en
   `{"Write", "Edit", "MultiEdit", "NotebookEdit"}` → skip.
2. `file_path = payload.get("input", {}).get("file_path")` (o
   `"path"` si `NotebookEdit`).
3. Si `file_path` es `None` → skip.
4. Si `Path(file_path).is_absolute()`:
   - `resolved = Path(file_path).resolve()`.
   - Si no es subpath de `Path(cwd).resolve()` → fail.
5. Si no absolute → skip (se asume relativo al cwd del adapter).

Evidence populada:
```json
{
  "artifacts_outside_cwd": false,
  "tool_use_writes_scanned": 3,
  "tool_use_writes_absolute": 1
}
```

En caso de fail:
```json
{
  "artifacts_outside_cwd": true,
  "offending_paths": ["/tmp/leak.txt"]   // primer offender
}
```

## Tests

### Nuevos backend — `tests/verification/test_artifacts.py` (3 casos)

1. `test_dirty_cwd_passes_e3` — `git_project` con fichero modified;
   `check_artifacts_in_cwd` retorna True y
   `evidence.artifacts_count >= 1`.
2. `test_clean_cwd_fails_no_artifacts` — `git_project` sin cambios
   post-commit inicial; E3 falla `error_code="no_artifacts"`.
3. `test_absolute_path_outside_cwd_fails_artifacts_outside_cwd` —
   simula un `RunEvent(event_type="tool_use")` con
   `payload={"name":"Write", "input":{"file_path":"/tmp/leak.txt"}}`;
   `check_no_artifacts_outside_cwd(cwd=git_project_path, ...)`
   devuelve False y evidence marca `offending_paths`.

Posiblemente 1 caso E2E adicional en
`test_verification_integration.py`:
- `test_sad_path_artifacts_outside_cwd` — fake CLI emite un
  `tool_use` con `file_path=/tmp/foo`; tras run,
  `run.outcome="verification_failed"` +
  `error_code="artifacts_outside_cwd"`.

### Baseline tras 11b

- Backend: **~69 passed** (65 actuales + 3 artifacts + 1 E2E).
- Frontend: 6 sin cambios.

## Criterio de hecho

- [ ] `pytest -q tests/verification/test_artifacts.py` → 3 passed.
- [ ] `pytest -q` completo → ≥69 passed, 0 regresiones.
- [ ] Un run que no crea ningún fichero en cwd termina
  `verification_failed` con `error_code="no_artifacts"`.
- [ ] Un run cuyo `tool_use Write` escribe a `/tmp/...` termina
  `verification_failed` con `error_code="artifacts_outside_cwd"`.
- [ ] `run.verification_json` contiene `artifacts_count`,
  `artifacts_outside_cwd`, `tool_use_writes_scanned`, más lo de
  11a (E1+E2).
- [ ] HANDBOOK sección "Verification artifacts (PR-V1-11b)"
  añadida.
- [ ] Codex-reviewer ejecutado. Blockers resueltos antes del
  merge.
- [ ] LOC netas código+tests ≤ **400**. Si excedes, paras.

## Riesgos conocidos

- **Paths relativos del tool_use**: el brief asume relativo al cwd
  del adapter. Si el CLI emite paths relativos a otra raíz
  (`~/...`, `$HOME`), E4 no los detecta como absolutos y los
  acepta. Aceptado como MVP.
- **Symlinks**: `Path.resolve()` los sigue. Si `cwd` es un symlink
  y el CLI escribe a su target absoluto, E4 podría decidir que
  está dentro o fuera según cómo esté el symlink. Para MVP,
  documentamos y no resolvemos caso especial.
- **`git status --porcelain` en subrepos/submodules**: cuenta
  submódulos como una sola línea. Aceptable.

## Notas para Claude Code

- Mira el WIP `claude/v1-pr-11-verification` (local) para la
  implementación de referencia de `artifacts.py`. Recorta al scope
  de 11b.
- Commits sugeridos:
  1. `feat(verification): E3 artifact presence check`
  2. `feat(verification): E4 tool_use path scan for writes outside cwd`
  3. `feat(verification): wire E3+E4 into verify_run orchestrator`
  4. `test(verification): artifact unit + E2E suites`
  5. `docs(v1): handbook verification artifacts section`
- **Si al implementar E4 descubres que los tests del fake CLI no
  emiten `tool_use`** (solo emiten `assistant`/`result`), extiende
  el fake para permitir inyectar tool_use via una env
  `FAKE_CLAUDE_TOOL_USE` (payload JSONL adicional). Mantén el cambio
  mínimo.
- Si LOC excede por bukar E4 en el orquestador, considera extraer
  los filtros a `artifacts.py` y mantener `core.py` como cola
  delegada.
