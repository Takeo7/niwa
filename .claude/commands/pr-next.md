---
description: Arranca el siguiente PR del MVP roadmap sin parámetros
---

Eres una sesión Claude Code que va a ejecutar UN PR del MVP de Niwa.
No tienes parámetros — autodescubres qué PR toca.

## Paso 1 — descubre qué PR te toca

1. Lee `docs/MVP-ROADMAP.md` completo: §1 happy path, §2 workflow,
   §4 hitos y PRs, §6 orden recomendado.
2. Lista PRs del repo con `mcp__github__list_pull_requests` (state=all).
   Filtra títulos que empiecen por `PR-` (ej. `PR-00`, `PR-A1`).
   Para cada PR del roadmap marca estado: `merged | open | none`.
3. El PR que te toca = primer PR del orden en §6 con estado `none`.
   Si todos están `merged` u `open`, di literalmente
   "roadmap completo o todos los PRs ya están en curso" y para.
4. Declara en chat: "Me toca **PR-NN — <título>**. Hito <X>. Esfuerzo
   <S/M/L>. Depende de: <lista>."

## Paso 2 — prepara rama y brief

5. Checkout a `claude/pr-<NN>-<slug>`. Si existe remoto, `git pull`;
   si no, crea desde la rama por defecto actualizada (`git fetch
   origin` + branch from default).
6. Si `docs/plans/PR-<NN>-<slug>.md` **no existe**:
   - Escríbelo usando `docs/plans/_TEMPLATE.md`.
   - Commitea SOLO el brief con mensaje `plan: brief for PR-<NN>`.
   - Push.
   - **PARA**. Di: "Brief escrito en `docs/plans/PR-<NN>-<slug>.md`.
     Espero tu 'ok' o 'cambia X' antes de tocar código."
7. Si el brief **ya existe**: léelo, resume en 3 líneas qué vas a
   hacer, y espera mi "ok" igualmente.

## Paso 3 — implementa (solo tras mi "ok" explícito)

8. Si el brief declara tests nuevos: escríbelos primero, confirma
   que fallan por el motivo esperado, commit
   `test: failing cases for <feature>`.
9. Implementa hasta que los tests pasen.
10. Corre `pytest -q` completo. Baseline:
    `1033 pass / 60 failed / 104 errors / 87 subtests pass` (228s).
    No puedes regresar ningún test que estuviera verde.
11. Invoca el subagente `codex-reviewer` sobre tu diff (`git diff
    origin/<default>...HEAD`) salvo que el brief marque esfuerzo S.
    Pega sus comentarios marcados como `🤖 Codex review` en el PR.
12. Commits pequeños, mensaje imperativo en inglés. No amends sobre
    commits pusheados.

## Paso 4 — abre el PR

13. Abre el PR con `mcp__github__create_pull_request`:
    - Título: `PR-<NN>: <título corto>` (máx. 70 chars).
    - Body: link al brief, diff de `pytest` vs baseline
      (pass/fail/error), bloque `🤖 Codex review` con resolución
      de cada comment.
14. `mcp__github__subscribe_pr_activity` al PR para responder a
    comentarios de review y fallos de CI sin que el humano te
    empuje.
15. Di en chat: "PR abierto: <URL>. Esperando review." y termina
    esta sesión. **No empieces el PR siguiente.**

## Paras y preguntas SIEMPRE si:

- El brief contradice lo que encuentras en el código.
- Detectas scope creep (algo "mientras estoy aquí").
- Un test del baseline falla tras tu cambio y no sabes si es tu
  culpa.
- Codex marca un `blocker` y no está claro cómo resolverlo sin
  scope nuevo.
- Cualquier ambigüedad en el brief respecto a nombres, rutas,
  schemas o criterios de hecho.

## NUNCA haces:

- Refactors fuera del scope declarado en el brief.
- Commits amend sobre algo ya pusheado.
- `git push --force`, `git reset --hard`, `--no-verify`.
- Mergear tu propio PR.
- Empezar el siguiente PR al terminar. **Sesión = un PR.**
- Tocar ramas que no son la tuya.

Empieza por el paso 1.
