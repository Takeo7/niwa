# PR-V1-28 — In-app help & first-project guidance

**Tipo:** FEATURE (UX onboarding)
**Esfuerzo:** S-M
**Depende de:** PR-V1-27 mergeado (ya en main)

## Qué

Tres piezas de UX para que un usuario nuevo (en concreto, la
pareja del autor) pueda usar Niwa sin abrir el README. Las tres
viven en el frontend, ningún cambio backend.

1. **Empty state guía** en la lista de proyectos cuando
   `projects.length === 0`: card con los 3 pasos del onboarding +
   botón directo a "Nuevo proyecto".
2. **Página `/help`** dedicada con el contenido completo de
   onboarding: modelo mental, quickstart, anatomía de un proyecto,
   estados de task, modos. Replica el README adaptado a UI con
   bloques `<Code>` copiables.
3. **Helper text** bajo el campo `local_path` del modal "Nuevo
   proyecto": "Path to a git repo already cloned on your machine.
   Niwa won't clone for you — clone first, then paste the
   absolute path here."

## Por qué

Smoke real con el segundo usuario (2026-04-25): tras instalar
Niwa, abrió la UI, le dio "Nuevo proyecto" y no entendió por qué
le pedía un `local_path`. El modelo mental "Niwa trabaja sobre
repos ya clonados localmente, no clona desde GitHub" no es obvio
para alguien que viene de Vercel/Linear/Replit donde el patrón es
"conectar cuenta → importar repo".

El README cubre esto pero está fuera de la UI. Un usuario que
abre la app no debe necesitar abrir el repo en GitHub para saber
qué hacer.

## Scope — archivos que toca

```
frontend/src/
├── routes/
│   └── HelpRoute.tsx                  # NUEVO ruta /help
├── features/
│   ├── help/
│   │   ├── HelpPage.tsx               # NUEVO contenido onboarding
│   │   └── HelpPage.test.tsx
│   └── projects/
│       ├── ProjectList.tsx            # add empty state
│       └── ProjectCreateModal.tsx     # helper text bajo local_path
├── shared/
│   └── AppShell.tsx                   # link "Help" en header
└── App.tsx                            # registrar ruta /help
```

**Hard-cap: 250 LOC** código + tests. Sin contar contenido
estático del help (texto del onboarding, que va en el componente
y no es lógica).

## Fuera de scope

- No clone-from-GitHub wizard (eso sí sería 1-2 semanas, candidato
  v1.1+).
- No videos/screenshots — todo texto + bloques de código copiables.
- No internacionalización — inglés (consistente con README).
- No tooltip persistente / popover guiado paso a paso (Joyride
  etc.) — overkill para MVP.
- No cambios backend.

## Contrato — qué muestra cada pieza

### Empty state en ProjectList

Cuando `projects.length === 0`:

```
┌────────────────────────────────────────────────┐
│ 👋 Welcome to Niwa                             │
│                                                │
│ Niwa runs Claude Code on your local git        │
│ repos. To get started:                         │
│                                                │
│ 1. Clone a repo to your machine if you         │
│    haven't yet:                                │
│                                                │
│    git clone https://github.com/you/your-repo  │
│    cd your-repo                                │
│                                                │
│ 2. Create a project pointing at it.            │
│                                                │
│    [+ New project]                             │
│                                                │
│ Need more detail? See [Help] for the full      │
│ onboarding guide.                              │
└────────────────────────────────────────────────┘
```

Mantine `Card` + `Title` + `Text` + `Code` (block) +
`Button.Filled`. Click en "+ New project" abre el mismo modal
que el botón normal. Click en "Help" navega a `/help`.

### Página `/help`

Estructura con `Tabs` o `Stack` simple (preferir Stack — menos
cliquear). Secciones:

**1. What Niwa does**

> Niwa is a local autonomous code agent. You describe a task in
> natural language; Niwa creates a branch in your repo, runs
> Claude Code to do the work, verifies the result, commits, and
> (optionally) opens a PR via the GitHub CLI.
>
> **It runs entirely on your machine.** Your code never leaves
> the laptop. Niwa needs you to clone the repos yourself — it
> doesn't connect to GitHub to import them.

**2. Quickstart (3 steps)**

Tres bloques numerados, cada uno con `Code` copiable:

```
1. Clone a repo to your machine

   git clone https://github.com/you/your-repo
   cd your-repo
   git status   # working tree must be clean
```

```
2. Create a project

   In the projects list, click "New project" and fill:
     • slug: short id, e.g. "playground"
     • name: human-readable label
     • kind: library / web-deployable / script
     • local_path: absolute path of your clone
     • git_remote: optional, GitHub URL for auto PRs
     • autonomy_mode: safe (default) or dangerous
```

```
3. Create your first task

   Inside the project, click "New task" and describe the work
   in natural language, e.g.:

     "Add a section to the README explaining how to run tests."

   Watch the run stream live. When it ends with status `done`,
   check your repo for the new branch.
```

**3. Project kinds**

Tabla pequeña explicando los 3 valores de `kind`:
- `library`: Niwa runs the project's tests after writing code.
- `web-deployable`: como library + serves built output at
  `/api/deploy/<slug>/`.
- `script`: skips the test step (for one-shot helpers).

**4. Task states**

Lista con bullet points:
- `inbox`: created but not queued for execution.
- `queued`: waiting for the executor to pick it up.
- `running`: executor is actively working.
- `waiting_input`: Claude asked you something. Reply in the
  task detail page to resume.
- `done`: completed and verified.
- `failed`: didn't pass verification (artifacts missing, tests
  failed, etc.).
- `cancelled`: stopped manually.

**5. Autonomy modes**

- `safe` (default): Niwa opens a PR; you merge.
- `dangerous`: Niwa auto-merges via `gh pr merge --squash` after
  verify passes. Banner rojo en ProjectDetail cuando este modo
  está activo (ya existe en PR-V1-16).

**6. Common gotchas**

- "Working tree clean" required before creating a task.
- The branch is created from the repo's default branch
  (`main`/`master`), not from your current checkout.
- `gh` CLI not installed → no auto-open of PRs (status will say
  `gh_missing`); other steps still work.

**7. Architecture / spec links**

- Full spec: link a `docs/SPEC.md` en el repo (URL fija al
  branch `main` en GitHub).
- Roadmap v1.1: link a `docs/plans/FOUND-20260422-onboarding.md`.

### Helper text en ProjectCreateModal

Bajo el campo `local_path`, usar la prop `description` de Mantine
`TextInput`:

```
description="Absolute path to a git repo already cloned on your
            machine. Niwa won't clone for you — clone first, then
            paste the path here."
```

Una línea, no se hace en bullet ni en card. Visible siempre que
el modal esté abierto.

### Header AppShell

Añadir un `NavLink` al header (junto a los existentes) llamado
"Help" que navega a `/help`. Icono `IconQuestionMark` o
`IconHelpCircle` de tabler-icons (ya disponibles).

## Tests

- **`HelpPage.test.tsx`** (~30 LOC):
  - render → renderiza al menos los headings "What Niwa does",
    "Quickstart", "Task states".
  - todos los bloques `<Code>` con comandos bash son copiables
    (verificar que existen en el DOM).
- **`ProjectList.test.tsx`** (extender el existente, +1 caso):
  - mock con `projects=[]` → renderiza el empty state con texto
    "Welcome to Niwa".
  - mock con `projects=[{...}]` → NO renderiza empty state
    (regression).

**Baseline tras el fix:** 152 + 0 (no toca backend) ; frontend
12 + 3 nuevos = **15 passed frontend**.

## Criterio de hecho

- [ ] Smoke manual: cerrar Niwa, borrar todos los proyectos de
      la DB, recargar UI → empty state visible con los 3 pasos
      y el botón "+ New project".
- [ ] Click en "Help" del header → navega a `/help`, contenido
      visible y legible.
- [ ] Click en "+ New project" en empty state → abre modal con
      helper text bajo `local_path`.
- [ ] `npm test -- --run` → 15 passed frontend.
- [ ] `pytest -q` → 152 passed backend (sin regresión).
- [ ] Codex-reviewer ejecutado.

## Riesgos conocidos

- **Contenido textual queda hardcoded en el componente.** Si en
  v1.1 cambia algo del flow, hay que editar `HelpPage.tsx` y el
  README a la vez. Aceptable — el coste de un sistema i18n /
  CMS es desproporcionado para 1 página.

## Notas para el implementador

- Los bloques `<Code>` para comandos bash usan
  `<Code block>...</Code>` de Mantine. Para inline (paths,
  nombres), `<Code>...</Code>` sin `block`.
- El empty state del ProjectList SOLO se muestra cuando la
  query carga y devuelve `[]`. Mientras `isLoading`, mostrar
  loader normal.
- Commits sugeridos:
  1. `feat(frontend): help page route + content`
  2. `feat(frontend): empty state guidance in project list`
  3. `feat(frontend): helper text under local_path field`
  4. `feat(frontend): help link in app shell header`
  5. `test(frontend): coverage for help page and empty state`
