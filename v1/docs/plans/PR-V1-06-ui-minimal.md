# PR-V1-06 — UI mínima: listar y crear proyectos y tareas

**Semana:** 1.5 (inserción táctica antes de Semana 2)
**Esfuerzo:** M
**Depende de:** PR-V1-01 a PR-V1-05 (todos mergeados)

## Qué

UI funcional mínima en React que consume el backend que ya existe.
Permite al usuario: ver lista de proyectos, crear un proyecto, abrir
el detalle de un proyecto, ver sus tareas, crear una tarea, borrar
tareas en estados terminales. La ejecución la sigue haciendo el
executor echo — el propósito de este PR es tener algo usable en el
navegador antes de meter Claude Code real en Semana 2.

## Por qué

Semana 1 entregó un backend sólido pero un frontend vacío
(`App.tsx` solo renderiza un título). Sin UI no se puede probar el
pipeline end-to-end sin `curl`, y no hay nada demostrable al segundo
usuario (la pareja del autor). Insertar este PR antes de Semana 2
aísla "UI de CRUD" de "UI de stream en vivo" (que llega con adapter
real en Semana 2) y hace ambos PRs más pequeños y revisables.

## Scope — archivos que toca

```
v1/frontend/
├── package.json                              # +2 deps (ver abajo)
├── src/
│   ├── main.tsx                              # envuelve en BrowserRouter
│   ├── App.tsx                               # rewrite → rutas
│   ├── api.ts                                # extendido con tipos base
│   ├── routes/
│   │   ├── ProjectsRoute.tsx                 # "/"
│   │   └── ProjectDetailRoute.tsx            # "/projects/:slug"
│   ├── features/
│   │   ├── projects/
│   │   │   ├── api.ts                        # fetchers + mutations
│   │   │   ├── ProjectList.tsx
│   │   │   ├── ProjectCreateModal.tsx
│   │   │   └── ProjectDetail.tsx
│   │   └── tasks/
│   │       ├── api.ts
│   │       ├── TaskList.tsx                  # embebido en ProjectDetail
│   │       └── TaskCreateModal.tsx
│   └── shared/
│       └── AppShell.tsx                      # header simple + <Outlet/>
└── tests/
    ├── ProjectList.test.tsx                  # vitest + Testing Library
    └── TaskCreateModal.test.tsx
```

**Límite duro:** 600 LOC tocadas (excede el soft-limit de 400 porque
es scaffolding de UI, igual precedente que PR-V1-01 que cerró en
585). Si durante la implementación el PR va a superar 600, PARA y
pide partirlo en PR-V1-06a (projects) + PR-V1-06b (tasks).

## Fuera de scope (explícito)

- **No hay detalle de tarea como ruta.** `/projects/:slug/tasks/:id`
  llega en Semana 2 cuando haya stream de eventos que mostrar.
- **No hay árbol de archivos** del proyecto. Llega en Semana 4-5.
- **No hay edición de proyecto** (no `PATCH` desde UI). Solo create /
  list / delete.
- **No hay stream en vivo** de tareas. TanStack Query hace `refetchInterval`
  de 2000ms sobre la lista de tareas mientras haya alguna en
  `queued`/`running` — no WebSocket, no SSE.
- **No hay página de System / readiness.** Llega en Semana 5.
- **No hay login ni auth.** Bind local, fin.
- **No se toca el backend.** Cero endpoints nuevos.
- **No se añade routing server-side** (todo es SPA, Vite dev server
  sirve el `index.html` para cualquier path gracias a su default).

## Dependencias nuevas

- **npm:**
  - `@mantine/form@7.17.8` — formularios tipados.
  - `@mantine/notifications@7.17.8` — toast tras create/delete.
  - `@tabler/icons-react@3.41.1` — iconos consistentes con Mantine.

Pre-aprobadas como parte del stack Mantine v7 declarado en PR-V1-01.

## Tests

- **Nuevos frontend** (`v1/frontend/tests/`):
  - `ProjectList.test.tsx`:
    - Render con lista vacía → muestra "No projects yet".
    - Render con 2 proyectos (mock QueryClient) → muestra ambas cards.
  - `TaskCreateModal.test.tsx`:
    - Al enviar con título vacío, el botón submit está deshabilitado.
    - Al enviar con título válido, llama al endpoint correcto y cierra.
- **Baseline tras el PR:**
  - Backend: 44 passed (sin cambios).
  - Frontend: 4 passed (de 0 actuales).

## Criterio de hecho

- [ ] `make -C v1 dev` arranca backend :8000 + frontend :5173.
- [ ] `http://localhost:5173/` muestra lista de proyectos (vacía
      inicialmente).
- [ ] Botón "Nuevo proyecto" abre modal con campos: slug, name, kind
      (select: web-deployable | library | script), local_path,
      deploy_port (opcional), git_remote (opcional). Submit crea vía
      `POST /api/projects`, muestra toast de éxito, refresca la lista.
- [ ] Click en card de proyecto navega a `/projects/:slug` y muestra
      nombre, kind, y lista de tareas (vacía inicialmente).
- [ ] Botón "Nueva tarea" abre modal con campos: title, description.
      Submit crea vía `POST /api/projects/:slug/tasks`, refresca
      tareas.
- [ ] Mientras haya alguna tarea en `queued` o `running`, la lista
      hace polling cada 2s (visible al ver tarea pasar a `done` en
      segundos tras el echo).
- [ ] Tareas en estado `inbox`/`queued`/`done`/`failed`/`cancelled`
      tienen botón "Borrar" que llama `DELETE /api/tasks/:id`. Tareas
      en `running`/`waiting_input` no lo tienen (el backend devolvería
      409; no hace falta mostrar el botón).
- [ ] `cd v1/frontend && npm test -- --run` → 4 passed.
- [ ] `cd v1/backend && pytest -q` → 44 passed (sin regresión).
- [ ] Codex-reviewer ejecutado sobre el diff, comentado en PR. Si hay
      blockers, fix-up en la misma rama antes del merge.

## Riesgos conocidos

- **CORS:** dev server frontend en `:5173` y backend en `:8000`. El
  `apiFetch` actual usa `/api` relativo — hay que configurar Vite con
  `server.proxy` apuntando a `localhost:8000`. Alternativa: habilitar
  CORS en FastAPI, pero el proxy es más limpio y no toca backend.
- **Polling con React Query:** `refetchInterval` activo solo cuando
  haya tareas en estados no-terminales, para no hacer llamadas
  innecesarias. Usar `useQuery` con `refetchInterval: (query) =>
  query.state.data?.some(t => ['queued','running'].includes(t.status))
  ? 2000 : false`.
- **Strict Mode doble render:** TanStack Query lo tolera bien pero
  conviene verificar que los mutations no se ejecutan dos veces.

## Notas para el implementador

- Este PR es puramente de UI + data fetching. NO metas lógica de
  negocio que deba vivir en el backend (validación de formato de
  slug, por ejemplo: el backend ya la hace, la UI solo marca error si
  la respuesta es 4xx).
- Formularios con `@mantine/form` + validación básica (`isNotEmpty`,
  `hasLength`). Sin Zod ni Yup — son dep extra no aprobada.
- Layout mínimo: `AppShell` de Mantine con header que diga "Niwa v1"
  y link a "/" (proyectos). Nada de navegación compleja.
- Toasts con `@mantine/notifications` en create/delete success y
  error.
- Si al implementar descubres que alguna ruta del backend devuelve
  algo distinto de lo que el brief asume, PARA y actualiza el brief
  o abre una pregunta. No improvises.
- Commits sugeridos:
  1. `chore(frontend): add mantine form/notifications, tabler icons`
  2. `feat(frontend): router with projects and project-detail routes`
  3. `feat(frontend): projects list + create modal`
  4. `feat(frontend): tasks list in project detail + create modal`
  5. `feat(frontend): delete task button with 409 handling`
  6. `test(frontend): vitest cases for projects list and task create modal`
