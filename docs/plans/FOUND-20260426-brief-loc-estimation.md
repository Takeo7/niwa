# FOUND-20260426 — Brief LOC estimation systematically too low

## Síntoma

En el ciclo v1.1, dos PRs consecutivos (PR-V1-31 y PR-V1-33) han
disparado el patrón "el cap LOC declarado en el brief está
substancialmente por debajo del scope real del trabajo". No es
overage marginal por fix-ups de codex (que ya está documentado
en `FOUND-20260426-loc-cap-pattern.md`), sino brief que estima
mal el alcance desde el inicio:

- **PR-V1-31** (`niwa-executor update`). Brief cap **100**. Real
  pre-codex: 121 (+21). Tras fix-ups de 2 majors + 1 minor:
  140 (+40). El pipeline tenía 3 ramas condicionales con
  error-propagation que el brief no contabilizó.
- **PR-V1-33** (task attachments). Brief cap **350**. Real
  parcial post-tests + service + model + migration: ~466 LOC,
  **sin endpoints ni frontend todavía**. Proyectado single-PR:
  ~700-750. Decisión de producto: split en 33a (backend) +
  33b (frontend) per brief explícito + cap real 400 por capa.

## Diagnóstico

Tres causas concurrentes:

1. **Briefs subestiman costes laterales**: deps ocultas
   (`python-multipart` para FastAPI multipart en 33), regression
   tests obligados en módulos legacy, ajustes de baseline
   (`HEAD_REVISION` en `test_models.py` cada vez que hay
   migration nueva).
2. **Briefs de scope cross-layer (backend + DB + frontend en un
   PR) inflan más rápido de lo intuitivo**: cada capa carga su
   propio test setup, fixtures, types, helpers. La suma no es
   lineal.
3. **Cap del brief vs cap del proyecto** divergen: el brief
   declara su propio cap conceptual ("M = 350"); el proyecto
   históricamente usa 400 como cap M soft. Cuando el sub-agente
   excede 350 y razona "estoy en M, máx 400", técnicamente
   acierta con el proyecto pero no con el brief.

## Por qué importa

Combinado con `FOUND-20260426-loc-cap-pattern.md`, el resultado
es: el cap del brief se está volviendo **número aspiracional sin
freno real**, no soft-limit ni hard-limit. Cada PR donde el cap
no aplica:

1. Erosiona la disciplina del orquestador para rechazar scope
   excesivo en el delegate inicial.
2. Hace impredecible el trabajo del sub-agente (no sabe si el
   cap es vinculante o no).
3. Mete ruido en la conversación humano-orquestador (cada PR
   incluye discusión sobre "¿este overage es legítimo?").

## Opciones para retro post-ciclo v1.1

Dirección 1 — **brief estima en rangos**. El brief declara
`cap_initial: 200`, `cap_realistic: 350`, `cap_hard_split: 500`
con semántica explícita: si el sub-agente proyecta entre
realistic y hard, sigue; si supera hard, paramos y splitamos.

Dirección 2 — **product partner ajusta cap durante revisión
del brief**. Antes de delegar, el orquestador hace una pasada
"¿este cap realista para el scope?" y propone bump si parece
bajo. Es 10 minutos extra por PR pero filtra dos rondas
posteriores.

Dirección 3 — **briefs cross-layer tienen multiplicador
implícito**. Brief que toca backend+DB+frontend declara cap
base + multiplicador 1.5x al estimar. PR-V1-33 siguiendo esa
regla habría tenido cap 350 × 1.5 = 525, más cerca del scope
real.

Dirección 4 — **deprecar caps por brief, mantener solo cap del
proyecto**. El brief describe scope; el cap es del proyecto
(400 M, 200 S, 600 L). Más simple, menos negociaciones.

## Prioridad

Baja-Media. No bloquea ningún PR del ciclo v1.1 actual. Para
considerar en retro post-cierre del Tier 2 v1.1 junto con
`FOUND-20260426-loc-cap-pattern.md` — son dos síntomas del
mismo problema de raíz: el cap del brief no funciona como
señal robusta.

## Referencias

- `docs/plans/PR-V1-31-executor-update-cmd.md` (cap 100, real 140).
- `docs/plans/PR-V1-33-task-attachments.md` (cap 350, real
  proyectado ~700, splitado en 33a+33b).
- `docs/plans/FOUND-20260426-loc-cap-pattern.md` (síntoma
  hermano: overage por fix-ups codex).
- Conversación humano-orquestador 2026-04-26 sobre
  python-multipart + split de PR-V1-33.
