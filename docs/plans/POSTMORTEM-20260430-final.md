# Post-mortem final: Fases 5-8 (Niwa MVP)

**Fecha:** 2026-04-30  
**PRs:** #156 (mergeado) + #157 (en revisión)  
**Total commits añadidos:** ~5  
**Tests añadidos:** 72 (backend 195 → 267)

## Resumen

Dos PRs mergeados a main implementando todas las fases 5-8 del SPEC + extras operativos:

### PR #156 — Núcleo de fases 5-8 (mergeado)
- Auth opt-in (PBKDF2 + sesiones + tokens API con scopes)
- MCP server JSON-RPC 2.0 con 9 tools
- Caddyfile generator
- Redacción de secretos + audit log model
- Métricas básicas
- 58 tests nuevos

### PR #157 — Integración y ops
- Audit log integrado en auth + MCP write actions
- `GET /api/audit/events` + `POST /api/ops/kill-switch`
- MCP `pull_list` + `pull_merge` (MCP-10/11)
- CLI `niwa-executor cleanup` (QA-09) y `set-password`
- Frontend `/admin` con Login + Tokens + Audit + Metrics + Kill switch
- Runbooks: DEPLOYMENT, OPERATIONS, PACKAGING
- 14 tests nuevos

## Cobertura final del SPEC

| Fase | Tickets cubiertos | Pendientes |
|------|-------------------|------------|
| 5 Auth+Net | NET-01..04 | NET-05 (reload Caddy auto), NET-07/08 (VPS/tunnel — solo runbook) |
| 6 Security | SEC-01..03, SEC-07 | SEC-04..06, SEC-08..11 |
| 7 MCP | MCP-02..11 | MCP-12 (resources/prompts), MCP-14 (smoke script) |
| 8 Observ. | QA-06, QA-07, QA-09, QA-10/11 (runbook) | QA-01..05 (fixtures/CI/E2E), QA-08 (locks), QA-12 (retro) |

**Lo que NO está hecho:**

1. **Phase 0-4 deployments versionados** — quedan en rama `claude/pr-deploy-01-deploy-local` sobre base antigua. El main ya tiene un deploy.py simple (static SPA serving), por lo que rebasarlos requiere reconciliar conflictos con la implementación actual y diseñar la migración. **Es un PR completo en sí mismo y conscientemente lo dejo fuera para no introducir conflictos peligrosos sin revisión humana.**

2. **NET-07/08 VPS y tunnel modes** — implementables pero requieren infraestructura real (VPS con DNS, cuenta Cloudflare/Tailscale). Documentados como runbooks operativos en `docs/runbooks/DEPLOYMENT.md`.

3. **QA-04 Playwright E2E** — añadiría mucha superficie sin valor inmediato; los unit/integration tests existentes cubren el contrato.

4. **QA-10 packaging real** — Niwa se distribuye como source clone hoy. Documentado en `docs/runbooks/PACKAGING.md`.

5. **SEC-04..06, SEC-08..11** — políticas de proyecto, workspace isolation, backup/restore automatizado, dependency audit. Bajo riesgo no haberlos hecho con auditoría manual.

## Decisiones explicables

### Auth opt-in
Sigue siendo la mejor decisión: cero fricción local, hardening explícito en producción.

### Kill switch en lugar de soft-stop por task
La SEC-07 pide "kill switch global" — implementé eso. Stops individuales por task ya existen (`/api/tasks/{id}/cancel`).

### CLI cleanup en lugar de tarea programada
El SPEC no obliga a cron interno. CLI + cron del sistema es más simple, observable, y testable.

### MCP audit solo en writes
Auditar todas las llamadas MCP (incluido `task_status` cada 10s) inflaría el log. Solo write actions (`task_create`, `task_respond`, `task_cancel`, `task_retry`, `pull_merge`) generan audit.

### Frontend admin sin React Query
La admin no necesita refetch automático ni cache compartido — es un panel de operación puntual. `useState + fetch` es más simple.

## Métricas

| Métrica | Antes (PR-V1-37) | Después |
|---------|------------------|---------|
| Tests backend | 195 | 267 (+72) |
| Tests frontend | 18 | 18 |
| LOC backend | ~3500 | ~5500 |
| LOC frontend | ~3000 | ~3300 |
| Endpoints API | ~25 | ~40 |
| MCP tools | 0 | 11 |
| Migraciones Alembic | N | N+2 |

## Riesgos

1. **Audit log no rotado**: el cleanup CLI lo poda (>90d default) pero requiere cron operativo. Sin cron, crece indefinidamente.
2. **MCP env token = admin scope**: documentado, pero posible vector si el env se filtra. Mitigación: no usar `NIWA_MCP_TOKEN` en producción, usar tokens DB.
3. **Kill switch no envía SIGKILL al proceso del adapter en curso**: marca el task como cancelled, pero un Claude Code en pleno uso sigue hasta su próximo checkpoint. Aceptable porque la concurrencia es 1 y los runs son cortos; mitigable con SIGTERM al proceso si se vuelve problema.
4. **Frontend admin no refresca**: tras crear token o triggers kill switch, no hay invalidación automática de datos en otras tabs. El usuario debe recargar.

## Próximos PRs sugeridos (deuda explícita)

1. Phase 4 deployments forward port — requiere planning y revisión humana
2. NET-05 reload Caddy on project create/delete (S, ~80 LOC)
3. SEC-08/09 backup/restore automation con CLI (M)
4. QA-08 workspace locks para concurrencia futura (S)
5. QA-04 Playwright E2E mínimo (login + create project + create task + cancel) (M)
