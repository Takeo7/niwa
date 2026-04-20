# PR-V1-06 — UI mínima (SUPERSEDED)

> **Status: SUPERSEDED (2026-04-20).** Al implementar se detectó que
> el scope llegaba a ~1000 LOC, excediendo el hard-cap de 600.
> Partido en dos PRs independientes:
>
> - `PR-V1-06a-ui-projects.md` — shell + routing + projects CRUD
>   + test ProjectList (~530 LOC).
> - `PR-V1-06b-ui-tasks.md` — tasks list, create modal, delete con
>   `409`, polling condicional + test TaskCreateModal (~450 LOC).
>
> Se conserva este fichero como registro del alcance combinado
> original. NO usar como brief activo — ver 06a/06b.

---

*(Brief combinado original intacto abajo para referencia.)*

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

## Tests (baseline combinado original)

- Backend: 44 passed (sin cambios).
- Frontend: 4 passed — 2 en ProjectList.test.tsx + 2 en
  TaskCreateModal.test.tsx.

## Criterio de hecho combinado

(Ver 06a y 06b; cada uno cubre su parte. Al mergear ambos, el
criterio del 06 original queda satisfecho.)
