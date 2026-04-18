# PR-NN — <título corto, imperativo>

**Hito:** 0 | A | B | C | D
**Esfuerzo:** S | S-M | M | L
**Depende de:** PR-NN, PR-MM (o "ninguna")
**Bloquea a:** PR-XX (o "ninguno")

## Qué

<2-3 líneas. "Añade endpoint /api/readiness que devuelve estado de
backends y qué falta configurar.">

## Por qué

<1 línea que conecta con el happy path del MVP (ver
`docs/MVP-ROADMAP.md §1`).>

## Scope — archivos que toca

- `ruta/al/fichero.py` (qué cambia en 1 línea)
- `ruta/al/otro.tsx` (idem)

## Fuera de scope (explícito)

- No toca X
- No cambia Y (eso es PR-MM)

## Tests

- **Nuevos:** `tests/test_feature.py` con casos: A, B, C.
- **Existentes que deben seguir verdes:** `test_smoke.py`, `test_X.py`.
- **Baseline esperada tras el PR:** `≥1060 pass / ≤75 errors` (o el
  número que aplique según último PR mergeado).

## Criterio de hecho

Lista verificable, ejecutable por otra persona:

- [ ] `curl /api/readiness` devuelve JSON con schema `{docker_ok,
  db_ok, backends: [...]}`
- [ ] Widget muestra N items rojos si no hay API key
- [ ] `pytest -q` sin regresiones respecto al baseline
- [ ] Review Codex resuelto (o "LGTM")

## Riesgos conocidos

- <bullet>: mitigación.
- Si ninguno: "ninguno".

## Notas para Claude Code

- Si al implementar descubres que el scope es mayor del declarado,
  PARA, reescribe este brief, pide re-aprobación.
- Commits pequeños, mensaje imperativo en inglés.
- Antes de pedir review: correr `pytest -q`, pegar el diff de
  pass/fail/error respecto al baseline en el PR description.
