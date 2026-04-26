# FOUND-20260426 — Patrón sistemático de overage de LOC cap por fix-ups de codex

## Síntoma

Tras 9+ PRs (PR-V1-11b, 11c, 16, 18, 22, 23, 25, 26, 30, 31), el
patrón es repetible: el sub-agente entrega el PR cerca o sobre el
cap declarado en el brief; codex encuentra blockers reales que
obligan a fix-ups; los fix-ups añaden 10-30 LOC; el PR se mergea
con LOC final muy por encima del cap original, con la
justificación "fix-ups de codex no cuentan".

Ejemplos:

- PR-V1-11b: brief 400 → final 499 (+99) tras blocker E4 embedded.
- PR-V1-11c: brief 400 → final 380 (raro, dentro de cap).
- PR-V1-18: brief 400 → final 421 (+21) tras blocker test isolation.
- PR-V1-22: brief 300 → final 290 (dentro tras fix-up dead code).
- PR-V1-23: brief 250 → final 262 (+12) tras blocker promote on triage failure.
- PR-V1-25: brief sin cap → 4 blockers + fix-ups; LOC controlado por
  ser release.
- PR-V1-26: brief 200 → final 234 (+34) tras blocker env curado.
- PR-V1-30: brief 30 → final 36 (+6) tras blocker SKIP_LINGER.
- PR-V1-31: brief 100 → final 140 (+40) tras 2 majors + minor.

## Diagnóstico

La distinción **scope creep inicial** vs **fix-up de codex defect**
es legítima conceptualmente:

- Scope creep: sub-agente añade lógica extra que el brief no pidió.
- Fix-up codex: corrige un defecto detectado en review (robustez,
  cobertura test, propiedad declarada por brief no implementada).

Pero en la práctica, el resultado neto es que el cap del brief
no funciona como freno duro real. Está actuando como soft-limit
con narrativa ("los fix-ups no cuentan") cada vez que codex
encuentra algo. Como codex casi siempre encuentra algo (ese es
su trabajo), el cap es opcional de facto.

## Por qué importa

El cap existe para forzar disciplina de scope: si un PR no cabe,
parte. Si el cap es opcional cuando hay fix-ups, el incentivo
del orquestador es:

- Brief con cap apretado → confiar en que codex añadirá margen
  vía fix-ups → más probable aceptar scope que no cabe.
- Sub-agente sabiendo esto puede ser menos disciplinado en la
  primera pasada porque "ya habrá fix-up para extender".

No hay evidencia hoy de que esto haya pasado conscientemente,
pero el patrón habilita ese fallo silencioso.

## Opciones para v1.2+ retro

Tres direcciones posibles, no excluyentes:

1. **Cap distinto pre/post codex.** El brief declara dos
   límites: `cap_initial` (sub-agente) y `cap_with_fixups` (post
   codex). Si fix-ups exceden `cap_with_fixups`, paro y consulto.
2. **Cap solo aplica a PR final.** Lo que importa es el LOC del
   merge. Sub-agente puede entregar bajo cap; codex añade lo que
   añada; producto consulta si total final supera cap. Más
   simple, mismo resultado pragmático que hoy pero hace
   explícito que el cap es del merge, no del primer push.
3. **Cap como guía soft, no hard.** Eliminar el lenguaje "PARAS
   y consultas" y reemplazar por "reporta al orquestador si
   excedes". Reconoce que en práctica el cap es soft-limit.

## Prioridad

Baja. No bloquea ningún PR del ciclo v1.1 actual. Para
considerar en retro post-cierre del ciclo (cuando se acabe Tier
2: PR-V1-33/34/35).

## Referencias

- PR-V1-31 conversación humano-orquestador 2026-04-26 que
  cristalizó el patrón.
- STATE.md historial completo de overages.
