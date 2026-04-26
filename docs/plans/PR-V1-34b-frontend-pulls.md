# PR-V1-34b — Frontend project pulls (Tabs + PullsTab + tests)

**Tipo:** FEATURE — capa frontend del PR-V1-34
**Esfuerzo:** S
**Depende de:** PR-V1-34a mergeado (consume su endpoint
`/api/projects/{slug}/pulls` con contrato Pydantic snake_case)
**Hijo de:** PR-V1-34 original

## Qué

Sólo la capa frontend de PR-V1-34: Tabs Mantine en
`ProjectDetail`, componente `PullsTab`, hook de api, y tests.
Consume el contrato Pydantic que cierra 34a.

## Por qué del split

Ver `FOUND-20260426-loc-cap-pattern.md` muestra 3. PR-V1-34
monolítico midió 551 LOC, así que se partió por capa. 34a fija
el contrato API con schemas Pydantic; 34b lo consume sin tocar
backend.

## Importante: NO cherry-pick directo

El frontend del PR-V1-34 monolítico (rama abandonada
`claude/v1-pr-34-project-pulls-view`) está escrito asumiendo
JSON raw de `gh` (camelCase: `headRefName`, `createdAt`,
`statusCheckRollup` array, lógica de prioridad de checks
calculada en frontend).

34a se rehízo durante codex review (ver
`FOUND-20260426-spec-deviation.md`) para devolver el contrato
Pydantic snake_case del brief original con `check_state`
colapsado server-side. Por tanto, **34b reescribe** `PullsTab`
contra el contrato Pydantic — no cherry-pickea el componente
del monolítico.

Ventajas de la reescritura:
- Componente más simple (no calcula prioridad de checks).
- Tipos TS reflejan el OpenAPI generado por FastAPI a partir
  de `PullRead`.
- Si el JSON de `gh` cambia, sólo 34a se ajusta — 34b queda
  estable.

## Scope

```
frontend/src/features/projects/api.ts             # +listPulls + types snake_case (~50 LOC)
frontend/src/features/projects/ProjectDetail.tsx  # Mantine Tabs (~45 LOC delta)
frontend/src/features/projects/PullsTab.tsx       # NUEVO (~120 LOC)
frontend/tests/PullsTab.test.tsx                  # NUEVO (~50 LOC)
```

**Hard-cap: 310 LOC** (estimado, igual que el split original).

## Fuera de scope

- Backend → ya en 34a.
- Botón "merge" en cada fila → PR-V1-35.
- Filtros adicionales (label, autor, etc.) → v1.2+.

## Contrato consumido

Endpoint cerrado en 34a (mergeado en `main`):

```
GET /api/projects/{slug}/pulls?state=open|closed|all&include_all=false
→ 200 PullsResponse {
    pulls: [{
      number: number,
      title: string,
      state: "OPEN" | "CLOSED" | "MERGED",
      url: string,
      mergeable: "MERGEABLE" | "CONFLICTING" | "UNKNOWN",
      checks: { state: "failing" | "pending" | "passing" | "none" },
      head_ref_name: string,
      created_at: ISO datetime,
      updated_at: ISO datetime,
    }],
    warning?: "no_remote" | "invalid_remote",
  }
→ 503 { error: "gh_missing" }
→ 502 { error: "gh_failed", detail: string }
→ 504 { error: "gh_timeout", detail: string }
```

Los tipos TypeScript en `api.ts` deben reflejar esto literal:
snake_case en `head_ref_name`, `created_at`, `updated_at`;
casing canonical de `gh` (mayúscula) en `state` y `mergeable`;
`check_state` ya colapsado en `checks.state`.

## Frontend

### `ProjectDetail.tsx` — Tabs

Reemplazar el contenido actual del detalle por Mantine `Tabs`:

- Tab `tasks` (default, contiene el bloque actual entero —
  lista de tareas + modal de crear).
- Tab `pulls` (contiene `<PullsTab projectSlug={slug} />`).

Mantener el header del proyecto (nombre, slug, kind) por encima
de las Tabs.

### `PullsTab.tsx`

`useQuery` con:
- `queryKey: ['projects', slug, 'pulls', { state, include_all }]`.
- `enabled: isTabActive` (sólo fetch cuando la tab está visible —
  derivar de `Tabs.value`).
- `refetchInterval: 60000`.

Tabla Mantine con columnas:

| # | Title | State | Mergeable | Checks | Created | Link |
|---|-------|-------|-----------|--------|---------|------|

- `State`: `Badge` color por estado (open=blue, merged=green,
  closed=gray).
- `Mergeable`: badge color (mergeable=green, conflicting=red,
  unknown=gray).
- `Checks`: icon + tooltip directo desde `pull.checks.state`
  (`passing` / `failing` / `pending` / `none`). NO recalcular
  en frontend.
- `Created`: relative time (`formatDistanceToNow` o util ya
  existente).
- `Link`: anchor "Open" → `pull.url` target=_blank.

Empty state: "No PRs yet — Niwa opens a PR for each task that
finishes when this project has a `git_remote` configured."

Si la respuesta tiene `warning: "no_remote"`: mensaje
"Configure `git_remote` on this project to see PRs."

Si la respuesta tiene `warning: "invalid_remote"`: mensaje
"Project remote is not on GitHub — pulls view supports github.com only."

Si HTTP 503 (`gh_missing`): mensaje "Install the GitHub CLI to
see PRs: `brew install gh && gh auth login`".

Si HTTP 502/504 (`gh_failed` / `gh_timeout`): toast con el
`detail` y botón retry.

### `api.ts`

Añadir:

```typescript
export type PullCheckState = 'failing' | 'pending' | 'passing' | 'none';

export type PullRead = {
  number: number;
  title: string;
  state: 'OPEN' | 'CLOSED' | 'MERGED';
  url: string;
  mergeable: 'MERGEABLE' | 'CONFLICTING' | 'UNKNOWN';
  checks: { state: PullCheckState };
  head_ref_name: string;
  created_at: string;
  updated_at: string;
};

export type PullsResponse = {
  pulls: PullRead[];
  warning?: 'no_remote' | 'invalid_remote';
};

export async function listPulls(slug: string, opts?: {
  state?: 'open' | 'closed' | 'all'; include_all?: boolean;
}): Promise<PullsResponse> { /* fetch wrapper */ }
```

## Tests

`frontend/tests/PullsTab.test.tsx`:

1. `test_pulls_tab_renders_table_with_data`: mock `listPulls`
   con 2 PRs (uno con `checks.state: "failing"`, otro
   `"passing"`) → tabla con 2 filas, badges correctos, icono
   de check correcto, link presente.
2. `test_pulls_tab_shows_install_message_when_gh_missing`: mock
   listPulls que rejecta con 503 `gh_missing` → mensaje de
   install visible.

(Si la implementación natural sugiere un tercer test —
e.g. `no_remote` warning — añadir; objetivo del split no es
recortar tests.)

## Criterio de hecho

- [ ] Tab "Pull requests" visible en project detail.
- [ ] Lista de PRs abiertos por Niwa con estado correcto desde
      el contrato snake_case.
- [ ] `checks.state` se renderiza directamente (no recalcular
      prioridad client-side).
- [ ] Refetch automático cada 60s mientras la tab está activa.
- [ ] Mensaje claro si `gh` no está instalado, si no hay
      `git_remote`, si remote no es GitHub, o si `gh` falla.
- [ ] `npm test` pasa con +2 (mínimo) nuevos tests.
- [ ] Codex ejecutado.
- [ ] LOC final ≤ 310 sin lockfile.

## Riesgos

- **`enabled: isTabActive` correctamente derivado:** si la
  query hace fetch aunque la tab esté oculta, multiplicamos
  requests. Usar el `Tabs.value` como state controlled o
  `Tabs.onChange`.
- **Polling 60s indefinido:** mientras el usuario tiene la tab
  abierta, hay 1 req/min. Acceptable; ver brief original 34.

## Notas para el implementador

- **NO cherry-pick** del frontend del monolítico — el contrato
  cambió.
- Sí puedes reusar la estructura general (qué columnas, qué
  empty states) del componente del monolítico como referencia
  visual, pero **el contrato consumido y la lógica de checks
  son distintos**. Lee 34a mergeado en `main` para confirmar.
- Rama nueva: `claude/pr-V1-34b-frontend-pulls` desde
  `origin/main` actualizada (contiene ya 34a mergeado).
- Si ves divergencias entre el contrato listado arriba y lo
  que devuelve `/api/projects/{slug}/pulls` en `main`, paras y
  consultas — no rehagas el contrato unilateralmente.
