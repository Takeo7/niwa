# PR-V1-06b — UI: tasks list + create + delete + polling

**Semana:** 1.5 (segunda mitad del 06 original)
**Esfuerzo:** M
**Depende de:** PR-V1-06a mergeado. Supersede junto con 06a a
`PR-V1-06-ui-minimal.md`.

## Qué

Encima del shell de 06a, añade **tasks** al detalle de proyecto:
lista embebida, modal de creación, botón delete para estados
terminales (con manejo de `409`), y polling condicional cada 2 s
mientras haya tareas en `queued`/`running`. Test Vitest del modal
de creación. Backend intacto.

## Por qué

Partido de `PR-V1-06` original para quedarse bajo el hard-cap de
600 LOC. Esta mitad completa el flujo end-to-end: el usuario
puede ver cómo una tarea pasa de `queued` → `done` en la UI sin
`curl`. Cierra el objetivo del 06 combinado.

## Scope — archivos que toca

```
v1/frontend/
├── src/
│   ├── api.ts                              # tipos Task*, TaskStatus,
│   │                                       # TaskCreatePayload,
│   │                                       # helpers hasInFlightTask, isTaskActive
│   ├── features/
│   │   ├── projects/
│   │   │   └── ProjectDetail.tsx           # reemplaza placeholder
│   │   │                                   # por <TaskList/> + botón "Nueva tarea"
│   │   └── tasks/
│   │       ├── api.ts                      # useTasks (con refetchInterval
│   │       │                                 condicional) + useCreateTask
│   │       │                                 + useDeleteTask
│   │       ├── TaskList.tsx                # filas: title, status,
│   │       │                                 created_at, botón delete
│   │       └── TaskCreateModal.tsx         # title + description,
│   │                                         valida isNotEmpty
└── tests/
    └── TaskCreateModal.test.tsx            # 2 casos del brief
```

**Límite duro:** 600 LOC. Si vas a exceder, PARA.

## Fuera de scope (explícito)

- Sin cambios a `AppShell`, routing, providers — 06a los dejó
  listos.
- No hay detalle de tarea como ruta (sigue siendo Semana 2).
- No hay streaming (Semana 2).
- No hay árbol de archivos.
- No hay auth, ni `/system`.
- No se toca backend.

## Dependencias nuevas

- npm: ninguna (las 3 Mantine/tabler ya entraron en 06a).
- devDependencies: ninguna.

## Tests

Nuevos en `v1/frontend/tests/TaskCreateModal.test.tsx` (2 casos del
brief 06 original):

1. `submit button disabled with empty title` — render del modal,
   título vacío, el botón submit está deshabilitado.
2. `valid submit posts and closes` — título válido, submit llama
   al endpoint correcto (`POST /api/projects/:slug/tasks`) con el
   payload esperado y el modal se cierra.

**Baseline tras PR-V1-06b:**
- Backend: 44 passed (sin tocar).
- Frontend: **4 passed** (2 de 06a + 2 nuevos).

## Criterio de hecho

- [ ] `/projects/:slug` renderiza la lista de tareas (vacía
  inicialmente).
- [ ] "Nueva tarea" abre modal; submit con título válido hace
  `POST /api/projects/:slug/tasks`, cierra, toast, refresca.
- [ ] Mientras haya task en `queued`/`running`, la lista refetch
  cada 2 s. Cuando no hay, para.
- [ ] Tareas en `inbox|queued|done|failed|cancelled` muestran
  botón delete que llama `DELETE /api/tasks/:id`. En
  `running|waiting_input` no lo muestran. Si el backend responde
  `409` igualmente, muestra toast de error legible y refresca la
  lista.
- [ ] `cd v1/frontend && npm test -- --run` → **4 passed**.
- [ ] `cd v1/backend && pytest -q` → 44 passed.
- [ ] HANDBOOK sección "Frontend" extendida con tasks + polling.
- [ ] Codex-reviewer ejecutado por el orquestador sobre el diff.

## Riesgos conocidos

- **Polling excesivo.** `refetchInterval` debe ser función de los
  datos, no constante. Apágalo cuando `data` no exista todavía
  (mientras carga) para no acumular requests en cold start.
- **Race create→refetch.** Tras `POST` exitoso, invalidar la
  query key `['tasks', slug]` para refetch inmediato. No
  dependas solo del polling.
- **Delete con 409 silencioso.** Si el backend empieza a
  aceptar delete en estados antes prohibidos, la UI sigue
  funcionando; el botón solo oculta el caso común.

## Notas para el implementador

- Commits sugeridos:
  1. `feat(frontend): task types and api hooks`
  2. `feat(frontend): task list embedded in project detail`
  3. `feat(frontend): task create modal`
  4. `feat(frontend): delete task button with 409 handling`
  5. `feat(frontend): conditional polling on in-flight tasks`
  6. `test(frontend): vitest cases for task create modal`
  7. `docs(v1): handbook tasks ui section`
- `useTasks(slug)` debe aceptar una opción para desactivar el
  polling en tests; si no, mockea el hook entero.
- `hasInFlightTask(tasks)` en `api.ts` — helper puro, usado por
  el `refetchInterval` y por visibilidad del spinner.
- Esfuerzo M → codex review obligatorio.
