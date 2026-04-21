# PR-V1-16 — Dangerous mode: auto-merge + UI banner

**Semana:** 4 (cierre)
**Esfuerzo:** M
**Depende de:** PR-V1-13 mergeado (safe mode finalize).

## Qué

Cierra Semana 4 activando el brazo `autonomy_mode="dangerous"`:

1. **Backend**: `finalize_task` añade un paso opcional **tras**
   `gh pr create` (solo si PR creado + `gh` disponible +
   `project.autonomy_mode == "dangerous"`):
   - `gh pr merge <pr_url> --squash --delete-branch`.
   - Si éxito → `FinalizeResult.pr_merged = True`.
   - Si falla → log del comando manual + `pr_merged = False` +
     entry en `commands_skipped`.
2. **Frontend**: banner rojo prominente en
   `/projects/:slug` cuando `project.autonomy_mode === "dangerous"`.
   Texto: "Dangerous mode — runs auto-merge PRs. Review carefully
   before enabling." El badge existente sigue, pero el banner
   avisa de golpe.

## Por qué

SPEC §1/§4: "`autonomy_mode = dangerous` → Niwa abre PR,
auto-mergea si verify OK". SPEC §9 Semana 4 pide el modo dangerous
con auto-merge. PR-V1-13 dejó preparado el camino pero solo
implementó safe (`autonomy_mode=safe` abre PR y espera humano).
Este PR activa dangerous end-to-end.

Banner UI avisa visualmente: el usuario tiene que ver de un
vistazo si el proyecto va a auto-mergear. Un badge pequeño no es
suficiente.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   └── finalize.py                         # +paso auto-merge
└── tests/
    └── test_finalize.py                    # +2-3 casos dangerous

v1/frontend/
├── src/
│   └── features/projects/
│       └── ProjectDetail.tsx               # banner rojo si dangerous
└── tests/
    └── ProjectDetail.test.tsx              # nuevo, 2 casos banner
```

**HARD-CAP 400 LOC netas código+tests** (sin HANDBOOK). Proyección
~250. Si excedes, PARAS.

## Fuera de scope (explícito)

- **No se añade toggle UI para cambiar `autonomy_mode`** — se sigue
  editando vía PATCH `/api/projects/{slug}` (backend expuesto ya) o
  DB directa. Añadir un toggle requeriría confirm modal + mutation
  nueva — follow-up.
- **No se añade columna `pr_merged_at`** al schema.
  `FinalizeResult.pr_merged` solo vive en memoria y en logs.
  `task.pr_url` sigue siendo la única persistencia relevante.
- **No hay rollback del merge** si verify post-merge falla (verify
  ya corrió antes del merge — si el merge rompe el target branch,
  es responsabilidad del usuario).
- **No hay deploy local** tras auto-merge. SPEC §9 Semana 5.
- **No hay límite de "intentos" o backoff**. `gh pr merge` falla
  → log y seguimos.
- **No se auto-mergea en proyectos sin `git_remote`** (obvio: no
  hay PR).
- **No se toca adapter, triage, verification, executor,
  bootstrap, CLI.** Cero cambios ahí.
- **No se fuerza confirm** en UI antes del primer run en dangerous.
  Banner + badge suficientes.

## Dependencias nuevas

- **Ninguna** (backend stdlib, frontend nada).

## Contrato funcional

### `FinalizeResult` extendido

```python
@dataclass(frozen=True)
class FinalizeResult:
    committed: bool
    pushed: bool
    pr_url: str | None
    pr_merged: bool                         # NUEVO: True si gh pr merge OK
    commands_skipped: list[str]
```

Campo por defecto `False` cuando no se intenta (safe mode, sin
`gh`, sin pr_url). `True` solo si `gh pr merge` exit 0.

### `finalize_task` flujo extendido

```python
def finalize_task(session, run, task, project) -> FinalizeResult:
    # ... pasos 1-3 de PR-V1-13 (commit, push, pr_create) ...
    pr_url = ...  # resultado del paso 3
    pr_merged = False

    # NUEVO: paso 4 — auto-merge si dangerous
    if (
        pr_url
        and getattr(project, "autonomy_mode", "safe") == "dangerous"
        and shutil.which("gh")
    ):
        rc, stdout, stderr = _run_cmd(
            ["gh", "pr", "merge", pr_url, "--squash", "--delete-branch"],
            cwd=project.local_path,
        )
        if rc == 0:
            pr_merged = True
            logger.info("auto-merged PR for task_id=%s", task.id)
        else:
            commands_skipped.append(
                f"gh_pr_merge_failed: {stderr[:500]} "
                f"(manual: gh pr merge {pr_url} --squash --delete-branch)"
            )
    elif pr_url and getattr(project, "autonomy_mode", "safe") == "safe":
        # safe mode: no-op (humano mergea manualmente)
        pass

    # ... persistir task.pr_url, devolver FinalizeResult ...
```

Comportamiento:
- **safe** + pr_url → FinalizeResult `pr_merged=False`, sin intento.
- **dangerous** + pr_url + `gh` → intenta merge.
  - Éxito → `pr_merged=True`.
  - Fail → log comando manual, `pr_merged=False`.
- **dangerous** + pr_url sin `gh` → `pr_merged=False` +
  `commands_skipped` con comando manual.
- **dangerous** sin pr_url (porque push falló o gh missing) →
  `pr_merged=False` sin entry nuevo (el skip ya se loggó antes).

### UI banner

Dentro de `ProjectDetail.tsx`, justo encima de la metadata (pre-
badge actual):

```tsx
{p.autonomy_mode === "dangerous" && (
  <Alert
    color="red"
    variant="filled"
    title="Dangerous mode"
    icon={<IconAlertTriangle size={18} />}
    mb="md"
  >
    Runs auto-merge PRs without review. Review carefully before
    enabling.
  </Alert>
)}
```

Usa `Alert` de Mantine y `IconAlertTriangle` de `@tabler/icons-react`
(ambos ya pre-aprobados en PR-V1-06a).

## Tests

### Backend nuevos en `test_finalize.py` (2-3 casos)

1. `test_dangerous_mode_runs_gh_pr_merge` — setup project con
   `autonomy_mode="dangerous"`, fake `gh pr create` devuelve URL,
   fake `gh pr merge` devuelve exit 0. `FinalizeResult.pr_merged
   == True`, `commands_skipped` sin entry de merge fail.
2. `test_safe_mode_skips_auto_merge` — project `autonomy_mode=
   "safe"`. `pr_merged == False`. `gh pr merge` **no** se invoca
   (mock assert cero calls para ese cmd).
3. `test_dangerous_mode_merge_failure_logs_manual_command` —
   dangerous + `gh pr create` OK, `gh pr merge` exit 1 con stderr.
   `pr_merged == False`, `commands_skipped` contiene fragmento
   "gh pr merge ... --squash --delete-branch".

### Frontend nuevos en `ProjectDetail.test.tsx` (2 casos)

1. `test_renders_dangerous_banner_when_mode_dangerous` — mock
   `useProject` devuelve project con `autonomy_mode="dangerous"`.
   Render asserts banner visible con texto "Dangerous mode".
2. `test_no_banner_when_mode_safe` — project con
   `autonomy_mode="safe"`. Banner no está en el DOM.

Usa `vi.stubGlobal`/`vi.mock` para hooks igual que
`TaskEventStream.test.tsx`.

### Baseline tras PR-V1-16

- Backend: **≥107 passed** (104 actuales + 3 finalize).
- Frontend: **≥8 passed** (6 actuales + 2 ProjectDetail).

## Criterio de hecho

- [ ] Project con `autonomy_mode="dangerous"` + verify OK + `gh`
  presente → PR creado + auto-merge + rama remota borrada.
- [ ] Project con `autonomy_mode="safe"` → PR creado, NO merge.
  Humano mergea manualmente.
- [ ] Project con `autonomy_mode="dangerous"` pero `gh pr merge`
  falla → `pr_url` persistido, `commands_skipped` con comando
  manual, task sigue `done`.
- [ ] Banner rojo visible en `/projects/:slug` cuando el modo es
  dangerous; invisible cuando safe.
- [ ] `pytest -q` completo → ≥107 passed.
- [ ] `npm test -- --run` → ≥8 passed.
- [ ] HANDBOOK sección "Dangerous mode (PR-V1-16)" con flow,
  seguridad, forma del `FinalizeResult`, banner UI.
- [ ] Codex ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests (sin HANDBOOK) ≤ **400**. Proyección
  ~250.

## Riesgos conocidos

- **`gh pr merge` deja el PR cerrado con `--delete-branch`.** Si
  algún hook del repo depende de la rama en vivo, se rompe. MVP
  asume repos sin hooks exóticos.
- **`--squash` es opinionated**. Usuario puede preferir
  `--rebase`/`--merge`. Follow-up con `autonomy_merge_strategy`
  columna. MVP: squash hardcoded.
- **Race con humano**: si el humano mergea a mano antes de que
  finalize lo haga, `gh pr merge` falla porque el PR ya está
  merged. Caemos al log sin drama; `commands_skipped` registra
  stderr.
- **Verificación post-merge**: verify ya pasó antes del merge.
  Si el merge introduce un conflicto contra main reciente, el
  target branch puede quedar roto. MVP no protege (riesgo
  explícito de dangerous mode).
- **Banner + badge redundantes**: banner es loud, badge es
  silencioso. Ambos coexisten por ahora. Si UX molesta, follow-up
  quita el badge.
- **Proyectos sin UI para cambiar autonomy_mode**: tiene que
  editarse vía PATCH API o DB. Follow-up añadir toggle modal.

## Notas para Claude Code

- Commits sugeridos (5):
  1. `feat(finalize): auto-merge pr when autonomy_mode dangerous`
  2. `test(finalize): dangerous mode merge success and failure`
  3. `feat(frontend): dangerous mode banner on project detail`
  4. `test(frontend): project detail banner vitest cases`
  5. `docs(v1): handbook dangerous mode section`
- Mantén `FinalizeResult` como frozen dataclass. Añadir
  `pr_merged: bool = False` con default para que los call-sites
  existentes compilen.
- `Alert` de Mantine con `color="red"` + `variant="filled"` para
  contraste alto. `IconAlertTriangle` del set ya instalado.
- En el test del banner, mockea `useProject` via
  `vi.stubGlobal("fetch", ...)` o monkey patch del hook.
- **Si algo del brief es ambiguo, PARA y reporta.**
