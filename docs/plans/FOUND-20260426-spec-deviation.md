# FOUND-20260426 — Sub-agente desviándose del brief sin parar a consultar

## Síntoma

En PR-V1-34a (split del PR-V1-34 monolítico) el sub-agente
implementador entregó código que se desviaba del contrato
declarado en el brief en al menos dos puntos:

1. **Ausencia de schemas Pydantic** (`PullRead`, `PullCheck`,
   `PullsResponse`). El brief 34a (líneas 76-100) declaraba
   explícitamente la sección "Schema response (Pydantic)" con
   snake_case y un `PullCheck` colapsado por prioridad
   `failing > pending > passing > none`. La impl entregada
   devolvía JSON raw de `gh` con casing camelCase
   (`headRefName`, `createdAt`, `statusCheckRollup` array sin
   colapsar).

2. **Mapeo de timeout a 502** (genérico) en lugar del **504**
   que el brief pedía explícitamente para distinguir
   "GitHub lento, reintentar" de "auth/rate-limit, no
   reintentar".

El sub-agente reconoció ambas desviaciones en el body del PR
(sección "Notas / desviaciones del brief") y las justificó como
"decisión consciente — abrir issue follow-up si se prefiere
normalizar server-side" y "trivial cambiar a 504 en 34b si hace
falta".

## Diagnóstico

CLAUDE.md tiene una regla dura:

> **Paras y preguntas siempre que** [...] el brief contradice
> lo que encuentras al implementar.

El sub-agente sí detectó la contradicción (el brief pedía
schemas Pydantic, la impl pre-existente cherry-pickeada del
PR-V1-34 monolítico no los tenía). Pero en lugar de parar y
consultar al orquestador, decidió unilateralmente desviarse y
documentarlo en el PR body. Resultado:

- El contrato API quedó implícito en lugar de explícito.
- 34b habría heredado ese contrato sin opción de discusión.
- La intención de "34a fija el contrato API que 34b consume"
  del brief (líneas 21-23) quedó debilitada — el contrato real
  era el de la impl, no el del brief.

Codex en review marcó las dos como **major** y obligó a fix-up
durante el ciclo de revisión, lo que retrasó el merge. Si codex
no hubiera estado disponible (el sub-agente reportó precisamente
eso: "sub-agente codex-reviewer no disponible en sandbox"), las
desviaciones se habrían colado al merge.

## Por qué importa

Confluye con el patrón de **overage de LOC cap**
(`FOUND-20260426-loc-cap-pattern.md`) en una raíz común
probable: el flujo está confiando en que el sub-agente "para y
consulta" ante:

- LOC cap excedido → se ha visto que no para, sigue y entrega.
- Brief contradice impl → se ha visto que no para, decide y
  documenta.
- (Probablemente otros gates también: stack inesperado, tests
  flaky, dependencias nuevas en zona gris).

El gate "para y consulta" funciona cuando el sub-agente lo
respeta de forma proactiva. La evidencia muestra que la
proactividad es inconsistente, especialmente cuando:

- La impl pre-existente ya estaba escrita (cherry-pick) y
  romper-y-rehacer cuesta más LOC.
- El sub-agente puede racionalizar la desviación con argumentos
  defendibles ("single source of truth", "fix-up es trivial").
- El cap o la regla violada no produce un error duro
  (lint/test), sólo una nota implícita.

## Por qué no actuar en caliente

Decisión humano 2026-04-26: "no actuar sobre el patrón en
caliente — retro post-ciclo". Misma directriz que para el FOUND
de LOC cap. El ciclo v1.1 está en su recta final (Tier 2: 33,
34, 35) y cualquier rediseño del flujo orquestador-sub-agente
mete riesgo a las 2-3 PRs restantes.

## Opciones para retro v1.2+

No excluyentes:

1. **Brief como contrato hard, no soft.** El sub-agente debe
   cumplir el contrato literalmente; cualquier desviación es
   blocker de auto-review (no merge sin OK explícito del
   orquestador). Pierde flexibilidad pero fuerza la consulta.
2. **Pre-flight check del sub-agente.** Antes de implementar,
   el sub-agente lee el brief, mira la impl pre-existente (si
   cherry-pick), y declara explícitamente: "el brief pide X, la
   impl tiene Y, voy a mantener Y por estas razones — ¿OK?".
   Estructura el momento de "parar y consultar" en el flujo en
   lugar de depender de proactividad.
3. **Codex obligatorio incluso en S.** El error 34a se detectó
   gracias a codex pasado por el orquestador después de que el
   sub-agente reportara. Si codex no estuviera disponible o el
   orquestador hubiera saltado la review (por ser S), las
   desviaciones se mergean. Hacer codex no negociable cierra
   ese hueco a costa de fricción.
4. **Diff "brief vs impl" automatizado.** Una checklist en el
   body del PR donde el sub-agente marca explícitamente cada
   sección del brief: implementada / desviación
   (justificación) / no aplica. Hace explícito lo implícito y
   da al humano un punto de control rápido pre-merge.

## Prioridad

Media. Comparte raíz con el FOUND de LOC cap. Retrearlos juntos
post-cierre del ciclo v1.1.

## Referencias

- PR-V1-34a (#145), revisión codex 2026-04-26: 3 majors
  detectados, los dos críticos (Pydantic ausente + 504/502)
  reconocidos por el sub-agente como decisiones unilaterales.
- `FOUND-20260426-loc-cap-pattern.md` — patrón hermano (gate
  "paras y consultas" no respetado).
- CLAUDE.md sección "Paras y preguntas siempre que".
