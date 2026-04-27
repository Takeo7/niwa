# FOUND-20260427 — Quinta muestra del patrón "el proceso confía en algo que no se está verificando"

## Síntoma

PR-V1-FIX-01 (mergeado en main como `33e4d73`) cierra dos
rojos descubiertos en el smoke técnico v1.1, ambos
sintomáticos del mismo patrón sistemático:

1. **`test_readiness_api.py::test_all_checks_ok`** — pasa en
   sandbox limpio, falla en cualquier máquina con
   `~/.niwa/config.toml` declarado. Causa: el flujo confió en
   que el sandbox del sub-agente representa el entorno real
   del humano. Diagnóstico hecho por el orquestador antes de
   esta sesión.
2. **`test_artifacts.py::test_non_git_cwd_skips_e3_gracefully`**
   — pasa en sandbox C-locale, falla en máquinas con
   `LANG=es_ES.UTF-8` y git-i18n instalado. Causa: el
   `subprocess.run` del verifier confiaba en que el locale del
   proceso era inglés sin pasar `env=`.

Ambos rojos no fueron detectados por CI porque **el repo no
tiene CI configurado** — `.github/workflows/` no existe,
verificado vía `mcp__github__` durante esta sesión. PR-V1-35
cerró con 0 check runs. El único gate del ciclo v1.1 entero
ha sido el reporte del sub-agente sobre su propio sandbox.

## Catálogo del patrón

Las cuatro muestras previas (todas del ciclo v1.1) están
documentadas en `FOUND-20260426-loc-cap-pattern.md`. Cada una
es una manifestación del mismo gap procesal:

| # | PR | Cap brief | Real | Causa procesal |
|---|----|-----------|------|----------------|
| 1 | PR-V1-31 | 100 | 140 (+40%) | Brief subestimó cost lateral del pipeline 3-rama |
| 2 | PR-V1-33 | 350 | 466 primer push (+33%) | Brief subestimó scope cross-stack; forzó split a 33a-i / 33a-ii / 33b (total 977) |
| 3 | PR-V1-34 | 300 | 551 primer push (+84%) | Brief subestimó scope cross-stack; forzó split a 34a + 34b |
| 4 | PR-V1-35 | 100 | 325 (+225%) | Brief subestimó scope; sub-agente paró antes de commitear, humano aprobó conscientemente |
| 5 | **PR-V1-FIX-01 (ESTA SESIÓN)** | 80 | 106 (+32%) | **Dos confianzas en gates inexistentes**: smoke confió en sandbox del sub-agente; subprocess confió en locale heredado |

Las cuatro previas se centran en **LOC cap subestimado**.
Esta quinta amplía el patrón a **gates de confianza
silenciosamente ausentes**.

## Diagnóstico — la raíz común

El flujo del ciclo v1.1 se apoya en gates implícitos que no
están automatizados. La tabla de gates que el ciclo ASUME que
existen vs lo que REALMENTE existe:

| Gate asumido | Realidad |
|--------------|----------|
| Tests pasan en CI antes de merge | **Inexistente.** No `.github/workflows/`. Ningún PR del ciclo tuvo check runs. |
| Tests pasan en el entorno del humano | **No verificado.** Sub-agente reporta sobre su propio sandbox limpio; el humano descubre rojos solo al hacer smoke manual. |
| Sub-agente respeta cap LOC del brief | **Soft-limit con narrativa.** Cuatro muestras de overage 30-225% aceptados con justificación post-hoc. |
| Sub-agente respeta gate "paras y consultas" | **Inconsistente.** PR-V1-34a se desvió sin consultar (`FOUND-20260426-spec-deviation.md`); PR-V1-35 sí paró. |
| Brief estima scope correctamente | **Sistemáticamente bajo.** `FOUND-20260426-brief-loc-estimation.md` documenta subestimaciones 1.5-3× consistentes. |

Cada PR del ciclo el flujo confía en estos gates como si
funcionaran. Cuando uno falla, el descubrimiento es siempre
post-hoc (smoke manual, blocker codex, conversación
orquestador-humano sobre overage). **Quinta muestra**: hasta
ayer el ciclo confió en que la suite "verde" del sub-agente
representaba la suite real del humano. El smoke v1.1 destruyó
esa confianza con dos rojos diagnosticables.

## Hallazgo positivo de esta sesión

Por primera vez en el ciclo, el ORQUESTADOR identificó un
defecto en su propio brief y forzó iteración antes de aceptar
la desviación del sub-agente:

- El brief que escribí (con corrección humana incluida) pidió
  un primer test que monkeypatcheaba `subprocess.run` para
  inyectar stderr español. Eso forzaba la impl a tener una
  rama de detección que no dependiera de stderr — algo que el
  sub-agente respondió con un `not_a_repo = not (cwd_path /
  ".git").exists()` defensivo en `artifacts.py`.
- Cuando el sub-agente reportó la desviación, el orquestador
  pudo haber aceptado ("desviación menor, justificada,
  trade-off aceptable"). En su lugar, paró y presentó al
  humano tres opciones (A: aceptar / B: iterar para test
  contract-on-env / C: split). Mi recomendación fue B porque
  reconocí que el defecto era del brief, no del sub-agente.
- El humano eligió B. Iteración resultó en impl mínima 4 LOC
  + test reescrito como contract-on-env. **El gate "paras y
  consultas" se está internalizando arriba en la cadena**, no
  solo en sub-agentes (PR-V1-35 fue el primer caso donde el
  sub-agente paró; éste es el primer caso donde el orquestador
  paró sobre su propio diseño).

Patrón a reforzar en `_TEMPLATE.md` y CLAUDE.md durante
PR-V1-36.

## Mitigaciones

Dos PRs en la cola atacan la causa raíz a distintos niveles:

### PR-V1-37 (CI mínimo) — ataca el gate primario

`.github/workflows/ci.yml` con:
- `cd backend && pip install -e ".[dev]" && pytest -q`
- `cd frontend && npm install && npm test`
- Trigger en push a `main` y a cualquier rama `claude/pr-*`.

Bloquea merges que rompan baseline. **Causa raíz común** de
las cinco muestras: convertir gates implícitos en checks
ejecutados por GitHub. Coste estimado: brief XS, ~30 LOC YAML.
**PRIORIDAD ALTA. Sesión siguiente.**

### PR-V1-36 (docs + checklist procesal) — ataca causas secundarias

- Reading order canónico de `docs/` (CLAUDE.md → SPEC →
  HANDBOOK → FOUNDs → brief → impl).
- Recalibración de caps por categoría brief: hoy S = ~80 LOC
  cuando una muestra del ciclo (PR-FIX-01) muestra que un fix
  con doble cobertura de test + helper + doc consume ~106
  LOC. Tres opciones para retro: rangos
  (`cap_initial`/`cap_realistic`/`cap_hard`), multiplicador
  cross-stack, deprecar caps por brief y mantener solo cap
  proyecto.
- Checklist procesal en `_TEMPLATE.md`: "¿el brief asume
  algún gate que el repo no tiene?" como sección obligatoria.
  Habría capturado las cinco muestras antes de empezar.
- Module docstrings backend (queja del smoke).

**PRIORIDAD MEDIA. Después de PR-V1-37.**

## Referencias

- `FOUND-20260426-loc-cap-pattern.md` — muestras 1-4 del
  patrón (overage de LOC cap).
- `FOUND-20260426-brief-loc-estimation.md` — síntoma hermano
  (briefs subestiman scope cross-stack).
- `FOUND-20260426-spec-deviation.md` — síntoma hermano
  (sub-agentes desviándose sin parar a consultar).
- `FOUND-20260427-v1.1-cycle-close.md` — resumen de cierre
  del ciclo v1.1, incluye los tres FOUND como input para
  retro post-smoke.
- PR-V1-FIX-01 (#148, mergeado `33e4d73`) — esta sesión.

## Conclusión

CI mínimo en PR-V1-37 cierra el agujero estructural. Sin él,
cada PR siguiente depende del orquestador y el humano
recordando manualmente que el sub-agente reporta sobre su
sandbox. PR-V1-36 cierra el agujero procesal. Tras los dos,
el ciclo v1.2 puede empezar con un baseline confiable.
