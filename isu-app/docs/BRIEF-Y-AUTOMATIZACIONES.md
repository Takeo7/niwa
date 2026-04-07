# Brief Diario y Automatizaciones — Estado y Plan

> Fecha: 2026-03-23
> Estado: **PENDIENTE** — documentado, no activar cambios todavía.
> Origen: Tarea de Arturo vía Telegram, confirmada como to-do/pendiente.

---

## 1. Estado actual de los cron jobs

Hay **4 jobs activos** en `cron/jobs.json`. Todos con `enabled: true` y ejecutándose:

| # | ID | Horario | Tiene Skill | Tiene Manifest | Estado |
|---|-----|---------|-------------|----------------|--------|
| 1 | `daily-evening-brief` | 21:00 Madrid | ✅ SKILL.md completo | ✅ routine.json | ✅ Bien estructurado |
| 2 | `morning-brief-arturo` | 08:00 Madrid | ❌ No | ❌ No | ⚠️ Ad-hoc, sin skill |
| 3 | `desk-yume-15min-review` | */15 UTC | ✅ SKILL.md completo | ✅ routine.json | ✅ Bien estructurado |
| 4 | `daily-improvement-arturo` | 08:00 Madrid | ❌ No | ❌ No | ⚠️ Ad-hoc, sin skill |

### Diagnóstico

- **Bien**: El brief nocturno (21:00) y la revisión de Desk (15 min) están correctamente diseñados con el patrón de 3 capas (scheduler → skill → delivery).
- **Problema 1**: El brief matinal (08:00) duplica parte del nocturno (noticias + tareas del día). No tiene skill, no tiene manifest, y no pasa por `sync-routine-jobs.py`.
- **Problema 2**: "Mejora diaria Yume" (08:00) es un job vago que ejecuta cambios autónomos sin skill definido. Riesgo de acciones no deseadas.
- **Problema 3**: Ambos jobs de las 08:00 se ejecutan a la misma hora y no están gestionados por el sync script.

---

## 2. Enfoque propuesto para el brief diario

### Opción recomendada: Un brief nocturno + un brief matinal diferenciado

| Brief | Hora | Contenido | Propósito |
|-------|------|-----------|-----------|
| **Nocturno** (existe) | 21:00 | Tareas de mañana + Top 5 noticias del día | Planificación y conciencia situacional |
| **Matinal** (a rediseñar) | 08:00 | Agenda del día + estado de delegaciones + alertas urgentes | Arranque operativo del día |

**Diferencia clave**: El nocturno mira hacia mañana y resume el mundo. El matinal mira hacia hoy y resume el estado operativo.

### Lo que NO debe hacer el matinal

- No repetir las noticias del nocturno (ya se leyeron anoche).
- No buscar en web (el nocturno ya cubrió eso).
- No ser un duplicado del nocturno con distinto horario.

### Contenido sugerido para el matinal (pendiente de crear skill)

1. Agenda del día: tareas con deadline hoy, eventos de calendario.
2. Estado de delegaciones activas (qué está working, qué está bloqueado).
3. Alertas: tareas urgentes que entraron durante la noche.
4. Briefings de mercado si hay ingestión activa (futuro).

---

## 3. Inventario de automatizaciones

### A. Activas y bien definidas (no tocar)

| Automatización | Tipo | Frecuencia | Skill |
|---|---|---|---|
| Brief nocturno | OpenClaw cron → agentTurn | Diario 21:00 | `daily-evening-brief` |
| Revisión Desk | OpenClaw cron → agentTurn | Cada 15 min | `desk-review` |

### B. Activas pero sin estructura (necesitan rediseño)

| Automatización | Tipo | Frecuencia | Acción pendiente |
|---|---|---|---|
| Brief matinal | OpenClaw cron (raw) | Diario 08:00 | Crear skill, crear manifest, diferenciar del nocturno |
| Mejora diaria | OpenClaw cron (raw) | Diario 08:00 | Evaluar si se mantiene. Si sí, crear skill con scope claro |

### C. Diseñadas pero no implementadas (futuro)

| Automatización | Tipo | Diseño en | Estado |
|---|---|---|---|
| Ingestión de briefings n8n | n8n → POST /api/briefings | `BRIEFING-INGESTION-DESIGN.md` | Backend API lista, falta workflow n8n |
| Prompt injection scan | n8n workflow | `prompt-injection-scan-workflow.json` | Workflow exportado, verificar si activo en n8n |
| Claude coding workflow | n8n workflow | `claude-coding-workflow.json` | Workflow exportado, no verificado |
| Drive/SharePoint safe ingest | n8n workflow | `drive-sharepoint-safe-ingest.json` | Workflow exportado, no verificado |
| Calendario (Google/Outlook) | Integración futura | Mencionado en SKILL.md | Sin diseño |

### D. Scripts de soporte (activos)

| Script | Propósito | Usado por |
|---|---|---|
| `scripts/routines/daily-evening-brief.sh` | Query Desk para datos del brief nocturno | `daily-evening-brief` |
| `scripts/sync-routine-jobs.py` | Sincroniza manifests → cron/jobs.json | Gestión de rutinas |
| `scripts/delegate.sh` | Delegar tareas a agentes | `desk-review` |
| `scripts/create-routine.sh` | Crear nueva rutina con plantilla | Manual |

---

## 4. Acciones pendientes (TO-DO)

Estas acciones están documentadas pero **NO se deben ejecutar** hasta que Arturo lo indique:

### Prioridad alta

- [ ] **Rediseñar brief matinal**: Crear `skills/morning-brief/SKILL.md` con contenido diferenciado del nocturno. Crear `routines/morning-brief/routine.json`.
- [ ] **Decidir sobre "Mejora diaria"**: ¿Se mantiene? Si sí, necesita un skill con scope acotado y criterios claros de qué puede tocar. Si no, desactivar.
- [ ] **Migrar jobs ad-hoc al sync script**: Los jobs `morning-brief-arturo` y `daily-improvement-arturo` no están gestionados por `sync-routine-jobs.py`. Crearles manifests o eliminarlos del cron.

### Prioridad media

- [ ] **Activar ingestión de briefings via n8n**: El backend API ya soporta briefings. Falta crear y activar el workflow `daily-market-briefing` en n8n.
- [ ] **Verificar workflows n8n existentes**: Comprobar cuáles de los workflows exportados están realmente activos en la instancia n8n.
- [ ] **Separar horarios de los jobs de las 08:00**: Si ambos se mantienen, escalonarlos (ej. matinal a las 07:30, mejora a las 08:30).

### Prioridad baja (futuro)

- [ ] Integrar calendario (Google/Outlook) como fuente para ambos briefs.
- [ ] Permitir respuesta interactiva al brief ("más sobre 3").
- [ ] Histórico de briefs en tabla `briefings` de Desk.
- [ ] RSS/APIs de noticias vía n8n para no depender de web search.

---

## 5. Resumen ejecutivo

El sistema de briefs y automatizaciones tiene buena base arquitectónica (protocolo de rutinas, skills, sync script). Los dos componentes principales (brief nocturno + revisión Desk) están bien diseñados. Los problemas son:

1. **Duplicación**: El brief matinal repite contenido del nocturno.
2. **Jobs sin estructura**: 2 de 4 jobs no siguen el patrón skill+manifest.
3. **Job de riesgo**: "Mejora diaria" ejecuta cambios autónomos sin criterios claros.

La solución es limpiar los jobs ad-hoc, crear skills para los que se mantengan, y diferenciar claramente el propósito de cada brief. Todo queda como pendiente hasta que Arturo dé luz verde.
