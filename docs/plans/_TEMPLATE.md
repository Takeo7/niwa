# PR-V1-NN — <título corto, imperativo>

**Semana:** 1 | 2 | 3 | 4 | 5 | 6
**Esfuerzo:** S | M | L
**Depende de:** PR-V1-NN (o "ninguna")

## Qué

<2-3 líneas describiendo el entregable concreto.>

## Por qué

<1 línea que conecta con la semana correspondiente del SPEC §9.>

## Scope — archivos que toca

- `v1/ruta/al/fichero.py` (qué cambia en 1 línea)
- `v1/ruta/al/otro.tsx` (idem)

## Fuera de scope (explícito)

- No toca X
- No cambia Y (eso es PR-V1-MM)

## Dependencias nuevas

- Python: <lista o "ninguna">
- npm: <lista o "ninguna">

Si hay alguna no pre-aprobada en `v1/CLAUDE.md §Reglas duras 10`,
paras antes de añadirla.

## Tests

- **Nuevos:** `v1/backend/tests/test_feature.py` casos A, B, C.
- **Frontend:** `v1/frontend/src/features/.../Feature.test.tsx` si
  aplica.
- **Existentes que deben seguir verdes:** todos los previos del
  baseline de v1.

## Criterio de hecho

Lista verificable:

- [ ] `curl http://localhost:<port>/api/<endpoint>` devuelve <X>
- [ ] UI muestra <Y> en <ruta>
- [ ] `pytest -q` en `v1/backend/` pasa
- [ ] `npm test` en `v1/frontend/` pasa
- [ ] Review Codex resuelto (o "LGTM" / skip si esfuerzo S)

## Riesgos conocidos

- <riesgo>: <mitigación>
- Si ninguno: "ninguno".

## Checklist procesal

- **LOC budget:** <S=100-130 / S+=130-200 / M=200-300 /
  L=300-400>; estimación pre-impl: <N> LOC.
- **FOUND aplicables a este PR:** <lista cross-link explícita, o
  "ninguno">. Mencionar FOUND aplicables mejora el comportamiento
  del implementer y convierte hallazgos históricos en guardrails.
- **Áreas críticas tocadas:** <sí/no>. Si sí, codex obligatorio.
  Áreas: `executor/`, `verification/`, `finalize.py`, `adapters/`.
- **Anclaje empírico:** código que el orquestador leyó/ejecutó
  antes de escribir el brief: <rutas, comandos o evidencia concreta>.

## Notas para Claude Code

- Si el scope real supera el declarado, PARA y reescribe el brief.
- Commits pequeños, imperativos, en inglés.
- Antes de abrir PR: `pytest -q` y `npm test` en verde, diff pegado
  en la descripción del PR.
