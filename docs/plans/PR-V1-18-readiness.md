# PR-V1-18 — Readiness: `/api/readiness` + página `/system`

**Semana:** 5
**Esfuerzo:** M
**Depende de:** PR-V1-17 mergeado.

## Qué

Check de salud del stack: un endpoint backend que devuelve 4
booleanos + detalle, y una ruta frontend que lo consume y muestra
"qué falta" de forma legible.

**Backend**: `GET /api/readiness` → JSON con 4 checks + resumen:

```json
{
  "db_ok": true,
  "claude_cli_ok": true,
  "git_ok": true,
  "gh_ok": false,
  "details": {
    "db": {"path": "/abs/path", "reachable": true},
    "claude_cli": {"path": "/usr/local/bin/claude", "found": true},
    "git": {"version": "git version 2.43.0"},
    "gh": {"found": false, "hint": "install from github.com/cli/cli"}
  }
}
```

**Frontend**: nueva ruta `/system` con tabla de 4 filas (una por
check) + badge verde/rojo + columna "qué falta" si el check falla
(extrae `hint` o genera mensaje por defecto).

## Por qué

SPEC §7: "`/system` — Readiness: DB OK, Claude CLI instalado +
autenticado, systemd unit corriendo, disk free. Read-only".
SPEC §9 Semana 5 cierra con página de readiness. Sin él, el
usuario no sabe si falta `gh` auth o si el `NIWA_CLAUDE_CLI`
apunta a un path obsoleto hasta que un run falla.

**Nota sobre scope del SPEC**: §7 lista también "systemd unit
corriendo" y "disk free". MVP omite ambos (el launcher CLI
`niwa-executor status` ya cubre systemd; disk free es cosmético).
Los 4 checks del brief son los que bloquean el pipeline real.

## Scope — archivos que toca

```
v1/backend/
├── app/
│   ├── api/
│   │   └── readiness.py                    # nuevo, ~90 LOC
│   └── services/
│       └── readiness_checks.py             # helpers puros, ~60 LOC
└── tests/
    └── test_readiness_api.py               # nuevo, 5 casos

v1/frontend/
├── src/
│   ├── App.tsx                             # +route /system
│   ├── api.ts                              # +tipo ReadinessResponse
│   └── routes/
│       └── SystemRoute.tsx                 # nuevo, ~80 LOC
└── tests/
    └── SystemRoute.test.tsx                # nuevo, 2 casos
```

**HARD-CAP 400 LOC netas código+tests** (sin HANDBOOK). Proyección
~320. Si excedes, PARAS.

## Fuera de scope (explícito)

- **No check de systemd / launchd**. `niwa-executor status` lo
  cubre desde PR-V1-15.
- **No check de disk free**. Cosmético, follow-up.
- **No auth check** del backend — binding local §2.
- **No check en vivo del proyecto deployado** (`/deploy/<slug>`).
  Follow-up.
- **No check de network externa** (GitHub API reachable, etc.).
  Solo local state.
- **No polling automático** desde UI. `useQuery` sin
  `refetchInterval`. Usuario hace refresh manual si quiere retest.
- **No endpoint de "reparar"**. Read-only.
- **No config editing UI**. SPEC §2 dice `config.toml` edit a mano.

## Dependencias nuevas

- **Ninguna**. FastAPI + stdlib `subprocess`/`shutil`; frontend
  reusa React Query + Mantine + Tabler icons.

## Contrato funcional

### Backend checks

1. **`db_ok`**: abre conexión al `Settings.db_path`; si
   `SELECT 1` devuelve → True. Atrapa `OperationalError`.
   `details.db.path` = path resuelto.
2. **`claude_cli_ok`**: `shutil.which(Settings.claude_cli or
   "claude")` devuelve path → True. **No** corre `claude
   whoami` u otro subcomando — el brief lo dice explícito (sería
   sondeo de red y puede ser caro). `details.claude_cli.path` =
   path resuelto o None; `found: bool`.
3. **`git_ok`**: `git --version` exit 0 → True. Captura stdout
   para `details.git.version`. Si `FileNotFoundError` → False.
4. **`gh_ok`**: `shutil.which("gh")` no None. Como en `finalize`,
   no corre `gh auth status` (ese sí es de red y lento para
   readiness).
   `details.gh.found: bool`; si False, `details.gh.hint: "install
   from github.com/cli/cli"`.

Todos los checks **best-effort** — si uno crashea internamente, se
captura y el campo queda `False` con `error: str` en details.

### Backend endpoint

```python
@router.get("/readiness", response_model=ReadinessResponse)
def get_readiness() -> ReadinessResponse:
    return ReadinessResponse(
        db_ok=_check_db(),
        claude_cli_ok=_check_claude_cli(),
        git_ok=_check_git(),
        gh_ok=_check_gh(),
        details=_build_details(),
    )
```

Pydantic `ReadinessResponse` en `app/schemas/readiness.py` (o
inline en el router si cabe en LOC budget).

### Frontend `/system` route

Componente usa `useQuery({ queryKey: ["readiness"], queryFn: ... })`
sin `refetchInterval`. Muestra:

- Título "System readiness".
- Botón "Refresh" que invalida la query.
- Tabla Mantine con 4 filas: `Check | Status | Details`.
  - Status: `<Badge color="green">OK</Badge>` o `<Badge color="red">Missing</Badge>`.
  - Details: texto desde `data.details.<check>`; si falla, muestra
    el `hint` si existe, o mensaje por defecto tipo "check failed
    — see server logs".

Loading skeleton mientras `isLoading`. Error alert si `isError`.

### Routing

`App.tsx` añade `<Route path="/system" element={<SystemRoute/>}/>`.
`AppShell` recibe un link en el header opcional (si cabe, si no,
se navega manualmente).

## Tests

### Backend — `tests/test_readiness_api.py` (5 casos)

Todos mockean `shutil.which` + `subprocess.run` con monkeypatch;
DB real de fixture.

1. `test_all_checks_ok` — todas las deps existen (mock which y
   subprocess exit 0). Response con los 4 booleanos True y
   details completos.
2. `test_claude_cli_missing` — `shutil.which("claude")` → None.
   `claude_cli_ok=False`, `details.claude_cli.path=None`.
3. `test_gh_missing_hints_install` — `shutil.which("gh")` →
   None. `gh_ok=False`, `details.gh.hint` presente.
4. `test_git_exception_captured` — `subprocess.run` raises
   `FileNotFoundError`. `git_ok=False`; no crash.
5. `test_db_unreachable_returns_false` — monkeypatch del engine
   para que `SELECT 1` lance. `db_ok=False`, `details.db.error`
   con mensaje.

### Frontend — `tests/SystemRoute.test.tsx` (2 casos)

Mock `fetch` con `vi.stubGlobal` o similar para devolver
response JSON.

1. `test_renders_all_ok_checks` — 4 checks verde + details.
2. `test_renders_missing_gh_with_hint` — `gh_ok=False` + hint
   visible en la fila correspondiente.

**Baseline tras PR-V1-18**: backend 118 → **≥123 passed**.
Frontend 8 → **10 passed**.

## Criterio de hecho

- [ ] `GET /api/readiness` devuelve JSON con 4 booleanos + details.
- [ ] `/system` muestra tabla con badges y details; botón refresh
  invalida la query.
- [ ] `pytest -q tests/test_readiness_api.py` → 5 passed.
- [ ] `npm test -- --run` → ≥10 passed.
- [ ] Backend `pytest -q` completo → ≥123 passed.
- [ ] HANDBOOK sección "Readiness (PR-V1-18)" con endpoint
  contract, qué checks incluye, por qué no systemd/disk/auth, flow
  UI.
- [ ] Codex ejecutado. Blockers resueltos antes del merge.
- [ ] LOC netas código+tests ≤ **400**. Proyección ~320.

## Riesgos conocidos

- **`subprocess.run` en el endpoint async**: FastAPI por default
  ejecuta handlers `def` en threadpool, así que `subprocess.run`
  síncrono es seguro. Si migras a `async def`, usar
  `asyncio.to_thread`.
- **`claude_cli_ok=True` cuando el path existe pero no está
  autenticado**: el check no prueba auth real. Documentado como
  known limitation. Follow-up podría añadir un modo `deep` con
  `claude auth status` (más lento).
- **DB check hace `SELECT 1`**: barato. No toca ninguna tabla.
- **Frontend usa React Query sin refetchInterval**: usuario debe
  apretar refresh para actualizar. Aceptable MVP.
- **Mensaje "hint" puede desactualizarse**: MVP hardcodea strings
  cortos; follow-up podría traducir o variar por OS.

## Notas para Claude Code

- Commits sugeridos (5):
  1. `feat(api): readiness checks module`
  2. `feat(api): GET /api/readiness endpoint`
  3. `feat(frontend): system readiness route`
  4. `test(api): readiness endpoint cases`
  5. `test(frontend): system route vitest cases`
  6. `docs(v1): handbook readiness section`
- Backend: helpers puros en `services/readiness_checks.py` para
  testearlos sin tocar el endpoint. El endpoint solo compone.
- Frontend: reutiliza patrón de `useProjects` / `useTasks` para
  React Query. `SystemRoute` sin layout complejo — solo tabla
  y botón.
- Si cabe en LOC, añade un enlace `System` al `AppShell` header;
  si no, dejar para follow-up.
- **Si algo ambiguo, PARA y reporta.**
