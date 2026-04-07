# InvestmentDesk: Arquitectura Inicial

> Agente de research personal de inversiones integrado en Desk.
> Owner: Arturo — Timezone: Europe/Madrid

---

## 1. Alcance

InvestmentDesk es un módulo dentro de Desk que actúa como **analista de research personal**. No ejecuta operaciones ni gestiona portfolios. Su función es:

1. **Recopilar** datos de mercado y noticias de forma automatizada
2. **Estructurar** esa información en briefings accionables
3. **Mantener memoria histórica** de tesis, análisis y señales
4. **Generar consultas bajo demanda** sobre activos, sectores o narrativas
5. **Alertar** cuando se cumplen condiciones predefinidas

**Fuera de alcance** (por diseño):
- Ejecución de órdenes de compra/venta
- Gestión de portfolio real (posiciones, P&L)
- Conexión directa a brokers
- Asesoramiento financiero regulado

---

## 2. Componentes

```
┌──────────────────────────────────────────────────────────────────┐
│                        InvestmentDesk                            │
├──────────────┬──────────────┬──────────────┬─────────────────────┤
│  Ingestion   │   Memory     │  Analysis    │   Delivery          │
│  Layer       │   Store      │  Engine      │   Layer             │
├──────────────┼──────────────┼──────────────┼─────────────────────┤
│ n8n workflow │ briefings    │ Claude       │ Dashboard (Desk UI) │
│ Telegram cmd │ research_    │ prompts      │ Telegram alerts     │
│ API directa │   notes      │ (on-demand)  │ Briefing cards      │
│ Manual       │ watchlists   │              │ Chat queries        │
└──────────────┴──────────────┴──────────────┴─────────────────────┘
```

### 2.1 Ingestion Layer (ya diseñado)

Documentado en `BRIEFING-INGESTION-DESIGN.md`. Recibe datos de fuentes externas y los persiste en `briefings` + `briefing_items`.

### 2.2 Memory Store

Tres capas de memoria financiera:

| Capa | Tabla | Horizonte | Propósito |
|------|-------|-----------|-----------|
| **Briefings** | `briefings` + `briefing_items` | Diario | Snapshot del día: mercados, datos, señales |
| **Research Notes** | `research_notes` | Semanas/meses | Tesis de inversión, análisis profundos, narrativas |
| **Watchlists** | `watchlist_items` (nueva) | Persistente | Activos bajo seguimiento con niveles y alertas |

#### Nueva tabla: `watchlist_items`

```sql
CREATE TABLE IF NOT EXISTS watchlist_items (
  id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  name TEXT NOT NULL,
  asset_type TEXT NOT NULL CHECK (asset_type IN (
    'equity','etf','crypto','commodity','forex','index','bond'
  )),
  thesis TEXT,                         -- por qué está en watchlist
  entry_target REAL,                   -- precio objetivo de entrada
  exit_target REAL,                    -- precio objetivo de salida
  stop_loss REAL,                      -- nivel de stop
  alert_conditions_json TEXT,          -- condiciones de alerta (JSON)
  status TEXT NOT NULL DEFAULT 'watching' CHECK (status IN (
    'watching','triggered','paused','archived'
  )),
  priority TEXT NOT NULL DEFAULT 'media' CHECK (priority IN ('baja','media','alta','critica')),
  tags_json TEXT,
  notes TEXT,
  added_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist_items(symbol);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist_items(status);
```

### 2.3 Analysis Engine

No es un servicio separado — es un conjunto de **prompts estructurados** que se ejecutan a través del bridge existente (Claude Code) o directamente en la conversación de Yume.

Tipos de análisis:

| Tipo | Trigger | Input | Output |
|------|---------|-------|--------|
| **Daily Digest** | Cron (rutina matutina) | Briefings del día + watchlist activa | Resumen priorizado con acciones sugeridas |
| **Asset Deep Dive** | Comando de Arturo | Symbol + research_notes históricas + briefings recientes | Análisis completo del activo |
| **Thesis Review** | Semanal (rutina) | Research notes tipo `thesis` activas | Estado de cada tesis: vigente/invalidada/actualizar |
| **Alert Check** | Con cada briefing nuevo | Briefing items vs watchlist alert_conditions | Notificaciones si se cumplen condiciones |

### 2.4 Delivery Layer

| Canal | Contenido | Frecuencia |
|-------|-----------|------------|
| **Desk Dashboard** | Sección "Daily Intelligence" con cards de briefings | Siempre visible |
| **Telegram** | Alertas de watchlist, resumen matutino | Bajo demanda + alertas |
| **Chat (Yume)** | Respuestas a consultas tipo "¿cómo está X?" | Interactivo |

---

## 3. Flujos de Datos

### 3.1 Flujo Matutino (automático)

```
06:30 CET ─── n8n: daily-market-briefing ───┐
                                              │
              Recolecta datos de APIs         │
              financieras gratuitas           │
                                              ▼
                                    POST /api/briefings
                                              │
                                              ▼
                                    Desk persiste briefing
                                              │
                                              ├── Check watchlist alerts
                                              │   └── IF match → Telegram alert
                                              │
                                              └── Webhook a Yume
                                                  └── Yume: "Briefing listo"
```

### 3.2 Flujo de Consulta (bajo demanda)

```
Arturo (Telegram/Desk): "¿Cómo va AAPL?"
         │
         ▼
    Yume recibe consulta
         │
         ▼
    Query InvestmentDesk:
    ├── SELECT briefing_items WHERE symbol='AAPL' ORDER BY date DESC LIMIT 10
    ├── SELECT research_notes WHERE symbol='AAPL'
    └── SELECT watchlist_items WHERE symbol='AAPL'
         │
         ▼
    Construye contexto → Claude genera respuesta
         │
         ▼
    Respuesta a Arturo con:
    - Último dato de precio (del briefing más reciente)
    - Tesis activa (si existe)
    - Señales recientes
    - Niveles de watchlist
```

### 3.3 Flujo de Research Note (manual)

```
Arturo: "Guarda esto como tesis: creo que semiconductores van a..."
         │
         ▼
    POST /api/research-notes
    {
      category: "thesis",
      symbol: "SOXX",  (opcional)
      title: "Tesis: ciclo semiconductores 2026",
      body: "...",
      tags_json: ["semiconductors","cycle","bullish"]
    }
         │
         ▼
    Persiste en research_notes
    Yume confirma: "Tesis guardada"
```

### 3.4 Flujo de Alerta (automático)

```
Nuevo briefing llega con item: BABA change_pct = -5.2%
         │
         ▼
    Alert Check:
    SELECT * FROM watchlist_items
    WHERE symbol = 'BABA' AND status = 'watching'
         │
         ▼
    Evaluar alert_conditions_json:
    { "change_pct_below": -5.0 }  ← MATCH
         │
         ▼
    Telegram: "⚠ BABA -5.2% — condición de alerta activada.
              Tesis: 'Watchlist por RSI oversold'. Nivel entrada: $85"
```

---

## 4. Memoria Histórica

### 4.1 Política de Retención

| Dato | Retención | Razón |
|------|-----------|-------|
| Briefings | 90 días en tabla, luego archivar | Datos de mercado pierden relevancia rápido |
| Briefing items | Misma que briefing padre | Cascada |
| Research notes | Indefinida | Son análisis propios, valor duradero |
| Watchlist items | Indefinida (archivables) | Referencia histórica |

### 4.2 Archivado

Rutina mensual que:
1. Marca briefings >90 días como `deleted=1`
2. Genera un `research_note` tipo `snapshot` con resumen del mes archivado
3. Los datos siguen en la DB pero no aparecen en queries por defecto

### 4.3 Consulta Histórica

Yume puede consultar la memoria histórica para:
- "¿Cuándo fue la última vez que VIX superó 25?"
- "¿Qué dije sobre NVDA en febrero?"
- "¿Cuáles de mis tesis se han cumplido?"

Estas consultas se resuelven con SQL sobre las tablas existentes + contexto de Claude para interpretar resultados.

---

## 5. Puntos de Consulta del Agente

Interfaces donde Arturo puede interactuar con InvestmentDesk:

### 5.1 Telegram (principal)

Comandos naturales procesados por Yume:

| Intención | Ejemplo | Acción |
|-----------|---------|--------|
| Ver briefing del día | "¿Qué hay hoy en mercados?" | GET /api/briefings/today → resumen |
| Consultar activo | "¿Cómo está BTC?" | Query multi-tabla → análisis |
| Guardar tesis | "Guarda tesis: creo que..." | POST /api/research-notes |
| Añadir a watchlist | "Vigila TSLA, entrada en $180" | POST /api/watchlist |
| Estado watchlist | "¿Cómo van mis watchlist?" | GET /api/watchlist → resumen |
| Análisis profundo | "Dame un deep dive de AAPL" | Query completa + Claude analysis |

### 5.2 Desk UI (Dashboard)

- **Sección "Daily Intelligence"**: Cards de briefings del día
- **Vista Watchlist**: Tabla con activos, niveles, estado
- **Vista Research**: Historial de notas y tesis con filtros
- **Detalle de briefing**: Expandido con items y acciones

### 5.3 API Directa

Para integración con otros sistemas o scripts:

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/briefings` | GET/POST | CRUD briefings (ya diseñado) |
| `/api/briefings/today` | GET | Briefings de hoy (ya diseñado) |
| `/api/briefings/{id}` | GET/PATCH/DELETE | Detalle briefing (ya diseñado) |
| `/api/research-notes` | GET/POST | CRUD research notes |
| `/api/research-notes/{id}` | GET/PATCH/DELETE | Detalle research note |
| `/api/watchlist` | GET/POST | CRUD watchlist |
| `/api/watchlist/{id}` | GET/PATCH/DELETE | Detalle watchlist item |
| `/api/investment/query` | POST | Consulta libre (symbol/tema → análisis) |
| `/api/investment/digest` | GET | Daily digest generado |

---

## 6. Rutinas Automatizadas

Siguiendo el protocolo de rutinas existente (`RUTINAS-PROTOCOL.md`):

### Rutina: `morning-market-brief`

```yaml
scheduler: n8n (cron 06:30 CET)
skill: n/a (workflow determinista, no necesita agente)
delivery: POST /api/briefings + Telegram summary
```

### Rutina: `watchlist-alert-check`

```yaml
scheduler: n8n (trigger: nuevo briefing creado)
skill: n/a (comparación programática de condiciones)
delivery: Telegram si hay matches
```

### Rutina: `weekly-thesis-review`

```yaml
scheduler: openclaw cron (domingos 10:00 CET)
skill: routines/skills/thesis-review/SKILL.md
delivery: Telegram con resumen + actualizar research_notes
```

### Rutina: `monthly-archive`

```yaml
scheduler: openclaw cron (1er día del mes, 03:00 CET)
skill: n/a (script SQL)
delivery: research_note tipo snapshot
```

---

## 7. Integración con el Sistema Existente

### 7.1 Con Desk Tasks

- Un briefing con prioridad `critica` puede generar una task automática en Desk
- Research notes pueden vincularse a proyectos (ej: `proj-inversiones`)
- Alertas de watchlist pueden crear inbox_items para triaje

### 7.2 Con Yume

- Yume es la interfaz conversacional de InvestmentDesk
- No es un agente separado — es una **capability** de Yume
- Yume decide cuándo consultar las tablas de InvestmentDesk basándose en el contexto de la conversación

### 7.3 Con Agentes

No se necesita un agente nuevo. InvestmentDesk se integra como:
- **Tablas en la DB** (ya creadas parcialmente)
- **Endpoints en app.py** (parcialmente implementados)
- **Rutinas en n8n/cron** (por crear)
- **Prompts de análisis** (por diseñar, reutilizan el bridge existente)

---

## 8. Plan de Implementación por Fases

### Fase 1: Fundación (actual)
- [x] Diseño de arquitectura (este documento)
- [x] Tablas briefings + briefing_items en schema
- [x] Tabla research_notes en schema
- [x] Endpoints básicos de briefings en app.py
- [x] Endpoint research-notes en app.py
- [ ] Tabla watchlist_items en schema
- [ ] Endpoints CRUD watchlist en app.py

### Fase 2: Ingestión Automatizada
- [ ] Workflow n8n `daily-market-briefing` con fuentes reales
- [ ] Alert check programático al recibir briefing
- [ ] Token auth para ingestión (`DESK_BRIEFING_TOKEN`)

### Fase 3: Consulta Inteligente
- [ ] Endpoint `/api/investment/query` con contexto multi-tabla
- [ ] Integración de consultas en conversación de Yume
- [ ] Prompts de análisis (daily digest, deep dive, thesis review)

### Fase 4: UI en Desk
- [ ] Sección Daily Intelligence en Dashboard
- [ ] Vista Watchlist
- [ ] Vista Research Notes
- [ ] Detalle expandido de briefings

### Fase 5: Rutinas y Alertas
- [ ] Rutina weekly-thesis-review
- [ ] Rutina monthly-archive
- [ ] Sistema de alertas de watchlist via Telegram

---

## 9. Decisiones de Diseño

| Decisión | Elección | Razón |
|----------|----------|-------|
| ¿Agente separado? | No — capability de Yume | Evita fragmentación, Arturo habla con una sola IA |
| ¿Base de datos separada? | No — misma SQLite de Desk | Simplicidad, las queries cruzan tablas (tasks, briefings, etc.) |
| ¿Servicio backend separado? | No — endpoints en app.py | Un solo proceso, sin overhead de comunicación entre servicios |
| ¿Análisis en tiempo real? | No — batch diario + on-demand | No hay necesidad de streaming para research personal |
| ¿Fuentes de datos pagas? | Empezar con gratuitas | Yahoo Finance, CoinMarketCap free tier. Escalar si hace falta |
| ¿Portfolio tracking? | Fuera de alcance v1 | Complejidad regulatoria y técnica. Primero research, luego portfolio |
