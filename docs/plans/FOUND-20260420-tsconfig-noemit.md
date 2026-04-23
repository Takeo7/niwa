# FOUND-20260420 — tsconfig emits .js into src/

**Observado durante:** PR-V1-06a (codex review) y PR-V1-06b (working
tree sucio tras `npm test -- --run` / `tsc -b`).

## Síntoma

`v1/frontend/tsconfig.json` no tiene `"noEmit": true`. Al ejecutar
`tsc -b` (incluido en `npm run build` y disparado implícitamente por
el IDE o por el test runner en algunos setups), TypeScript emite
ficheros `.js` junto a los `.tsx` dentro de `src/`:

```
v1/frontend/src/App.js
v1/frontend/src/api.js
v1/frontend/src/features/projects/ProjectCreateModal.js
v1/frontend/src/features/projects/ProjectDetail.js
v1/frontend/src/features/projects/ProjectList.js
v1/frontend/src/features/projects/api.js
v1/frontend/src/features/tasks/TaskCreateModal.js
v1/frontend/src/features/tasks/TaskList.js
v1/frontend/src/features/tasks/api.js
v1/frontend/src/main.js
v1/frontend/src/routes/ProjectDetailRoute.js
v1/frontend/src/routes/ProjectsRoute.js
v1/frontend/src/shared/AppShell.js
```

Vite hace el build real, así que estos `.js` son ruido: ensucian
`git status`, pueden confundir a los tests si el resolver los
prefiere sobre los `.tsx`, y obligan a limpieza manual tras cada
sesión.

## Fix propuesto

Añadir `"noEmit": true` al `compilerOptions` de
`v1/frontend/tsconfig.json`. `tsc -b` seguirá validando tipos
(`tsc --noEmit` sigue corriendo typecheck) pero no escribirá `.js`.

Alternativa: `"outDir": "../.tsout"` para aislar los emitidos — peor,
duplica trabajo de Vite.

## Prioridad

Baja. Es higiene, no bloquea ningún PR. PR-V1-06a ya añadió
`*.tsbuildinfo` al `.gitignore` como paliativo parcial; los `.js`
siguen sin ignorarse porque el fix correcto es no emitirlos.

## Alcance del follow-up

1 línea en `tsconfig.json` + opcional: añadir `*.js` bajo `src/` al
`.gitignore` como red de seguridad. No se recomienda ignorar `.js` a
nivel global, solo dentro de `src/**`.

## Referencia

- PR-V1-06a codex review: https://github.com/Takeo7/niwa/pull/108#issuecomment-4283121471
- PR-V1-06b working tree report.
