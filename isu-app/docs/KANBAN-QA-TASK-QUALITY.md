# Kanban QA — Detección de Tareas de Baja Calidad

> Generado: 2026-03-25
> Alcance: 146 tareas no archivadas en la base de datos de Desk
> Tarea origen: `cfdfe9d4` — Kanban QA: detectar tareas de baja calidad o poco sentido

---

## 1. Resumen Ejecutivo

De 146 tareas analizadas, se detectaron **5 patrones de baja calidad** que afectan a **~45 tareas (31%)**. El problema principal es la generación automática excesiva por `idle-review`, que crea tareas micro-granulares, redundantes y a veces contradictorias.

| Problema | Tareas afectadas | Severidad |
|----------|-----------------|-----------|
| Fragmentación excesiva | ~18 | Alta |
| Redundancia / duplicados | ~12 | Alta |
| Tareas sin impacto real | ~8 | Media |
| Definición vaga o incompleta | ~4 | Media |
| Contradicción con reglas del proyecto | ~3 | Alta |

---

## 2. Problemas Detectados

### 2.1 Fragmentación Excesiva (ALTA)

Tareas que deberían ser una sola pero se dividieron en micro-pasos innecesarios.

**Caso 1: "Project Files" — 8 tareas para un solo feature**

| ID (corto) | Título | Tiempo resolución |
|------------|--------|-------------------|
| `91f19735` | project files | — |
| `906bf9a1` | project files tardaa mucho en cargar | — |
| `78ab1cff` | Project Files: diagnosticar loading infinito | — |
| `08908368` | Project Files: validar UX rápida en proyectos grandes | — |
| `6cf902fe` | Project Files Pumicon: diagnosticar "Empty project directory" | — |
| `1b86a9b1` | Project Files Pumicon: corregir render/carga del árbol | — |
| `a79f08ce` | Project Files Pumicon: corregir resolución de ruta/slug | — |
| `d9b928a4` | Project Files Pumicon: validar árbol real visible | — |

**Diagnóstico**: Una tarea "Implementar y depurar Project Files" habría bastado. La cadena diagnosticar→corregir→validar es un patrón de debug normal, no tareas separadas.

**Caso 2: "System Panel" — 7 tareas para un bug de subpestañas**

| ID (corto) | Título | Tiempo resolución |
|------------|--------|-------------------|
| `ea86c6a0` | System Panel: reproducir bug de subpestaña | 12 min |
| `daf7c70b` | System Panel: auditar estado activo de tabs/subtabs | 6 min |
| `b798d56e` | System Panel: revisar resets por polling | 8 min |
| `d960d408` | System Panel: revisar navegación interna y re-renders | 9 min |
| `1b4b17d6` | System Panel: proteger subpestaña frente a refresh | 13 min |
| `9a33a813` | System Panel: validar estabilidad en uso prolongado | 15 min |
| `10318e50` | System Panel: validar comportamiento en móvil y desktop | 17 min |

**Diagnóstico**: 7 tareas completadas en 6-17 minutos cada una. El bug + fix + validación es una sola tarea. La fragmentación no aporta trazabilidad, solo ruido.

**Caso 3: Tests de InvestmentDesk — 4 tareas solapantes**

| ID (corto) | Título |
|------------|--------|
| `974d5227` | Añadir tests unitarios para parse_briefing.py (extract_tickers, validate_frontmatter) |
| `3883dd95` | Añadir tests unitarios para extract_title, extract_section y _extract_bullet_points |
| `16876e21` | Añadir tests unitarios para funciones críticas sin cobertura en parse_briefing.py y generate_daily_summary.py |
| `1074eef5` | Añadir tests unitarios para generate_daily_summary.py |

**Diagnóstico**: La tarea `16876e21` ya cubre las otras tres. Cuatro tareas de testing para dos archivos es fragmentación pura.

---

### 2.2 Redundancia / Duplicados (ALTA)

Tareas que resuelven el mismo problema con distinto título.

| Grupo | Tareas redundantes | Problema |
|-------|-------------------|----------|
| HTML escaping | `4387d4fc` (Fix escaping inconsistente HTML), `e51206dd` (Escapar HTML en descripción) | Mismo fix: aplicar `escHtml()` a campos dinámicos |
| Credenciales | `3816c274` (Eliminar credenciales hardcodeadas en app.py), `3f20c267` (Eliminar credenciales en texto plano del README) | Mismo concern, deberían ser una tarea |
| Pumicon draw fix | `0981bbaa` (Fix - Pumicon: repartir fichas), `edd348e9` (Play/Draw fix: robas fichas jugadas), `70d62f61` (Fichas entre rondas - Fix) | Tres títulos distintos para el mismo bug |
| Bullet points | `7c61e9a5` (Extraer helper _extract_bullet_points), parte de `3883dd95` (tests para _extract_bullet_points) | Refactor + test como tareas separadas cuando son el mismo cambio |
| Stopwords | `aa00bfbb` (Añadir códigos de país a TICKER_STOPWORDS), `b1451031` (Unificar filtro de stopwords) | Dos tareas sobre la misma lista de stopwords |

---

### 2.3 Tareas Sin Impacto Real (MEDIA)

Tareas que se completaron pero cuyo valor es cuestionable.

| ID (corto) | Título | Razón de bajo impacto |
|------------|--------|----------------------|
| `7d3575bb` | Usar constante HAND_MAX_PER_ROW de Constants.ts | Cambio cosmético: reemplazar `14` por `HAND_MAX_PER_ROW` (que vale 14). No hay riesgo de divergencia en 2 sitios. |
| `90653647` | Consolidar rounding en ScoringPipeline | Prioridad `baja`, diferencia de redondeo imperceptible al jugador. Esfuerzo > beneficio. |
| `d78afda1` | Extraer now_str() a módulo compartido | Duplicación en 2 scripts de 50 líneas. Crear un módulo compartido para una función de 1 línea es sobre-ingeniería. |
| `cf8a994f` | Añadir logging cuando se ignoran briefings duplicados | Logging defensivo en un flujo que procesa ~1 briefing/día. Señal/ruido desfavorable. |

---

### 2.4 Definición Vaga o Incompleta (MEDIA)

| ID (corto) | Título | Problema |
|------------|--------|----------|
| `0981bbaa` | Fix - Pumicon | Título no describe el bug. Solo dice "Fix". |
| `f40ad054` | Desk tiles - fix | "Desk tiles" no es un concepto del proyecto. Título confuso. |
| `e65c1afd` | Revisar manual - Claude | Sin descripción. ¿Qué manual? ¿Revisar qué? |
| `0bb2cefd` | Revisar - Saco Jokers | Vago. ¿Revisar qué del saco de jokers? |

---

### 2.5 Tareas que Contradicen Reglas del Proyecto (ALTA)

| ID (corto) | Título | Contradicción |
|------------|--------|---------------|
| `3816c274` | Eliminar credenciales hardcodeadas en app.py | **app.py es archivo protegido**. La tarea se completó pero requería intervención manual según las reglas. Además, eliminar los defaults rompe el arranque del servidor — fue exactamente el incidente documentado en `e70cba58`. |
| `fbc52424` | Añadir validación de longitud en creación de tareas | Modifica app.py (protegido). |
| `53195ccf` | Añadir autenticación al endpoint /api/webhook/task-progress | Modifica app.py (protegido). |

---

## 3. Análisis por Fuente de Creación

| Fuente | Tareas | % del total | Calidad media | Problema principal |
|--------|--------|-------------|---------------|-------------------|
| `idle-review` | 84 | **57%** | ★★★☆☆ | Micro-granularidad, redundancia, sobre-ingeniería |
| `telegram` | 41 | 28% | ★★★★☆ | Ocasionalmente vagas (depende del contexto del mensaje) |
| `desk-ui` | 20 | 14% | ★★★☆☆ | Títulos vagos, duplicados de bugs Pumicon |
| `desk-seed` | 1 | 1% | ★★★★☆ | N/A (solo 1 tarea) |

### El problema de `idle-review`

El 57% de las tareas fueron generadas automáticamente por el proceso `idle-review`. Este es el factor #1 de ruido en el kanban:

1. **Genera tareas de código con líneas exactas** — útil cuando es un bug real, ruido cuando es un refactor marginal
2. **No deduplica** contra tareas existentes — crea tareas nuevas aunque el problema ya esté registrado
3. **Fragmenta cambios atómicos** — "extraer helper" + "añadir tests para helper" + "usar helper en X" como 3 tareas
4. **Prioriza demasiadas como `alta`** — 77 de 146 tareas son `alta` (53%), lo que diluye el significado de la prioridad
5. **Genera tareas sobre archivos protegidos** sin verificar las reglas de sandbox

**Distribución de idle-review por tipo:**

| Categoría | Cantidad |
|-----------|----------|
| Añadir feature/mejora | 20 |
| Bugfix | 15 |
| Extraer/Refactorizar | 10 |
| Testing | 6 |
| Validación | 5 |
| Cleanup | 4 |
| Consolidación | 3 |
| Seguridad | 2 |
| Otros | 19 |

---

## 4. Tareas Completadas en < 5 minutos

30 tareas se resolvieron en menos de 15 minutos (muchas en 1-3 min). Esto indica:

- O la tarea era trivial y no debía ser una tarea (ruido)
- O se resolvió como parte de otra tarea y se cerró en batch (fragmentación artificial)

Las más extremas (1-2 min) probablemente se cerraron como efecto colateral de otro cambio.

---

## 5. Recomendaciones Accionables

### R1: Filtro de calidad para `idle-review` (PRIORITARIA)

Antes de que `idle-review` cree una tarea, debería verificar:
- [ ] ¿Ya existe una tarea similar? (búsqueda por keywords en título)
- [ ] ¿El archivo afectado está en la lista de protegidos? → no crear tarea
- [ ] ¿El cambio es >10 líneas de impacto? → si no, agrupar en "limpieza menor"
- [ ] ¿La prioridad es realmente `alta`? → solo si es bug, seguridad, o datos corruptos

### R2: Regla de agrupación

Prohibir tareas que sigan el patrón:
- "Diagnosticar X" → "Corregir X" → "Validar X" como tareas separadas
- "Extraer Y" → "Añadir tests para Y" → "Usar Y en Z" como tareas separadas

Una tarea = un entregable verificable completo.

### R3: Calibración de prioridades

Actualmente el 53% de tareas son `alta`. Propuesta:
- **Crítica**: datos corruptos, seguridad activa, caída de servicio
- **Alta**: bug visible para el usuario, bloqueo de desarrollo
- **Media**: mejora funcional, refactor con beneficio claro
- **Baja**: cosmético, tech-debt menor, nice-to-have

### R4: Requisitos mínimos para crear tarea

| Campo | Mínimo aceptable |
|-------|------------------|
| Título | >15 chars, verbo + sustantivo concreto (no "Fix - Pumicon") |
| Descripción | >50 chars o referencia a issue/doc externo |
| Proyecto | Obligatorio |
| Prioridad | Justificada (no default a `alta`) |

### R5: Limpieza inmediata sugerida

Tareas activas que deberían revisarse:
- `d0b6be6d` (Pumicon TextStyle refactor, en `en_progreso` pero source=`idle-review`) — ¿sigue siendo relevante o fue absorbida por otro cambio?
- Las 3 tareas Kanban QA pendientes (`743002f8`, `22dd97f8`, `9192065d`) — verificar si este informe las cubre total o parcialmente

---

## 6. Métricas de Salud del Kanban

| Métrica | Valor | Estado |
|---------|-------|--------|
| Tareas activas (no hecha/archivada) | 5 | OK |
| Tareas completadas | 141 | OK |
| % generadas por automático | 57% | ALERTA |
| % prioridad alta | 53% | ALERTA |
| Duplicados detectados | ~12 | ALERTA |
| Tareas sobre archivos protegidos | 3+ | ALERTA |
| Tareas resueltas <5 min | ~15 | ADVERTENCIA |
| Ratio señal/ruido estimado | 70/30 | Aceptable pero mejorable |

---

*Análisis generado a partir de la base de datos SQLite de Desk (146 tareas no archivadas, 21 tablas, 4 proyectos).*
