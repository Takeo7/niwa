# Decisiones tomadas durante implementación v0.2

Cada entrada: fecha, PR, decisión, motivo.

Formato sugerido:

```
## YYYY-MM-DD — PR-XX

**Decisión:** qué se decidió.
**Motivo:** por qué.
**Alternativas consideradas:** qué se descartó y por qué.
**Impacto:** qué otras partes del sistema se ven afectadas.
```

---

## 2026-04-12 — PR-00

**Decisión:** El nuevo ADR de arquitectura v0.2 se numera como `0002-v02-architecture.md`, no `0001` como indica el SPEC.
**Motivo:** Los ADRs son secuenciales a nivel de proyecto, no se reinician por versión de producto. Ya existe `0001-niwa-yume-separation.md` (historia válida del proyecto, creado 2026-04-08). El SPEC tiene un error de numeración en este punto.
**Alternativas consideradas:** Renumerar el ADR existente o usar un esquema de numeración por versión. Descartadas porque romperían enlaces existentes y complicarían la trazabilidad.
**Impacto:** El SPEC queda implícitamente corregido — futuros PRs deben seguir la numeración secuencial (0003, 0004, etc.).
