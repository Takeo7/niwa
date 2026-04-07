# Kanban QA — Clasificación de Tareas por Tipo, Origen y Patrón

> Generado: 2026-03-25
> Fuente: base de datos `desk.sqlite3` — 147 tareas totales, 143 completadas
> Periodo: 2026-03-22 a 2026-03-25

---

## 1. Resumen Ejecutivo

| Dimensión | Hallazgo clave |
|-----------|---------------|
| **Tipo dominante** | Bugfixes (28) y features (27) representan ~38% de las tareas completadas |
| **Origen dominante** | `idle-review` genera el 57% de todas las tareas (84/147) |
| **Patrón de creación** | 100% de `idle-review` se crea en batches de 5; Telegram en batches de 4-7 |
| **Velocidad** | Telegram se cierra en ~11 min; idle-review en ~39 min; desk-ui en ~105 min |
| **Proyecto más activo** | `desk` (71 tareas), seguido de `investmentdesk` (31) y `pumicon` (29) |

---

## 2. Distribución por Tipo de Tarea

Clasificación basada en análisis de títulos (keywords: fix/corregir, implementar/crear/añadir, test, XSS/sanitiz/proteger, validar, extraer/eliminar/refactor, diagnosticar/auditar/revisar, QA/kanban).

| Tipo | Count | % | Descripción |
|------|-------|---|-------------|
| **bugfix** | 28 | 19.6% | Corrección de bugs funcionales (crashes, lógica rota, rendering) |
| **feature/add** | 27 | 18.9% | Nueva funcionalidad (endpoints, helpers, campos, UI components) |
| **other** | 25 | 17.5% | Tareas genéricas, configuración, miscelánea |
| **validation** | 16 | 11.2% | Validación de campos, formatos, estados, end-to-end |
| **refactor/cleanup** | 14 | 9.8% | Extracción de helpers, eliminación de duplicados, reorganización |
| **review/audit** | 12 | 8.4% | Auditorías de UI, mobile QA, revisión manual |
| **security** | 10 | 7.0% | XSS, path traversal, credenciales, sanitización |
| **qa/process** | 6 | 4.2% | Meta-tareas de calidad y proceso |
| **testing** | 5 | 3.5% | Tests unitarios (Vitest, pytest) |

---

## 3. Distribución por Origen (Source)

| Origen | Total | Completadas | % del total | Perfil |
|--------|-------|-------------|-------------|--------|
| **idle-review** | 84 | 83 | 57% | Tareas generadas automáticamente por el sistema de revisión continua |
| **telegram** | 41 | 39 | 28% | Tareas creadas manualmente por el usuario vía Telegram |
| **desk-ui** | 21 | 20 | 14% | Tareas creadas desde la interfaz web del Desk |
| **desk-seed** | 1 | 1 | 1% | Tarea de inicialización (seed) |

### Perfil de cada origen

**idle-review** — Genera predominantemente:
- features (24), bugfixes (16), refactoring (14), security (8), validation (7), testing (5)
- Es la fuente más técnica: cubre todo el espectro de mejora de código
- Siempre crea en batches de exactamente 5 tareas (excepto 1 batch de 4)
- Ciclo: cada ~2h durante la noche/madrugada (00:04, 01:03, 05:03, 06:05, 07:08)

**telegram** — Genera predominantemente:
- reviews/audits (9), validation (8), other (8), bugfixes (6), qa/process (5)
- Es la fuente más orientada a QA y revisión manual
- Batches de 4-7 tareas temáticas (ej: "System Panel: ..." x7, "Mobile QA: ..." x5)

**desk-ui** — Genera predominantemente:
- other (7), bugfixes (6), reviews (3)
- Tareas más informales y cortas ("Tooltip - fix", "Play/Draw fix")
- Sin patrón de batch; creación individual

---

## 4. Distribución por Proyecto

| Proyecto | Total | Tipos dominantes |
|----------|-------|-----------------|
| **desk** | 71 | other (13), validation (10), review/audit (10), bugfix (10), feature (9), security (6) |
| **investmentdesk** | 31 | feature (9), refactor (5), other (5), validation (4), testing (4) |
| **pumicon** | 29 | bugfix (12), feature (6), refactor (4) |
| **yume** | 16 | other (4), feature (3), bugfix (3) |

### Observaciones por proyecto:
- **desk**: Perfil equilibrado — recibe de todas las fuentes. Alto en validación y auditorías.
- **investmentdesk**: Perfil de proyecto nuevo — dominado por features y refactoring temprano.
- **pumicon**: Perfil de mantenimiento — dominado por bugfixes (41% de sus tareas).
- **yume**: Perfil de infraestructura — tareas variadas sin patrón definido.

---

## 5. Patrones Temporales

### Creación por día
| Día | Tareas creadas |
|-----|---------------|
| 2026-03-22 | 27 |
| 2026-03-23 | 46 |
| 2026-03-24 | 45 |
| 2026-03-25 | 29 |

### Velocidad de cierre (tareas con completed_at)
| Origen | Tareas con timestamp | Avg minutos |
|--------|---------------------|-------------|
| telegram | 10 | 11.0 min |
| idle-review | 83 | 38.8 min |
| desk-ui | 14 | 104.6 min |

**Nota**: Las tareas de Telegram se cierran rápido porque llegan como batches pre-planificados. Las de desk-ui tardan más porque suelen ser reportes de bugs que requieren investigación.

---

## 6. Patrones de Batch (Creación Simultánea)

El 85% de las tareas se crean en batches (mismo timestamp exacto):

| Origen | Patrón de batch |
|--------|----------------|
| **idle-review** | Siempre 5 tareas por batch, ~cada 2h. 16 batches detectados. |
| **telegram** | 4-7 tareas por batch, temáticas (ej: "System Panel" x7). 8 batches detectados. |
| **desk-ui** | 1 batch de 7 tareas (operacional); resto individual. |

Esto indica que:
1. `idle-review` tiene un pipeline fijo que genera exactamente 5 mejoras por ciclo
2. Telegram batches son planificación manual del usuario (épicas desglosadas)
3. desk-ui es mayoritariamente input individual/ad-hoc

---

## 7. Prioridad vs Origen

| Origen | Alta | Media | Baja |
|--------|------|-------|------|
| idle-review | 46 (55%) | 37 (44%) | 1 (1%) |
| telegram | 28 (68%) | 13 (32%) | 0 |
| desk-ui | 3 (14%) | 17 (81%) | 1 (5%) |

- Telegram tiene la mayor proporción de tareas alta prioridad (68%)
- desk-ui es mayoritariamente media prioridad (input informal)
- idle-review asigna alta a ~mitad de sus findings

---

## 8. Conclusiones y Recomendaciones

### Hallazgos clave:
1. **idle-review domina el volumen** pero genera tareas técnicas de buena calidad (security fixes, refactoring, testing)
2. **Telegram es el canal del usuario** para planificación estratégica — batches temáticos bien desglosados
3. **desk-ui captura bugs ad-hoc** con descripciones informales que podrían beneficiarse de templates
4. **Testing es el tipo más escaso** (3.5%) — la mayoría de tests los genera idle-review, no el usuario
5. **Pumicon acumula bugfixes** — podría indicar deuda técnica o falta de testing preventivo

### Para mejorar:
- Considerar añadir un campo `type` explícito a las tareas (bugfix, feature, security, refactor, test, review) en lugar de inferirlo del título
- Evaluar si el rate de 5 tareas/batch de idle-review es óptimo o genera ruido
- Aumentar proporción de testing proactivo vs reactivo (bugfixes)
