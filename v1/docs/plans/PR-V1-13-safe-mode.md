# PR-V1-13 — Safe mode: commit + push + open PR

**Semana:** 3 (cierre)
**Esfuerzo:** M
**Depende de:** PR-V1-12b mergeado (triage + verificación integradas).

## Qué

Tras `verify_run` aprobar (outcome `verified`), el executor ejecuta
`finalize_task(session, run, task, project)` que:

1. `git add -A` + `git commit -m "niwa: {task.title}" -m "{body}"` en
   el cwd del run (la rama `niwa/task-<id>-<slug>` creada por
   PR-V1-08). Body = descripción + firma Niwa.
2. Si `project.git_remote` no-None: `git push -u <remote>
   niwa/task-<id>-<slug>`.
3. Si además `gh` está en PATH (check con `shutil.which("gh")`):
   `gh pr create --title "{title}" --body "{body}"`. Captura la
   URL devuelta y persiste en `task.pr_url`.
4. Si `gh` falta o remote no está configurado: **log del comando
   equivalente** y continúa. La task permanece `done`; la branch
   local tiene el trabajo; el humano puede abrir el PR manualmente.

**Autonomy mode**: este PR solo implementa `safe`. `dangerous`
(auto-merge) queda en Semana 4.

## Por qué

SPEC §1: "Commit + push de la rama. Abre PR automático si el repo
tiene remote GitHub. Si autonomy_mode = dangerous, mergea".
SPEC §9 Semana 3 cierra con "modo safe (PR manual)". Este PR
entrega el brazo safe; Semana 4 añade dangerous.

Antes de este PR, los cambios del adapter quedan en working tree
sin committear: el usuario tiene que mirar la rama manualmente y
commitear. Con 13, el flujo end-to-end termina con una URL clickeable
(o un log reproducible).

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── finalize.py                         # nuevo, ~130 LOC
│   └── executor/
│       └── core.py                         # finalize_task tras verify_run passes
└── tests/
    ├── test_finalize.py                    # nuevo, 4-5 casos unit
    └── test_executor.py                    # +1 integration E2E
```

**HARD-CAP 400 LOC netas código+tests.** Proyección ~350. Si
excedes, PARAS y reportas.

## Fuera de scope (explícito)

- **No hay autonomy dangerous / auto-merge.** Semana 4 o PR-V1-14.
- **No hay deploy** a localhost:PORT. Semana 4-5.
- **No se toca el contrato de verificación.**
- **No se toca el adapter ni el triage.**
- **No hay UI** para mostrar `pr_url`. Follow-up puede extender el
  detalle de task para renderizar el link si existe.
- **No hay rollback** si el PR se abrió pero algo posterior falla
  (no hay "posterior" en safe mode).
- **No hay force-push**, no amend.
- **No hay manipulación de labels**, reviewers, milestones, etc.
  en el PR creado. `gh pr create` con args mínimos.
- **No se detecta la branch default del remote.** `gh` lo hace
  automáticamente por defecto; MVP trust.
- **No se comprueba autenticación** de `gh` previamente —
  `gh pr create` fallará y caemos a la ruta de log.

## Dependencias nuevas

- **Ninguna.** Stdlib (`subprocess`, `shlex`, `shutil`, `pathlib`).

## Contrato funcional

### `FinalizeResult` (dataclass)

```python
@dataclass(frozen=True)
class FinalizeResult:
    committed: bool                     # True si commit tuvo éxito
    pushed: bool                        # True si push tuvo éxito
    pr_url: str | None                  # URL si gh pr create devolvió una
    commands_skipped: list[str]         # razones (ej. "no_remote", "gh_missing")
```

### `finalize_task(session, run, task, project) -> FinalizeResult`

Semántica **best-effort**: no lanza excepciones al caller. Cada
paso que falla se loggea y se refleja en el resultado. La task
sigue `done` aunque finalize no llegue hasta el PR.

Orden:

1. **Commit**. Si `git status --porcelain` vacío → `committed=False`,
   skip con razón `"nothing_to_commit"`. Si hay cambios:
   - `git add -A`.
   - `git -c user.email="niwa@localhost" -c user.name="Niwa"
     commit -m "{subject}" -m "{body}"`. Los flags `-c` evitan
     depender de config global.
   - Si commit devuelve != 0 → `committed=False`,
     `commands_skipped += ["commit_failed: <stderr>"]`.
   - `subject = f"niwa: {task.title[:60]}"` (truncado para no pasar
     72 chars del estándar git).
   - `body = (task.description or "") + "\n\nNiwa task #" +
     str(task.id)`.
2. **Push** (solo si `committed` y `project.git_remote`):
   - `git push -u origin {branch_name}` (origin viene de
     `git_remote`, pero git lo resuelve al remote configurado;
     asumimos `origin` set por el usuario al clonar).
   - Si push falla → `pushed=False`, commands_skipped += msg.
3. **PR** (solo si `pushed` y `shutil.which("gh")`):
   - `gh pr create --title "{title}" --body "{body}" --head
     {branch_name}` ejecutado con `cwd=project.local_path`.
   - `title = task.title[:70]`.
   - `body = (task.description or "(no description)") +
     "\n\n---\nOpened by Niwa for task #" + str(task.id)`.
   - `gh` imprime la URL del PR en stdout (una línea).
   - Si exit 0: `pr_url = stdout.strip()`. Si la línea no parece
     URL, `pr_url = None` con log.
   - Si exit != 0: log comando equivalente, `pr_url = None`,
     commands_skipped += `"gh_pr_create_failed: <stderr[:500]>"`.
4. **Persist**: si `pr_url`, `task.pr_url = pr_url`. Commit.
5. **Log** (en `commands_skipped` o al logger): comando que el
   usuario podría correr para completar manualmente. Si falla
   el push, loggear `git push -u origin {branch}`. Si falla el
   PR, loggear `gh pr create --head {branch}`.

### Integración en `executor/core.py`

Entre `run.verification_json = ...; session.commit()` y el
`_finalize(...)` de la rama verified:

```python
if result.passed:
    try:
        fin = finalize_task(session, run, task, project)
        logger.info("finalize task_id=%s committed=%s pushed=%s pr_url=%s",
                    task.id, fin.committed, fin.pushed, fin.pr_url)
    except Exception as exc:
        # finalize es best-effort; si algo catastrófico revienta (no
        # subprocess normal), loggear y seguir. NO regresar la task.
        logger.exception("finalize crashed for task_id=%s", task.id)
    _finalize(session, task, run, outcome="verified", exit_code=exit_code)
```

## Tests

### Nuevos unit — `test_finalize.py` (4-5 casos)

Mockean `subprocess.run` con `monkeypatch` (no pasar por git/gh
reales). Helper `_mock_cmd(monkeypatch, returncodes_by_cmd: dict[str, tuple[int, str, str]])`.

1. `test_commit_push_and_pr_happy_path` — git status sucio, commit
   ok, push ok, gh existe, `gh pr create` devuelve
   `"https://github.com/foo/bar/pull/42"`. FinalizeResult con
   `committed=True, pushed=True, pr_url="https://github.com/foo/bar/pull/42"`.
   `task.pr_url` persistido.
2. `test_nothing_to_commit_skipped` — `git status --porcelain`
   vacío. `committed=False`, `pushed=False`, `pr_url=None`,
   `commands_skipped=["nothing_to_commit"]`.
3. `test_no_git_remote_skips_push_and_pr` — commit ok,
   `project.git_remote=None`. `committed=True, pushed=False,
   commands_skipped=["no_remote"]`.
4. `test_gh_missing_skips_pr` — commit + push ok,
   `shutil.which("gh")` devuelve None (mock).
   `committed=True, pushed=True, pr_url=None,
   commands_skipped=["gh_missing: run 'gh pr create --head ...'"]`.
5. (Si cabe) `test_gh_pr_create_failure_logs_command` — gh existe,
   pero `gh pr create` devuelve exit 1. `pr_url=None`,
   `commands_skipped` incluye el stderr.

### Integration E2E en `test_executor.py` (1 caso)

`test_process_pending_finalizes_verified_run_with_gh_stub`:
- Monkeypatch `finalize_task` directamente con spy que devuelve
  `FinalizeResult(committed=True, pushed=True,
  pr_url="https://...")`. Alternativa: mockear subprocess
  selectivamente para git y gh.
- Task encolada, triage stub execute, fake CLI crea artefacto,
  verify pasa, finalize mockeado devuelve url.
- Tras `process_pending`: `task.status=="done"`,
  `task.pr_url=="https://..."`, `run.outcome=="verified"`.

**Baseline tras PR-V1-13**: 83 → **~88 passed** (83 actuales + 4
unit + 1 integration).

## Criterio de hecho

- [ ] `pytest -q tests/test_finalize.py` → 4 (o 5) passed.
- [ ] `pytest -q` completo → ≥88 passed, 0 regresiones.
- [ ] Un run verified con remote y `gh` disponible: task termina
  `done`, `pr_url` populado con URL válida.
- [ ] Un run verified sin remote: task termina `done`, `pr_url`
  None, rama local intacta.
- [ ] Un run verified con remote pero sin `gh`: task `done`, push
  realizado, `pr_url` None, log con comando manual.
- [ ] Un run verified sin cambios (imposible si E3 pasó; caso
  defensivo): `committed=False`, task igual `done`.
- [ ] HANDBOOK sección "Safe mode finalize (PR-V1-13)" con:
  pipeline completo, flags `gh` args, config git vía `-c`,
  comportamiento sin remote / sin gh, persistence de `pr_url`.
- [ ] Codex ejecutado. Blockers cerrados antes del merge.
- [ ] LOC netas código+tests ≤ **400**.

## Riesgos conocidos

- **`git` config ausente**: los flags `-c user.email="niwa@localhost"
  -c user.name="Niwa"` inline hacen el commit self-contained.
  Documentado.
- **`origin` remote ausente**: el código asume `origin` como
  default. Si el usuario renombra, `git push -u origin` falla y
  push queda como skipped. Documentado; la alternativa (auto-detect
  remote) infla LOC.
- **`gh` no autenticado**: `gh pr create` fallará con exit != 0.
  Caemos a la ruta de log. El usuario debería haber corrido
  `gh auth login` antes. Documentado.
- **`gh pr create` con base branch no obvio**: `gh` usa el default
  del repo. Si el repo tiene `master` u otro, puede fallar por
  branch mismatch. MVP: log, follow-up si usuario lo pide.
- **Carrera de remote**: si el usuario hace push manual a la misma
  rama entre verify y finalize, el push de Niwa puede fallar por
  non-fast-forward. MVP no protege — asume uso monousuario.
- **`commands_skipped` crece**: lista de razones acumulativa para
  debug. En producción podría renderizarse al UI vía
  `run.verification_json` o campo nuevo; out of scope de 13.
- **Commit message con caracteres especiales en title/description**
  (backticks, comillas, saltos de línea): `-m` de git los trata
  literales. Para títulos muy largos / con caracteres unicode,
  MVP confía en que el CLI lo maneje.

## Notas para Claude Code

- Commits sugeridos (5):
  1. `feat(finalize): commit + push + gh pr create pipeline`
  2. `feat(executor): invoke finalize_task on verified runs`
  3. `test(finalize): unit cases for happy path and skips`
  4. `test(executor): finalize integration on verified run`
  5. `docs(v1): handbook safe mode finalize section`
- Mantén `finalize.py` plano — función pública + dataclass + 3 o 4
  helpers privados (`_run_cmd`, `_commit`, `_push`, `_pr_create`).
- `_run_cmd(args, cwd) -> (rc, stdout, stderr)`: `subprocess.run`
  con `check=False, capture_output=True, text=True, timeout=30`.
  Log info del comando.
- `commit` debe usar los flags `-c user.email`/`-c user.name` para
  no depender del config global del sistema.
- `gh pr create` captura URL de stdout. Verifica con
  `re.match(r"https?://", line.strip())`.
- **Si algo del brief es ambiguo, PARA y reporta.**
