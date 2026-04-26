# PR-V1-34a — Backend project pulls (service + endpoint + tests)

**Tipo:** FEATURE — capa backend del PR-V1-34
**Esfuerzo:** S
**Depende de:** ninguna (consume `gh` CLI)
**Hijo de:** PR-V1-34 original (split por capa, ver
`FOUND-20260426-loc-cap-pattern.md` muestra 3)

## Qué

Sólo la capa backend de PR-V1-34: servicio que envuelve `gh pr
list`, endpoint REST, y tests unitarios. Sin frontend.

El frontend va en PR-V1-34b, que arranca después de mergear este.

## Por qué del split

El PR-V1-34 monolítico midió 551 LOC (>400 hard-cap). El brief
original dividía claramente entre backend y frontend, así que el
split por capa es el corte natural — mismo patrón que se aplicó
en PR-V1-33 (33a-i, 33a-ii, 33b). 34a fija el contrato API que
34b consume.

## Scope

```
backend/app/api/projects.py             # +endpoint /pulls (~65 LOC)
backend/app/services/github_pulls.py    # NUEVO: gh wrapper (~102 LOC)
backend/tests/test_github_pulls.py      # NUEVO (~70 LOC)
```

**Hard-cap: 240 LOC** (estimado real del split actual).

## Fuera de scope

- Todo el frontend: tab nueva, PullsTab, api.ts hook, tests
  frontend → 34b.
- No mergea desde la UI → PR-V1-35.
- No autenticación con GitHub OAuth — usa `gh` CLI ya
  autenticado, herencia del usuario que corre el backend.

## Endpoint

### `GET /api/projects/{slug}/pulls?state=open|closed|all&include_all=false`

Contrato exacto que debe quedar fijado para que 34b lo consuma:

**Inputs:**
- Path: `slug` del proyecto.
- Query `state`: `open` (default), `closed`, o `all`.
- Query `include_all`: bool (default `false`). Si `true`, no
  filtra por `headRefName`. Si `false`, sólo devuelve PRs cuya
  `headRefName` empiece por `niwa/task-`.

**Comportamiento:**
1. Lee `project.git_remote`. Si NULL → 200 con
   `{"warning": "no_remote", "pulls": []}`.
2. Verifica `shutil.which("gh")`. Si no → 503 con
   `{"error": "gh_missing"}`.
3. Detecta `owner/repo` desde `project.git_remote` (regex que
   acepta `git@github.com:owner/repo.git`,
   `https://github.com/owner/repo.git`, sin `.git` final).
4. Ejecuta:
   ```
   gh pr list --repo <owner>/<repo> --state <state> \
     --json number,title,state,url,mergeable,statusCheckRollup,createdAt,updatedAt,headRefName \
     --limit 30
   ```
5. Si `include_all=false`, filtra los que `headRefName` empieza
   por `niwa/task-`.
6. Devuelve `{"pulls": [...]}` parseado.

**Timeout** del subprocess: 15s. Si timeout → 504.
**Error parsing/exec** → 502 con `{"error": "gh_failed", "detail": "..."}`.

### Schema response (Pydantic)

```python
class PullCheck(BaseModel):
    state: Literal["passing", "failing", "pending", "none"]

class PullRead(BaseModel):
    number: int
    title: str
    state: str  # "OPEN" | "CLOSED" | "MERGED"
    url: str
    mergeable: str  # "MERGEABLE" | "CONFLICTING" | "UNKNOWN"
    checks: PullCheck
    head_ref_name: str
    created_at: datetime
    updated_at: datetime

class PullsResponse(BaseModel):
    pulls: list[PullRead]
    warning: str | None = None
```

`statusCheckRollup` viene como array de check runs; el servicio
lo colapsa a un único `PullCheck` con prioridad
`failing > pending > passing > none`.

## Tests

`backend/tests/test_github_pulls.py`:

1. `test_list_pulls_filters_to_niwa_branches`: mock
   `subprocess.run` devolviendo 5 PRs, 3 con `headRefName`
   empezando en `niwa/`, 2 no. Endpoint con `include_all=false`
   devuelve 3.
2. `test_list_pulls_returns_warning_when_no_remote`: proyecto sin
   `git_remote` → 200 con warning + array vacío.
3. `test_list_pulls_returns_503_when_gh_missing`: mock
   `shutil.which` → None → 503.

(Tests adicionales que aparezcan en el cherry-pick — p.ej. el
parse del statusCheckRollup — se conservan; objetivo del split
no es recortar tests.)

## Criterio de hecho

- [ ] Endpoint `GET /api/projects/{slug}/pulls` responde con el
      contrato fijado arriba.
- [ ] `pytest -q` pasa con +3 (mínimo) nuevos tests.
- [ ] Codex ejecutado (subprocess + parsing externo, merece review).
- [ ] LOC final ≤ 240 sin lockfile.
- [ ] Cherry-pick limpio desde rama abandonada
      `claude/v1-pr-34-project-pulls-view`.

## Riesgos

- **Permisos del `gh` server-side:** subprocess hereda
  credenciales del user que corre el backend. Si el user no
  autenticó `gh`, el comando falla con exit ≠ 0. El servicio
  debe distinguir "gh ausente" (503) de "gh falla" (502).
- **Rate limit GitHub:** 60 req/h sin auth, 5000/h con auth. No
  aplica restricción server-side; refetch policy queda en 34b.
- **Regex del git_remote:** soportar SSH y HTTPS, con o sin
  `.git`. Si falla regex → 502 con detail descriptivo.

## Notas para el implementador

- Hay implementación en local en
  `claude/v1-pr-34-project-pulls-view` (commits `d7ea2ff` y
  `6a02cb5`). Cherry-pick selectivo de los 3 ficheros backend.
- Rama nueva: `claude/pr-V1-34a-backend-pulls` desde
  `origin/main` actualizada.
- Si la implementación local supera el cap por ≥ 30 LOC tras
  cherry-pick, paras y consultas (no fix-up automático).
