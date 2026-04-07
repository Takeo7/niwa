# Auditoría de Delivery Telegram en Crons

**Periodo analizado:** 2026-03-17 a 2026-03-24 (7 días)
**Solicitado por:** Arturo (via Desk)
**Fecha del informe:** 2026-03-24

---

## Resumen ejecutivo

| Cron Job | Runs | Delivered | Not-delivered | Errors | Tasa entrega |
|---|---|---|---|---|---|
| idle-project-review | 28 | 11 (39%) | 17 (61%) | 0 | 39% |
| morning-brief-arturo | 4 | 3 (75%) | 1 (25%) | 0 | 75% |
| daily-improvement-arturo | 4 | 3 (75%) | 1 (25%) | 0 | 75% |
| daily-evening-brief | 1 | 1 (100%) | 0 | 0 | 100% |
| desk-yume-15min-review | 233 | 46 (20%) | 142 (61%) | 45 (19%) | 20% |
| desk-yume-5min-review | 132 | 54 (41%) | 72 (55%) | 9 (7%) | 41% |

---

## Patrones de fallo identificados

### Patrón 1: Agente genera output pero gateway no extrae mensaje (CAUSA PRINCIPAL)

**Afecta a:** `idle-project-review` (16 de 17 no-delivered)

El agente genera tokens (251-1113 output_tokens) pero el campo `summary` queda vacío (`null`). El gateway marca `delivered=false, deliveryStatus=not-delivered` porque no hay mensaje que enviar.

**Causa raíz:** El agente ejecuta el script, recibe `action=skip` (hay tareas abiertas en Desk), y genera output interno de razonamiento pero no produce un mensaje de Telegram. El prompt dice "Si action=skip: no envíes nada", así que el agente obedece correctamente. **Esto es comportamiento esperado**, no un bug.

Sin embargo, hay **1 caso genuinamente sospechoso**:
- `2026-03-24 10:06 UTC`: summary="Para Arturo por Telegram: [idle-review] 5 tareas nuevas en Desk..." pero `delivered=false`. El agente generó el mensaje correcto (862 tokens, 337s de ejecución) pero el gateway no lo entregó. Posible causa: el agente escribió el mensaje en el `summary` en vez de enviarlo al canal de Telegram, o timeout del gateway tras 337s de ejecución.

### Patrón 2: Gemini produce output vacío / no entregable (CONFIRMADO)

**Afecta a:** `morning-brief-arturo`, `daily-improvement-arturo` (1 fallo cada uno)

Ambos fallos ocurrieron el **2026-03-22 07:00 UTC** con `gemini-2.5-flash` (provider: google).

- morning-brief: 221 output_tokens, sin summary → no-delivered
- daily-improvement: 744 output_tokens, sin summary → no-delivered

**Causa raíz:** Gemini genera tokens pero no en el formato que el gateway espera para extraer un mensaje de Telegram. El modelo produce razonamiento interno o respuestas parciales que no se parsean como un mensaje entregable. Los runs siguientes con `gpt-5.4` entregaron correctamente.

### Patrón 3: Rate limiting de API (CONFIRMADO)

**Afecta a:** `desk-yume-15min-review` (45 errores = 100% de los errores)

Todos los errores son: `"All models failed: rate_limit"` — tanto OpenAI como Google fallan simultáneamente.

- Concentrados en 2 días: 2026-03-21 (19 errores) y 2026-03-22 (26 errores)
- Distribuidos por todo el día (no correlacionan con horas pico)
- Afectan a ambos providers a la vez

**Causa raíz:** La frecuencia de 15 min (96 runs/día) satura las cuotas de API. El 2026-03-22 fue especialmente malo con 26 errores (27% del día). A partir del 2026-03-23 los errores desaparecieron, lo que sugiere que se ajustaron cuotas o se redujo carga concurrente.

### Patrón 4: desk-yume-15min-review "muted" por diseño

**Afecta a:** 139 de 142 not-delivered (98%)

La rutina está configurada con `bestEffort: true` y la skill instruye al agente a solo reportar si hay bloqueos reales. La mayoría de runs detectan que no hay nada que reportar → `action=skip` → no delivery. **Esto es comportamiento correcto y esperado.**

Solo 3 runs son sospechosos (tenían summary pero no entregaron):
- 2x `HEARTBEAT_OK` (gemini) — el agente respondió con un heartbeat en vez de un mensaje Telegram
- 1x `"Leo el skill y ejecuto el review"` (gpt-5.4) — el agente narró su proceso en vez de producir un mensaje

---

## Diagnóstico por causa raíz

| Causa | Runs afectados | Severidad | Acción recomendada |
|---|---|---|---|
| Agent skip (no hay qué reportar) | ~155 | Info (esperado) | Ninguna — comportamiento correcto |
| Rate limiting de API | 45 | Alta | Reducir frecuencia de desk-review a 30min, o implementar backoff |
| Gemini no produce formato entregable | 3-4 | Media | Fijar provider a gpt-5.4 para jobs con delivery, o mejorar parsing |
| Gateway no extrae mensaje de output largo | 1 | Baja | Investigar timeout del gateway en runs > 300s |
| Agente narra proceso en vez de enviar | 2 | Baja | Reforzar prompt: "Output SOLO el mensaje, sin narración" |

---

## Recomendaciones

1. **Rate limiting (impacto alto):** Considerar reducir `desk-yume-15min-review` a cada 30 min, o implementar exponential backoff en el scheduler cuando ambos providers fallan.

2. **Gemini como fallback (impacto medio):** Cuando `gemini-2.5-flash` es el provider, no respeta el formato de output esperado para delivery. Opciones:
   - Fijar `gpt-5.4` como provider obligatorio para jobs con delivery a Telegram
   - Añadir post-procesado en el gateway que intente extraer mensaje de outputs no estándar

3. **Runs largos (impacto bajo):** El run de idle-project-review que tardó 337s generó el mensaje pero no se entregó. Verificar si el gateway tiene un timeout que corta la entrega en runs que exceden cierto umbral.

4. **No se requiere acción** para la mayoría de not-delivered: son skips legítimos por diseño del sistema.

---

## Datos crudos de referencia

- JSONL logs: `/home/yume/.openclaw/cron/runs/*.jsonl`
- Job config: `/home/yume/.openclaw/cron/jobs.json`
- Routines: `/home/yume/.openclaw/workspace/routines/*/routine.json`
- Delivery queue: `/home/yume/.openclaw/delivery-queue/` (vacía — no hay items encolados pendientes)
