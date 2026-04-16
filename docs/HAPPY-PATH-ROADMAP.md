# Happy Path Roadmap — post sesión PRs 25-36

**Fecha:** 2026-04-16
**Estado actual:** el pipeline v0.2 funciona end-to-end en producción.
UI → tarea → executor → v0.2 routing → claude_code adapter → ficheros
creados → resultado visible en detalle de tarea.

## Qué funciona hoy

- [x] Fresh install `./niwa install --quick --mode assistant --yes`
- [x] Servicios estables (executor + hosting, NRestarts=0)
- [x] v0.2 routing pipeline (routing_decisions, backend_runs, state machine)
- [x] Claude ejecuta tareas con `--dangerously-skip-permissions`
- [x] Resultado de Claude visible en pestaña Detalles ("Resultado")
- [x] Tarea marcada como `hecha` solo si el adapter reporta `succeeded`
- [x] Health check post-install detecta crash-loops
- [x] Update desde UI tira de la rama correcta
- [x] Migraciones abortan si fallan

## Qué falta para happy path completo

### Prioridad 1 — UX mínima para que el usuario no se pierda

| # | Feature/Bug | Scope | LOC est. |
|---|-------------|-------|----------|
| 1 | **Renderizar markdown** en Resultado | Frontend: `react-markdown` | ~30 |
| 2 | **Auto-registro de proyecto** post-tarea | Backend hook + frontend minor | ~80 |
| 3 | **Notificación de errores** en la UI | Frontend: badge/toast en tarea | ~50 |

### Prioridad 2 — Control operacional

| # | Feature/Bug | Scope | LOC est. |
|---|-------------|-------|----------|
| 4 | Toggle dangerous mode en UI | Frontend component | ~30 |
| 5 | Bug 29: cookie Secure flag | Backend 1 línea | ~5 |
| 6 | Bugs 24+25: artifact_root + tmpdir | Backend quirúrgico | ~20 |

### Prioridad 3 — Infraestructura

| # | Feature/Bug | Scope | LOC est. |
|---|-------------|-------|----------|
| 7 | PR-12: tests E2E del contrato MCP | Tests + CI | ~200 |
| 8 | Bug 28: OAuth tokens encryption | Backend + key mgmt | ~200+ |
| 9 | Config DNS/dominios desde UI | Full-stack | ~300+ |
| 10 | Bug 16: chat multi-provider | Backend + frontend | ~200-400 |

## PRs sugeridos para siguiente sesión (en orden)

- **PR-37**: markdown rendering en Resultado (react-markdown).
- **PR-38**: auto-registro de proyecto post-tarea.
- **PR-39**: notificación/badge de error en tarea.
- **PR-40**: toggle dangerous mode.
- **PR-41**: cookie Secure + artifact_root + tmpdir (cleanup batch).

## Referencia

- Bugs documentados: `docs/BUGS-FOUND.md` (Bugs 1-32 + Features 1-4)
- Decisiones: `docs/DECISIONS-LOG.md`
- SPEC: `docs/SPEC-v0.2.md`
- Sesión de PRs 25-36: 2026-04-16, 14 PRs mergeados.
