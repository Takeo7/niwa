# Kanban QA — Evolución de Calidad del Sistema de Tareas

> Generado: 2026-03-25
> Alcance: 147 tareas, 4 días de historia (22–25 mar 2026)
> Tarea origen: Kanban QA: medir mejora del sistema de tareas en el tiempo
> Basado en: KANBAN-QA-TASK-QUALITY.md (detección de baja calidad) y datos crudos de desk.sqlite3

---

## 1. Veredicto General

**La calidad de las tareas ha EMPEORADO ligeramente** entre el 22 y el 25 de marzo, principalmente por el aumento del peso de `idle-review` como fuente y el crecimiento de tareas-ruido cerradas en <5 minutos.

| Indicador | Tendencia | Dirección |
|-----------|-----------|-----------|
| Longitud media de título | 45 → 66 chars | **Mejora** ↑ |
| Longitud media de descripción | 140 → 407 chars | **Mejora** ↑ |
| % prioridad `alta` | 63% → 41% | **Mejora** ↑ |
| % tareas de `idle-review` | 0% → 83% | **Empeora** ↓ |
| Tareas cerradas <5 min (ruido) | 0 → 18 | **Empeora** ↓ |
| Ratio ruido/total | 0/27 (0%) → 18/29 (62%) | **Empeora** ↓ |

---

## 2. Evolución Día a Día

### Día 1 — 22 mar (Arranque)

| Métrica | Valor |
|---------|-------|
| Tareas creadas | 27 |
| Fuentes | telegram (20), desk-ui (6), desk-seed (1) |
| % idle-review | **0%** |
| % prioridad alta | 63% |
| Avg título | 45 chars |
| Avg descripción | 140 chars |
| Cerradas <5 min | **0** |

**Perfil**: Día de creación humana. Tareas procedentes de Telegram y UI, con descripciones cortas pero intencionales. Prioridad alta inflada (63%), pero sin ruido automático. Es la **mejor jornada en calidad de señal**.

### Día 2 — 23 mar (Entra idle-review)

| Métrica | Valor |
|---------|-------|
| Tareas creadas | 46 |
| Fuentes | idle-review (30), telegram (16) |
| % idle-review | **65%** |
| % prioridad alta | 63% |
| Avg título | 52 chars |
| Avg descripción | 328 chars |
| Cerradas <5 min | **11** |
| Avg cierre idle-review | 93 min |
| Avg cierre telegram | 12 min |

**Perfil**: Salto de volumen (+70%) por la entrada de `idle-review`. Las descripciones mejoran (más detalladas, con líneas de código), pero aparecen los primeros duplicados y fragmentaciones. 11 tareas cerradas en <5 min = 24% de ruido.

### Día 3 — 24 mar (Pico de volumen)

| Métrica | Valor |
|---------|-------|
| Tareas creadas | 45 |
| Fuentes | idle-review (30), desk-ui (15) |
| % idle-review | **67%** |
| % prioridad alta | **42%** ← mejora |
| Avg título | 55 chars |
| Avg descripción | 417 chars |
| Cerradas <5 min | **13** |
| Avg cierre idle-review | 12 min |

**Perfil**: La prioridad se calibra algo (baja a 42% de alta). Las descripciones siguen mejorando. Pero el cierre promedio de idle-review cae a 12 min — muchas tareas se cierran casi instantáneamente, confirmando que eran triviales o redundantes. 13 tareas <5 min = 29% de ruido.

### Día 4 — 25 mar (Hoy, degradación)

| Métrica | Valor |
|---------|-------|
| Tareas creadas | 29 |
| Fuentes | idle-review (24), telegram (5) |
| % idle-review | **83%** ← máximo |
| % prioridad alta | 41% |
| Avg título | 66 chars ← máximo (bueno) |
| Avg descripción | 407 chars |
| Cerradas <5 min | **18** |
| Avg cierre idle-review | **3 min** ← mínimo |

**Perfil**: El día más automatizado. 83% de las tareas vienen de `idle-review`, y el tiempo medio de cierre cae a **3 minutos** — la mayoría son ruido que se cierra inmediatamente. 18 de 29 tareas (62%) son ruido. Los títulos son más largos y descriptivos, pero eso es un artefacto del formato de `idle-review`, no calidad real.

---

## 3. Tendencias Clave

### Lo que MEJORA

1. **Calidad formal**: títulos más descriptivos (45→66 chars), descripciones más ricas (140→407 chars)
2. **Calibración de prioridad**: la proporción de `alta` bajó de 63% a 41%
3. **Deduplicación de títulos**: 0 duplicados exactos detectados (los duplicados son semánticos, no literales)

### Lo que EMPEORA

1. **Dominio de idle-review**: de 0% a 83% del volumen — el kanban se está convirtiendo en un log de lint
2. **Ratio señal/ruido**: de 0% a 62% de tareas cerradas en <5 min
3. **Tiempo medio de cierre**: las tareas de idle-review pasaron de 93 min (día 2) a 3 min (día 4), indicando que cada vez son más triviales
4. **Pérdida de voz humana**: las tareas de Telegram (las más intencionadas) pasaron de 20/día a 5/día

### Lo que se MANTIENE

1. **Tasa de completación**: consistentemente >95%
2. **Tareas activas (WIP)**: estable en 4-5 tareas
3. **No hay tareas bloqueadas crónicamente**: la 1 tarea bloqueada es reciente

---

## 4. Análisis: ¿Qué Está Pasando?

El sistema de tareas tiene **dos velocidades**:

| Canal | Velocidad | Calidad | Intención |
|-------|-----------|---------|-----------|
| Telegram + desk-ui | Lenta, deliberada | Alta | El usuario decide qué importa |
| idle-review | Rápida, automática | Baja-Media | Un script decide qué "podría mejorarse" |

El problema es que `idle-review` genera **más volumen que los humanos**, y sus tareas:
- Se cierran en minutos (señal de trivialidad)
- Fragmentan cambios naturales en micro-tareas
- Inflan las métricas de productividad sin valor real

Esto crea una **ilusión de actividad**: 147 tareas en 4 días parece impresionante, pero ~45 son ruido.

---

## 5. Scorecard de Calidad por Período

| Período | Señal | Ruido | Score (señal/total) | Calificación |
|---------|-------|-------|---------------------|--------------|
| 22 mar (pre-idle) | 27 | 0 | **100%** | ★★★★★ |
| 23 mar (idle entra) | 35 | 11 | **76%** | ★★★★☆ |
| 24 mar (pico) | 32 | 13 | **71%** | ★★★☆☆ |
| 25 mar (hoy) | 11 | 18 | **38%** | ★★☆☆☆ |
| **Global** | **105** | **42** | **71%** | ★★★☆☆ |

**La tendencia es claramente descendente.** De 5 estrellas a 2 en 4 días.

---

## 6. Recomendaciones para Revertir la Tendencia

### Inmediatas (hoy)

| # | Acción | Impacto esperado |
|---|--------|-----------------|
| 1 | **Throttle de idle-review**: máximo 10 tareas/día | Score subiría a ~75% |
| 2 | **Filtro de trivialidad**: no crear tareas que afecten <5 líneas de código | Elimina ~40% del ruido |
| 3 | **Archivar las 18 tareas ruido de hoy** si ya están cerradas | Limpia el kanban |

### A corto plazo (esta semana)

| # | Acción | Impacto esperado |
|---|--------|-----------------|
| 4 | **Deduplicación semántica**: antes de crear, buscar tareas similares por keywords | Elimina redundancia |
| 5 | **Regla de agrupación**: diagnosticar+corregir+validar = 1 tarea | Reduce fragmentación |
| 6 | **Prioridad por defecto = media** para idle-review (solo bugs = alta) | Calibra prioridades |

### A medio plazo (próxima semana)

| # | Acción | Impacto esperado |
|---|--------|-----------------|
| 7 | **Dashboard de salud**: widget en Desk que muestre score diario | Visibilidad continua |
| 8 | **Review semanal**: QA automático cada domingo con este mismo formato | Tracking temporal |

---

## 7. Métricas de Seguimiento Propuestas

Para medir si las acciones funcionan, trackear semanalmente:

| Métrica | Objetivo | Actual |
|---------|----------|--------|
| Score señal/total | >80% | 38% (hoy) |
| % idle-review del total | <40% | 83% (hoy) |
| Tareas cerradas <5 min | <10% del total | 62% (hoy) |
| % prioridad alta | <30% | 41% (hoy) |
| Avg tiempo de cierre | >30 min | 3 min (idle, hoy) |

---

*Análisis generado a partir de desk.sqlite3 (147 tareas, 4 días de historia). Complementa KANBAN-QA-TASK-QUALITY.md con la dimensión temporal.*
