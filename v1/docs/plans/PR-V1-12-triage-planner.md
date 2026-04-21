# PR-V1-12 — Triage planner (SUPERSEDED)

> **Status: SUPERSEDED (2026-04-21).** La implementación combinada
> llegó a **494 LOC netas código+tests** tras 3 pases de
> compactación, 94 sobre el hard-cap estricto 400 de Semana 3.
> Product partner aprobó split:
>
> - `PR-V1-12a-triage-module.md` — módulo `triage.py` puro + 3 unit
>   tests (~256 LOC). Módulo existe, testeable aislado, NO se
>   invoca desde el executor.
> - `PR-V1-12b-triage-executor.md` — integración executor + 2
>   integration tests + extension fake CLI + 2 stubs legacy
>   (~238 LOC). Activa triage en el pipeline.
>
> Resolución Opción B del orquestador aplicada y persistida: SPEC
> §3 fija el enum `task_events.kind`; `kind="triage_split"` del
> brief original incompatible. Resuelto con
> `TaskEvent(kind="message", payload.event="triage_split",
> subtask_ids, rationale)`. Sin migración.
>
> PR #117 (intento combinado) cerrado sin merge; rama
> `claude/v1-pr-12-triage-planner` queda en remoto como referencia
> para 12a/12b.

---

*(Brief combinado original intacto abajo para referencia histórica.)*
