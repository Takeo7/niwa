# Kanban QA — Informe Accionable Final

> Fecha: 2026-03-25
> Alcance: 147 tareas, 31 commits, 4 días de historia (22-25 mar)
> Fuentes: git log, desk.sqlite3, informes QA previos

---

## Veredicto General

**La calidad del sistema de tareas se está degradando.** El score señal/ruido cayó de 100% (día 1) a 38% (hoy). La causa principal es `idle-review`, que genera el 83% de las tareas actuales, la mayoría triviales (cierre promedio: 3 minutos).

El proyecto Desk en sí avanzó bien: de skeleton a app funcional con auth, kanban, agentes y deploy en 3 días. Pero el sistema de gestión de tareas está generando más ruido que valor.

---

## 3 Problemas Críticos

### 1. idle-review inunda el kanban (CRÍTICO)

- **Dato**: 84 de 147 tareas (57%) vienen de idle-review
- **Hoy**: 83% de las tareas son automáticas, con cierre promedio de 3 min
- **Efecto**: el kanban se convirtió en un log de lint, no en una herramienta de planificación
- **Evidencia**: 18 tareas cerradas en <5 min solo hoy (62% del total del día)

### 2. Fragmentación y duplicados (ALTO)

- **31% de tareas** (~45) tienen problemas de calidad: fragmentación, redundancia o trivialidad
- **Caso típico**: "Project Files" se fragmentó en 8 tareas; "System Panel" en 7 tareas de 6-17 min cada una
- **Duplicados**: HTML escaping (2 tareas idénticas), credenciales (2 tareas), Pumicon draw fix (3 tareas)
- **Resultado**: métricas infladas sin valor real

### 3. Monolito app.py sin freno (ALTO)

- `app.py` tiene ~5700 líneas en un solo archivo
- Creció de 0 a ese tamaño en 3 días
- Es archivo protegido, pero idle-review sigue generando tareas que lo modifican (contradicción)
- Riesgo técnico #1 del proyecto

---

## 5 Conclusiones

1. **La velocidad de desarrollo es alta pero no sostenible** — 31 commits en 3 días, pero con deuda técnica acumulándose (monolito, commits grandes, archivos basura)

2. **idle-review necesita throttling urgente** — Su utilidad es real (encuentra bugs y mejoras de seguridad), pero el volumen sin filtro genera más ruido que señal

3. **La calidad mejora cuando hay intervención humana** — Las tareas de Telegram (28% del total) tienen calidad ★★★★☆ vs ★★★☆☆ de idle-review

4. **Las prioridades están descalibradas** — 53% de tareas son "alta" prioridad, lo que diluye el significado. Solo bugs, seguridad y caídas deberían ser alta

5. **Testing es el área más débil** — Solo 3.5% de tareas son de testing. La mayoría de tests los genera idle-review, no planificación deliberada

---

## Plan de Acción (ordenado por impacto)

### Inmediato (hoy-mañana)

| # | Acción | Responsable | Impacto |
|---|--------|-------------|---------|
| 1 | **Throttle idle-review a máx 10 tareas/día** | Config/manual | Score subiría de 38% a ~75% |
| 2 | **Filtro: no crear tareas sobre archivos protegidos** | idle-review config | Elimina contradicciones con sandbox |
| 3 | **Filtro: no crear tareas de <5 líneas de impacto** | idle-review config | Elimina ~40% del ruido |
| 4 | **Archivar las ~18 tareas ruido de hoy** | Manual/script | Limpia el kanban |

### Esta semana

| # | Acción | Responsable | Impacto |
|---|--------|-------------|---------|
| 5 | **Regla de agrupación**: diagnosticar+corregir+validar = 1 tarea | Proceso | Reduce fragmentación |
| 6 | **Deduplicación semántica** antes de crear tarea | idle-review | Elimina redundancia |
| 7 | **Prioridad por defecto = media** para idle-review | Config | Calibra prioridades |
| 8 | **Adoptar conventional commits** (`feat:`, `fix:`, `refactor:`) | Proceso | Facilita revisión |

### Próxima semana

| # | Acción | Responsable | Impacto |
|---|--------|-------------|---------|
| 9 | **Separar app.py en módulos** (routes, models, auth, templates) | Dev | Reduce deuda técnica #1 |
| 10 | **Campo `type` explícito en tareas** (bugfix, feature, security...) | Schema | Mejor clasificación |
| 11 | **Dashboard de salud del kanban** en Desk UI | Dev | Visibilidad continua |
| 12 | **QA semanal automático** (este formato, cada domingo) | Rutina | Tracking temporal |

---

## Métricas de Seguimiento

Revisar semanalmente para verificar que las acciones funcionan:

| Métrica | Actual (25 mar) | Objetivo |
|---------|-----------------|----------|
| Score señal/total | **38%** | >80% |
| % idle-review del total | **83%** | <40% |
| Tareas cerradas <5 min | **62%** | <10% |
| % prioridad alta | **41%** | <30% |
| Avg tiempo cierre (idle) | **3 min** | >30 min |
| Commits con scope excesivo | **13%** | <5% |

---

## Resumen para Audio

**En una frase**: El kanban del Desk se está ahogando en tareas automáticas triviales — idle-review genera el 83% del volumen con un cierre promedio de 3 minutos, y la calidad cayó de 5 estrellas a 2 en solo 4 días.

**Las 3 acciones más urgentes**:
1. Limitar idle-review a máximo 10 tareas por día
2. Prohibir que genere tareas sobre archivos protegidos
3. No crear tareas para cambios menores de 5 líneas

**Lo positivo**: el proyecto en sí avanzó rápido y bien. La seguridad se priorizó desde el inicio, los bugs se corrigen rápido, y la tendencia en calidad de commits mejora. El problema no es el desarrollo, es el sistema de gestión de tareas.

---

*Informe consolidado a partir de: KANBAN-QA-REPORT.md, KANBAN-QA-TASK-QUALITY.md, KANBAN-QA-IMPROVEMENT-TRACKING.md, KANBAN-QA-TASK-CLASSIFICATION.md y desk.sqlite3.*
