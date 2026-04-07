# InvestmentDesk — Backlog & Próximos Pasos

> Última revisión: 2026-03-23
> Estado: ordenado, sin tareas arrancadas. Todo queda en to-do/pendiente.

---

## Estado actual: ¿Qué funciona hoy?

- **Task management completo** — CRUD, kanban 7 estados, prioridades, deadlines, My Day
- **Proyectos** — CRUD con directorio y file tree browser
- **Briefings API** — CRUD completo con items (ticker, metric, signal, news, action)
- **Research Notes API** — CRUD completo con categorías, símbolos, tags
- **Calendar/Gmail** — OAuth listo, lectura de emails implementada
- **Agent dashboard** — estado de agentes (Yume, Claude Code, Iris), delegaciones
- **Chat con Yume** — via Claude Haiku directamente
- **Deploy** — Docker + Traefik en desk.yumewagener.com, auth por sesión + bearer token

---

## Backlog ordenado por prioridad

### P1 — Siguientes pasos inmediatos

| # | Tarea | Tipo | Notas |
|---|-------|------|-------|
| 1 | **Watchlist API** — implementar CRUD (`/api/watchlist`) | feature | Schema diseñado en ARCHITECTURE.md. Tabla definida pero no aplicada al DB. Endpoints: POST/GET/PATCH/DELETE. Incluir campos: symbol, entry_target, exit_target, stop_loss, alert_conditions, status |
| 2 | **n8n workflow `daily-market-briefing`** — crear y conectar al POST `/api/briefings` | integración | El endpoint ya acepta datos. Falta el workflow que alimente desde fuentes (Yahoo Finance, CoinMarketCap, etc.) con el `DESK_BRIEFING_TOKEN` |
| 3 | **Limpiar sistema de briefs** — diferenciar brief matinal vs nocturno | fix/refactor | Documentado en `docs/BRIEF-Y-AUTOMATIZACIONES.md`. Ambos duplican contenido. Crear skills dedicados con manifests |

### P2 — Funcionalidad core pendiente

| # | Tarea | Tipo | Notas |
|---|-------|------|-------|
| 4 | **File upload a proyectos** — `POST /api/projects/{id}/files` | feature | Spec completa en `TASK-project-files.md`. Incluye list y delete. UI: drag-and-drop |
| 5 | **Investment Query endpoint** — `/api/investment/query` | feature | Phase 3 de ARCHITECTURE.md. Recibe símbolo/tema → análisis. Requiere prompts Claude |
| 6 | **Daily Digest endpoint** — `/api/investment/digest` | feature | Phase 3. Genera resumen diario priorizado |
| 7 | **UI Briefings en Desk** — sección "Daily Intelligence" | frontend | Phase 4. Cards expandibles, filtros por categoría, vista de hoy |

### P3 — Mejoras y expansión

| # | Tarea | Tipo | Notas |
|---|-------|------|-------|
| 8 | **UI Watchlist** — tabla con símbolos, niveles, estado | frontend | Phase 4. Depende de #1 (Watchlist API) |
| 9 | **UI Research Notes** — vista con filtros por categoría/símbolo | frontend | Phase 4. API ya existe |
| 10 | **Alertas Telegram** — notificar triggers de watchlist | integración | Phase 5. Requiere #1 completado |
| 11 | **Routine `weekly-thesis-review`** — revisar tesis de research notes | rutina | Phase 5. Definir criterios de invalidación |
| 12 | **Routine `monthly-archive`** — archivar briefings >90 días | rutina | Phase 5. Política de retención mencionada pero no implementada |

### P4 — Deuda técnica / limpieza

| # | Tarea | Tipo | Notas |
|---|-------|------|-------|
| 13 | **Definir formato `alert_conditions_json`** | diseño | Mencionado en arquitectura, sin spec concreta |
| 14 | **Revisar "mejora diaria" job** — definir scope y criterios | fix | Ejecuta cambios autónomos sin criterios claros. Riesgo de acciones no deseadas |
| 15 | **Aplicar tabla `watchlist_items` al DB** | infra | Schema SQL existe pero no está aplicado a sqlite3 |

---

## Decisiones pendientes (requieren input de Arturo)

1. **Fuentes de datos para briefing**: ¿Yahoo Finance API, CoinMarketCap, RSS financieros, otra cosa?
2. **Formato de alertas watchlist**: ¿Porcentaje de cambio? ¿Precio absoluto? ¿Ambos?
3. **Criterios de digest diario**: ¿Qué priorizar en el resumen? ¿Sentimiento? ¿Volatilidad?
4. **Retención de briefings**: ¿90 días confirmado o ajustar?

---

## Archivos de referencia

| Archivo | Contenido |
|---------|-----------|
| `docs/INVESTMENTDESK-ARCHITECTURE.md` | Diseño completo del sistema (phases 1-5) |
| `docs/BRIEFING-INGESTION-DESIGN.md` | Spec de ingestion API |
| `docs/BRIEF-Y-AUTOMATIZACIONES.md` | Análisis de problemas con briefs + TODOs |
| `TASK-project-files.md` | Spec de file upload |
| `docs/DEPLOY_FLOW.md` | Procedimiento de deploy obligatorio |
| `db/schema.sql` | Schema completo incluyendo watchlist (no aplicado) |
| `backend/app.py` | API monolítica (~5700 líneas) |
