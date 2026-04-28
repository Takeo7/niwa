# PR-V1-36 — docs: reading order + canonical examples + procedural checklist

**Esfuerzo:** S+ (banda calibrada del FOUND-loc-cap-pattern: 130-200 LOC)
**Depende de:** PR-V1-36-prep (mergeado, #149) — `AGENTS.md` ya en raíz.

## Qué

Tres entregables coherentes, todos "documentación viva del proceso":

1. **`docs/HANDBOOK.md` — sección nueva "Reading order por workflow"**.
   Para cada workflow común, lista los 3-5 archivos a leer en orden.
   Reduce el coste de exploración en sesiones nuevas. Workflows
   declarados (cubrir todos):
   - Para añadir un endpoint nuevo (services + api + tests).
   - Para tocar el verifier (verification/* + integración con
     executor).
   - Para modificar el lifecycle de task (executor + states +
     events + DB).
   - Para añadir una columna a una tabla (model + migration +
     tests).
   - Para tocar el adapter de Claude CLI (adapters/* + smoke).
   - Para añadir un componente frontend (route + feature + tests).

2. **`docs/HANDBOOK.md` — sección nueva "Ejemplos canónicos por
   tipo de pieza"**. Para cada tipo, declarar el archivo modelo
   actual del repo + 1 línea diciendo qué patrón captura. Tipos
   declarados (cubrir todos):
   - Servicio backend (pure functions over Session).
   - Router/endpoint con dependency injection.
   - Modelo SQLAlchemy.
   - Schema Pydantic v2.
   - Test de servicio (sin TestClient).
   - Test de endpoint con TestClient.
   - Migración Alembic.
   - Componente frontend con Mantine v7.
   - Hook TanStack Query.
   - Test frontend con Vitest + RTL.

3. **`docs/plans/_TEMPLATE.md` — sección checklist procesal**
   anclada en los tres FOUND del ciclo v1.1. Añadir antes de la
   sección "Notas para Claude Code". Campos obligatorios:
   - **LOC budget** con banda calibrada (S=100-130 / S+=130-200 /
     M=200-300 / L=300-400) y estimación pre-impl.
   - **FOUND aplicables a este PR**: lista cross-link explícito
     (cero o más). Captura el hallazgo positivo del cycle-close
     (mencionar FOUND mejora comportamiento del implementer).
   - **Áreas críticas tocadas** (sí/no, codex obligatorio si sí).
     Áreas: `executor/`, `verification/`, `finalize.py`,
     `adapters/`.
   - **Anclaje empírico**: "Código que el orquestador leyó/ejecutó
     antes de escribir el brief". Fuerza que el contrato del
     brief no sea aspiracional sin referencia al código real
     (causa raíz de FIX-01).

## Por qué

Los tres FOUND del ciclo v1.1 apuntan a causa raíz común: el
proceso confía en cosas que no se verifican (caps, contratos,
estado real del código). PR-V1-37 (CI mínimo) ataca la causa
primaria. Este PR ataca tres causas secundarias:

- **Reading order**: reduce tokens y mejora precisión cuando
  Codex (o cualquier implementer) explora el repo.
- **Ejemplos canónicos**: evita que cada implementer destile el
  patrón desde cero. Captura "haz esto como aquello".
- **Checklist en `_TEMPLATE.md`**: convierte los FOUND de
  archivo histórico en guardrail activo, mencionado en cada
  brief nuevo.

Empíricamente, el cycle-close FOUND mostró que mencionar FOUND
en briefs (PR-V1-35) mejoró el comportamiento del sub-agente
(paró antes de commitear). Sistematizamos esa práctica.

## Scope — archivos que toca

- `docs/HANDBOOK.md` — añade dos secciones nuevas. NO modificar
  contenido existente del documento. NO reordenar secciones.
- `docs/plans/_TEMPLATE.md` — añade un bloque checklist antes
  de "Notas para Claude Code". El bloque puede ajustar
  ligeramente el orden de campos existentes si la nueva
  sección encaja mejor en otra posición; documentar el cambio
  en commit message.

## Fuera de scope (explícito)

- **NO** añadir module-level docstrings a archivos backend.
  Eso era parte del plan original conversacional pero queda
  fuera para mantener cap. Candidato a PR aparte si rinde.
- **NO** rename del agente `codex-reviewer` interno. Decisión
  cerrada en PR-V1-36-prep.
- **NO** tocar `CLAUDE.md`. El cambio de `_TEMPLATE` se aplica
  a briefs futuros, no se retroactivamente actualiza
  `CLAUDE.md`.
- **NO** tocar código `.py` / `.ts` / `.tsx`. Markdown-only.

## Dependencias nuevas

- Python: ninguna.
- npm: ninguna.

## Tests

- **Nuevos:** ninguno (markdown-only).
- **Existentes que deben seguir verdes:** baseline backend
  (196 passed, 1 skipped) y frontend (18 passed). Mecánicamente
  preservado — no hay nada que pueda romperse, pero el
  implementer DEBE correr ambos gates igual y pegar output
  literal en el PR body para confirmar.

## Criterio de hecho

- [ ] `docs/HANDBOOK.md` tiene sección "Reading order por
      workflow" con los 6 workflows declarados, cada uno
      con 3-5 archivos en orden.
- [ ] `docs/HANDBOOK.md` tiene sección "Ejemplos canónicos por
      tipo de pieza" con los 10 tipos declarados, cada uno
      con archivo modelo y razón en 1 línea.
- [ ] `docs/plans/_TEMPLATE.md` tiene bloque checklist con los
      cuatro campos: LOC budget con banda, FOUND aplicables,
      áreas críticas tocadas, anclaje empírico.
- [ ] El nombre exacto de los archivos canónicos está
      verificado contra el repo actual (`backend/app/services/`,
      etc.) — no inventados.
- [ ] `cd backend && pytest -q` → 196 passed, 1 skipped (sin
      cambios). Output literal en PR body.
- [ ] `cd frontend && npm test` → 18 passed (sin cambios).
      Output literal en PR body.
- [ ] LOC vs cap: real ≤ 200 (banda S+). Mostrar
      `git diff --stat origin/main...HEAD` (lockfiles
      excluidos, no aplica aquí — solo markdown).

## Riesgos conocidos

- **Inflación**: 6 workflows × 5 archivos + 10 tipos × 2 líneas
  + 4 campos × 5 líneas ≈ 100 LOC markdown sin ser denso.
  Si el implementer es verboso, sube a 150-180 fácil. Cap S+
  cubre hasta 200 LOC, dentro de banda. Mitigación: brief
  pide líneas específicas por sección.
- **Archivos canónicos mal elegidos**: el implementer tiene
  que decidir qué `task_service.py` vs cuál otro. Mitigación:
  AGENTS.md ya pide "anclaje empírico antes de declarar
  contratos" — el implementer debe verificar el archivo
  existe y captura el patrón.
- **`_TEMPLATE.md` cambia el formato de briefs futuros**:
  positivo intencional, no riesgo.

## Notas para el implementer (Codex Desktop GPT-5.5)

- Reglas duras vienen de `AGENTS.md` en raíz. Léelo si no lo
  has hecho.
- **FOUND aplicables a este PR** (cross-link literal en el
  brief, parte del checklist que estás creando):
  - `docs/plans/FOUND-20260426-loc-cap-pattern.md`
  - `docs/plans/FOUND-20260426-brief-loc-estimation.md`
  - `docs/plans/FOUND-20260426-spec-deviation.md`
  - `docs/plans/FOUND-20260427-process-gap.md`
- **Áreas críticas tocadas**: ninguna. Codex review NO
  obligatorio (markdown-only). El orquestador hace review
  ligero igualmente.
- **Anclaje empírico del brief (lo que el orquestador leyó
  antes de escribirlo)**:
  - `docs/plans/_TEMPLATE.md` (formato actual).
  - `docs/plans/FOUND-20260427-v1.1-cycle-close.md` (input
    de retro).
  - Conversación ciclo v1.1 + setup PR-V1-36-prep.
- Para identificar archivos canónicos, recorre
  `backend/app/services/`, `backend/app/api/`, etc. Elige
  el archivo que mejor capture el patrón típico actual del
  repo, no el más complejo ni el más simple.
- Pega `git diff --stat origin/main...HEAD` literal en PR
  body. Pega outputs literales de pytest y npm test.
- Si el LOC real proyecta > 200, **PARA y consulta** al
  humano antes de pushear. Reporta cuánto y dónde.
