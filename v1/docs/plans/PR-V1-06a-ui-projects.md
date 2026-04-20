# PR-V1-06a — UI: shell + routing + projects CRUD

**Semana:** 1.5 (inserción táctica; primera mitad del 06 original)
**Esfuerzo:** M
**Depende de:** PR-V1-05 mergeado. Supersede junto con 06b a
`PR-V1-06-ui-minimal.md`.

## Qué

Primer PR de UI real: el shell de la app (Mantine + React Router +
React Query + Notifications) más todo lo de **projects** — lista en
`/`, modal de creación, y ruta de detalle `/projects/:slug` que
muestra nombre + kind (sin tareas todavía). Tests Vitest de la lista
de proyectos. Backend intacto.

## Por qué

Partido de `PR-V1-06` original para quedarse bajo el hard-cap de
600 LOC. Esta mitad entrega la plataforma base de UI (shell + tipos
+ providers) y deja un flujo demostrable end-to-end con proyectos.
La mitad de **tasks** (list + create + delete + polling) vive en
`PR-V1-06b-ui-tasks.md`.

## Scope — archivos que toca

```
v1/frontend/
├── package.json                            # +3 deps (ver abajo)
├── package-lock.json                       # regenerado
├── vite.config.ts                          # server.proxy /api → :8000
├── src/
│   ├── main.tsx                            # MantineProvider + Notifications
│   │                                       # + QueryClientProvider + BrowserRouter
│   ├── App.tsx                             # <Routes> con / y /projects/:slug
│   ├── api.ts                              # apiFetch + tipos Project*, AutonomyMode, ProjectKind
│   ├── shared/
│   │   └── AppShell.tsx                    # header "Niwa v1" + <Outlet/>
│   ├── routes/
│   │   ├── ProjectsRoute.tsx               # "/" → <ProjectList/>
│   │   └── ProjectDetailRoute.tsx          # "/projects/:slug" → <ProjectDetail/>
│   └── features/projects/
│       ├── api.ts                          # useProjects, useProject, useCreateProject
│       ├── ProjectList.tsx                 # cards + "Nuevo proyecto"
│       ├── ProjectCreateModal.tsx          # @mantine/form + POST + toast
│       └── ProjectDetail.tsx               # nombre + kind, placeholder "tareas: en PR-V1-06b"
└── tests/
    ├── setup.ts                            # vitest-dom-like setup mínimo
    ├── renderWithProviders.tsx             # QueryClient + MemoryRouter wrapper
    └── ProjectList.test.tsx                # 2 casos del brief
```

**Límite duro:** 600 LOC. Si vas a exceder, PARA.

## Fuera de scope (explícito)

- **No hay tasks.** Ni lista, ni create, ni delete, ni polling.
  Todo eso es **06b**. `ProjectDetail` muestra un placeholder
  ("Tareas — llegan en PR-V1-06b") para que no haya link roto.
- No se toca backend.
- No hay detalle de tarea (ruta `/projects/:slug/tasks/:id`) —
  llega en Semana 2 con el stream.
- No hay `PATCH` de proyecto desde UI.
- No hay página `/system`.
- No hay auth.

## Dependencias nuevas

- **npm** (ya declaradas pre-aprobadas en el 06 original):
  - `@mantine/form@7.17.8`
  - `@mantine/notifications@7.17.8`
  - `@tabler/icons-react@3.41.1`
- **devDependencies** necesarias para los tests (pre-aprobadas
  dentro del stack testing del frontend; el brief 06 original no
  las listó explícitas — si alguna falta ya en `package.json`,
  puedes añadirlas):
  - `@testing-library/react@16.x` (ya está en v1).
  - `jsdom` (ya está).

Si necesitas una dep no listada arriba, PARA y pregunta.

## Tests

Nuevos en `v1/frontend/tests/ProjectList.test.tsx` (2 casos del
brief 06 original):

1. `renders empty state` — con fetcher mockeado devolviendo `[]`,
   se ve "No projects yet" (o equivalente literal del componente).
2. `renders two project cards` — con fetcher mockeado devolviendo 2
   proyectos, ambos aparecen con su `name`.

**Baseline tras PR-V1-06a:**
- Backend: 44 passed (sin tocar).
- Frontend: **2 passed** (de 0 actuales).

## Criterio de hecho

- [ ] `make -C v1 dev` arranca backend :8000 + frontend :5173 sin
  errores.
- [ ] `http://localhost:5173/` carga el shell Mantine con el header
  "Niwa v1" y la lista de proyectos.
- [ ] Con 0 proyectos, lista muestra el empty state.
- [ ] "Nuevo proyecto" abre modal; submit con payload válido hace
  `POST /api/projects`, muestra toast de éxito, refresca la lista.
- [ ] Click en card navega a `/projects/:slug` y muestra
  nombre + kind + placeholder de tareas.
- [ ] Proxy de Vite: `GET http://localhost:5173/api/projects` pasa
  a `localhost:8000` sin CORS.
- [ ] `cd v1/frontend && npm test -- --run` → **2 passed**.
- [ ] `cd v1/backend && pytest -q` → 44 passed (sin regresión).
- [ ] HANDBOOK actualizado con sección "Frontend" describiendo
  shell + proyectos + decisión del proxy.
- [ ] Codex-reviewer ejecutado por el orquestador sobre el diff,
  comentado en el PR.

## Riesgos conocidos

- **Proxy de Vite vs tests.** El proxy solo opera en `vite dev`;
  los tests Vitest no pasan por él. `apiFetch` debe usar `/api`
  relativo y en tests se mockea `fetch` o el hook completo. No
  hagas `globalThis.fetch = ...` directamente si puedes mockear el
  hook.
- **StrictMode + React Query.** El doble-render de StrictMode no
  debe provocar dobles POST — las mutations solo se ejecutan al
  submit del form, no en el render.
- **LOC creep por tipos.** `api.ts` puede crecer si se duplican
  shape types; mantén un solo lugar para `Project`, `ProjectKind`,
  `AutonomyMode`, `ProjectCreatePayload`.

## Notas para el implementador

- Commits sugeridos:
  1. `chore(frontend): add mantine form/notifications, tabler icons`
  2. `feat(frontend): app shell with router and providers`
  3. `feat(frontend): projects list and create modal`
  4. `feat(frontend): project detail placeholder for tasks`
  5. `test(frontend): vitest cases for projects list`
  6. `docs(v1): handbook frontend section`
- El placeholder de tareas en `ProjectDetail.tsx` debe ser una sola
  línea: `<Text c="dimmed">Tareas — próximamente en PR-V1-06b.</Text>`.
  06b lo reemplaza.
- `@mantine/form` con `isNotEmpty` + `hasLength`; sin Zod/Yup.
- `apiFetch` genérico en `api.ts` que devuelve `json()`; manejar
  ≥400 arrojando con `{status, body}`.
- El test usa `renderWithProviders` que monte:
  - `QueryClientProvider` con `{defaultOptions: {queries: {retry:
    false}}}`.
  - `MemoryRouter` con el initial entry que haga falta.
  - `MantineProvider` con `theme={undefined}`.
- Esfuerzo M → codex review obligatorio antes del merge.
