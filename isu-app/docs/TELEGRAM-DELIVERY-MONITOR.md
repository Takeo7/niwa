# Telegram Delivery Monitor — Weekly Report

**Periodo de monitorización:** 2026-03-24 a 2026-03-31
**Objetivo:** Detectar patrones de `delivered=false` con output válido en crons.

Cada entrada es un snapshot de las últimas 24h de logs JSONL (generado automáticamente a las 23:55 UTC).

### Infraestructura de monitorización

- **Script:** `scripts/telegram-delivery-monitor.py` — analiza JSONL de las últimas 24h, detecta runs sospechosos (output válido + no entregado)
- **Crontab:** `55 23 * * *` — ejecución diaria persistente, auto-remove tras 2026-03-31
- **Logs:** `/tmp/telegram-delivery-monitor.log`
- **Datos fuente:** `/home/yume/.openclaw/cron/runs/*.jsonl`
- **Auditoría previa (semana anterior):** `Desk/docs/TELEGRAM-DELIVERY-AUDIT.md`

### Hipótesis bajo seguimiento

| # | Hipótesis | Estado | Evidencia día 1 |
|---|---|---|---|
| H1 | El agente genera texto que el gateway no interpreta como mensaje | Confirmada parcial | 2-3 runs con prefijo "Para Arturo por Telegram:" no entregados |
| H2 | El gateway tiene bug con formato del output | Bajo observación | `muted=true` + dedup posible en desk-review (14 mensajes repetitivos no entregados) |
| H3 | Rate limiting de Telegram API | No observado hoy | 0 errores (mejorado vs semana anterior con 45 errores) |
| H4 | Timeout del gateway en runs largos | 1 caso | idle-project-review 337s → no entregado |

---

## 2026-03-24 (generado 2026-03-24T19:52:07Z)

| Job | Runs | Delivered | Not-delivered | Errors | Rate | Notes |
|---|---|---|---|---|---|---|
| daily-evening-brief | 0 | - | - | - | - | No runs |
| daily-improvement-arturo | 1 | 1 | 0 | 0 | 100% | OK |
| desk-yume-15min-review | 96 | 25 | 71 | 0 | 26% | **15 suspicious** |
| desk-yume-5min-review | 0 | - | - | - | - | No runs |
| idle-project-review | 24 | 6 | 18 | 0 | 25% | **1 suspicious** |
| morning-brief-arturo | 1 | 1 | 0 | 0 | 100% | OK |

### Desglose por provider

| Provider | Delivered | Failed | Errors | Rate |
|---|---|---|---|---|
| openai-codex | 33 | 89 | 0 | 27% |

### Runs sospechosos (output válido + no entregado)

**desk-yume-15min-review** — 15 suspicious runs (summary present but not delivered):
  - 11:15 UTC: model=gpt-5.4, tokens=465, duration=15832ms, summary_len=33
    > `Leo el skill y ejecuto el review.`
  - 16:00 UTC: model=gpt-5.4, tokens=477, duration=20340ms, summary_len=91
    > `[desk-review] 1 tarea bloqueada: Monitorizar delivery de Tel…`
  - 16:15 UTC: model=gpt-5.4, tokens=382, duration=16988ms, summary_len=117
    > `Para Arturo por Telegram: [desk-review] 1 tarea bloqueada: M…`
  - 16:30–19:00 UTC: 11 runs with same pattern — `[desk-review] 1 tarea bloqueada...` (summary_len=91, not delivered)
  - 19:15 UTC: model=gpt-5.4, tokens=568, duration=15451ms, summary_len=115
    > `Para Arturo (Telegram): [desk-review] 1 tarea bloqueada: Mon…`

**idle-project-review** — 1 suspicious run (summary present but not delivered):
  - 10:06 UTC: model=gpt-5.4, tokens=862, duration=337300ms, summary_len=88
    > `Para Arturo por Telegram: [idle-review] 5 tareas nuevas en D…`

### Hallazgos día 1

1. **Gateway no entrega mensajes con prefijo "Para Arturo por Telegram:"** — El agente antepone instrucciones de routing al mensaje, pero el gateway espera el contenido directo. Esto afecta 2-3 runs donde el summary empieza con "Para Arturo..."
2. **Gateway no entrega mensajes `[desk-review]` repetitivos** — 14 de 15 suspicious son el mismo mensaje reportando esta tarea como bloqueada. Posible: el gateway tiene dedup o el `muted=true` impide delivery cuando el contenido es repetitivo.
3. **Run largo (337s) no entregado** — idle-project-review tardó 5.6 min y generó mensaje válido pero no se entregó. Posible timeout del gateway.
4. **100% openai-codex hoy** — Sin fallos de Gemini (no se usó como provider hoy).

---

## 2026-03-25 (generado 2026-03-25T23:55:01Z)

| Job | Runs | Delivered | Not-delivered | Errors | Rate | Notes |
|---|---|---|---|---|---|---|
| daily-evening-brief | 0 | - | - | - | - | No runs |
| daily-improvement-arturo | 1 | 1 | 0 | 0 | 100% | OK |
| daily-investment-review | 1 | 0 | 1 | 0 | 0% | OK |
| desk-yume-15min-review | 89 | 0 | 89 | 0 | 0% | **29 suspicious** |
| desk-yume-5min-review | 0 | - | - | - | - | No runs |
| idle-project-review | 35 | 1 | 34 | 0 | 2% | **11 suspicious** |
| morning-brief-arturo | 1 | 1 | 0 | 0 | 100% | OK |

### Desglose por provider

| Provider | Delivered | Failed | Errors | Rate |
|---|---|---|---|---|
| openai-codex | 3 | 124 | 0 | 2% |

### Runs sospechosos (output válido + no entregado)

**desk-yume-15min-review** — 29 suspicious runs (summary present but not delivered):
  - 00:00 UTC: model=gpt-5.4, tokens=572, duration=17749ms, summary_len=31
    > `Ejecutando la revisión de Desk.`
  - 07:30 UTC: model=gpt-5.4, tokens=426, duration=31235ms, summary_len=104
    > `[desk-review] 1 tarea bloqueada: Extraer TextStyle boilerpla…`
  - 11:45 UTC: model=gpt-5.4, tokens=615, duration=23356ms, summary_len=72
    > `Voy a leer el skill y ejecutar la revisión sin tocar estados…`
  - 13:15 UTC: model=gpt-5.4, tokens=600, duration=24855ms, summary_len=118
    > `Para Arturo (Telegram): [desk-review] 1 tareas bloqueadas: I…`
  - 13:30 UTC: model=gpt-5.4, tokens=578, duration=18394ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 13:45 UTC: model=gpt-5.4, tokens=391, duration=13428ms, summary_len=116
    > `Para Arturo (Telegram): [desk-review] 1 tarea bloqueada: Inv…`
  - 14:00 UTC: model=gpt-5.4, tokens=675, duration=25858ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 14:15 UTC: model=gpt-5.4, tokens=450, duration=18588ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 14:30 UTC: model=gpt-5.4, tokens=552, duration=19359ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 14:45 UTC: model=gpt-5.4, tokens=475, duration=15475ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 15:01 UTC: model=gpt-5.4, tokens=504, duration=15299ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 15:15 UTC: model=gpt-5.4, tokens=525, duration=25485ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 15:30 UTC: model=gpt-5.4, tokens=500, duration=16009ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 15:45 UTC: model=gpt-5.4, tokens=365, duration=23296ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 16:00 UTC: model=gpt-5.4, tokens=624, duration=36369ms, summary_len=92
    > `[desk-review] 1 tarea bloqueada: Investigar APIs de delivery…`
  - 16:30 UTC: model=gpt-5.4, tokens=479, duration=14918ms, summary_len=272
    > `[desk-review] 5 tareas bloqueadas: Implementar planificador …`
  - 17:30 UTC: model=gpt-5.4, tokens=423, duration=21122ms, summary_len=89
    > `[desk-review] 1 tarea bloqueada: Crear API de agregación de …`
  - 19:15 UTC: model=gpt-5.4, tokens=574, duration=33943ms, summary_len=480
    > `[desk-review] 10 tareas bloqueadas: New task Modal; Extraer …`
  - 19:30 UTC: model=gpt-5.4, tokens=397, duration=14668ms, summary_len=166
    > `Para Arturo por Telegram: [desk-review] 3 tareas bloqueadas:…`
  - 19:45 UTC: model=gpt-5.4, tokens=435, duration=18759ms, summary_len=126
    > `[desk-review] 3 tareas bloqueadas: New task Modal; Manduka -…`
  - 20:01 UTC: model=gpt-5.4, tokens=591, duration=26271ms, summary_len=86
    > `[desk-review] 1 tarea bloqueada: Mostrar timeline de etapas …`
  - 20:15 UTC: model=gpt-5.4, tokens=563, duration=21268ms, summary_len=86
    > `[desk-review] 1 tarea bloqueada: Mostrar timeline de etapas …`
  - 22:15 UTC: model=gpt-5.4, tokens=497, duration=17054ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 22:30 UTC: model=gpt-5.4, tokens=917, duration=22961ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 22:45 UTC: model=gpt-5.4, tokens=429, duration=16128ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 23:00 UTC: model=gpt-5.4, tokens=447, duration=19740ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 23:15 UTC: model=gpt-5.4, tokens=537, duration=20111ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 23:30 UTC: model=gpt-5.4, tokens=453, duration=19348ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 23:45 UTC: model=gpt-5.4, tokens=357, duration=16771ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
**idle-project-review** — 11 suspicious runs (summary present but not delivered):
  - 00:04 UTC: model=gpt-5.4, tokens=471, duration=207240ms, summary_len=64
    > `[idle-review] (5) tareas nuevas en Desk. Revísalas en el kan…`
  - 01:03 UTC: model=gpt-5.4, tokens=736, duration=167937ms, summary_len=81
    > `Telegram a Arturo: [idle-review] 5 tareas nuevas en Desk. Re…`
  - 05:03 UTC: model=gpt-5.4, tokens=516, duration=170291ms, summary_len=94
    > `Enviar a Arturo por Telegram: [idle-review] (4) tareas nueva…`
  - 06:05 UTC: model=gpt-5.4, tokens=1052, duration=287631ms, summary_len=62
    > `[idle-review] 5 tareas nuevas en Desk. Revísalas en el kanba…`
  - 07:08 UTC: model=gpt-5.4, tokens=488, duration=208637ms, summary_len=64
    > `[idle-review] (5) tareas nuevas en Desk. Revísalas en el kan…`
  - 08:05 UTC: model=gpt-5.4, tokens=748, duration=291351ms, summary_len=88
    > `Para Arturo por Telegram: [idle-review] 5 tareas nuevas en D…`
  - 09:04 UTC: model=gpt-5.4, tokens=776, duration=192158ms, summary_len=62
    > `[idle-review] 3 tareas nuevas en Desk. Revísalas en el kanba…`
  - 10:32 UTC: model=gpt-5.4, tokens=402, duration=153228ms, summary_len=62
    > `[idle-review] 4 tareas nuevas en Desk. Revísalas en el kanba…`
  - 11:33 UTC: model=gpt-5.4, tokens=662, duration=173075ms, summary_len=62
    > `[idle-review] 3 tareas nuevas en Desk. Revísalas en el kanba…`
  - 16:00 UTC: model=gpt-5.4, tokens=382, duration=22754ms, summary_len=24
    > `action=skip; no enviado.`
  - 18:30 UTC: model=gpt-5.4, tokens=444, duration=26119ms, summary_len=38
    > `Busco el script correcto y lo ejecuto.`

---

## 2026-03-26 (generado 2026-03-26T23:55:01Z)

| Job | Runs | Delivered | Not-delivered | Errors | Rate | Notes |
|---|---|---|---|---|---|---|
| daily-evening-brief | 0 | - | - | - | - | No runs |
| daily-improvement-arturo | 1 | 0 | 1 | 0 | 0% | **1 suspicious** |
| daily-investment-review | 1 | 0 | 1 | 0 | 0% | OK |
| desk-yume-15min-review | 96 | 35 | 61 | 0 | 36% | **29 suspicious** |
| desk-yume-5min-review | 0 | - | - | - | - | No runs |
| idle-project-review | 71 | 40 | 31 | 0 | 56% | OK |
| morning-brief-arturo | 1 | 1 | 0 | 0 | 100% | OK |

### Desglose por provider

| Provider | Delivered | Failed | Errors | Rate |
|---|---|---|---|---|
| anthropic | 36 | 0 | 0 | 100% |
| openai-codex | 40 | 94 | 0 | 29% |

### Runs sospechosos (output válido + no entregado)

**daily-improvement-arturo** — 1 suspicious runs (summary present but not delivered):
  - 07:07 UTC: model=gpt-5.4, tokens=6931, duration=273926ms, summary_len=1030
    > `Qué mejoré: arreglé el flujo de rutinas gestionadas y migré …`
**desk-yume-15min-review** — 29 suspicious runs (summary present but not delivered):
  - 00:00 UTC: model=gpt-5.4, tokens=419, duration=25545ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 00:15 UTC: model=gpt-5.4, tokens=617, duration=23080ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 00:30 UTC: model=gpt-5.4, tokens=574, duration=22171ms, summary_len=177
    > `Para Arturo por Telegram:  [desk-review] 3 tareas bloqueadas…`
  - 00:45 UTC: model=gpt-5.4, tokens=395, duration=18106ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 01:00 UTC: model=gpt-5.4, tokens=481, duration=20471ms, summary_len=176
    > `Para Arturo por Telegram: [desk-review] 3 tareas bloqueadas:…`
  - 01:15 UTC: model=gpt-5.4, tokens=527, duration=18230ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 01:30 UTC: model=gpt-5.4, tokens=443, duration=18254ms, summary_len=174
    > `Para Arturo (Telegram): [desk-review] 3 tareas bloqueadas: M…`
  - 01:45 UTC: model=gpt-5.4, tokens=470, duration=21585ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 02:00 UTC: model=gpt-5.4, tokens=336, duration=16460ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 02:15 UTC: model=gpt-5.4, tokens=608, duration=22540ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 02:30 UTC: model=gpt-5.4, tokens=595, duration=22087ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 02:45 UTC: model=gpt-5.4, tokens=588, duration=15306ms, summary_len=174
    > `Para Arturo (Telegram): [desk-review] 3 tareas bloqueadas: M…`
  - 03:00 UTC: model=gpt-5.4, tokens=453, duration=16704ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 03:15 UTC: model=gpt-5.4, tokens=457, duration=23736ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 03:30 UTC: model=gpt-5.4, tokens=630, duration=21053ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 03:45 UTC: model=gpt-5.4, tokens=509, duration=14465ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 04:00 UTC: model=gpt-5.4, tokens=640, duration=20573ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 04:15 UTC: model=gpt-5.4, tokens=478, duration=23982ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 04:30 UTC: model=gpt-5.4, tokens=544, duration=17466ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 04:45 UTC: model=gpt-5.4, tokens=511, duration=13707ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 05:00 UTC: model=gpt-5.4, tokens=658, duration=19378ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 05:15 UTC: model=gpt-5.4, tokens=609, duration=20018ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 05:30 UTC: model=gpt-5.4, tokens=577, duration=20784ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 05:45 UTC: model=gpt-5.4, tokens=480, duration=22176ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 06:01 UTC: model=gpt-5.4, tokens=566, duration=37838ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 06:15 UTC: model=gpt-5.4, tokens=444, duration=34951ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 06:31 UTC: model=gpt-5.4, tokens=616, duration=26781ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 06:45 UTC: model=gpt-5.4, tokens=590, duration=25217ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`
  - 07:07 UTC: model=gpt-5.4, tokens=775, duration=26069ms, summary_len=150
    > `[desk-review] 3 tareas bloqueadas: Mostrar timeline de etapa…`

---
