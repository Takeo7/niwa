# InvestmentDesk: Diseño de Ingestión de Briefings Diarios

## Resumen

Sistema para recibir, procesar y almacenar briefings diarios automatizados dentro de Desk. Los briefings son resúmenes estructurados de mercado, noticias y análisis que llegan de fuentes externas y se presentan como inteligencia accionable.

---

## 1. Modelo de Datos

### Nueva tabla: `briefings`

```sql
CREATE TABLE IF NOT EXISTS briefings (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,                -- fecha del briefing (YYYY-MM-DD)
  source TEXT NOT NULL,              -- origen: 'n8n', 'telegram', 'api', 'manual'
  category TEXT NOT NULL CHECK (category IN (
    'market_overview',               -- resumen general de mercados
    'macro',                         -- datos macroeconómicos
    'earnings',                      -- resultados empresariales
    'sector',                        -- análisis sectorial
    'watchlist',                     -- seguimiento de posiciones/watchlist
    'risk',                          -- alertas de riesgo
    'custom'                         -- personalizado
  )),
  title TEXT NOT NULL,
  body TEXT NOT NULL,                -- contenido markdown del briefing
  summary TEXT,                      -- resumen de 1-2 líneas (generado por AI)
  metadata_json TEXT,                -- datos estructurados adicionales (JSON)
  sentiment TEXT CHECK (sentiment IN ('bullish','bearish','neutral','mixed')),
  priority TEXT NOT NULL DEFAULT 'media' CHECK (priority IN ('baja','media','alta','critica')),
  read INTEGER NOT NULL DEFAULT 0,   -- leído por el usuario
  pinned INTEGER NOT NULL DEFAULT 0, -- fijado para referencia
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefings_date ON briefings(date);
CREATE INDEX IF NOT EXISTS idx_briefings_category ON briefings(category);
CREATE INDEX IF NOT EXISTS idx_briefings_read ON briefings(read);
```

### Nueva tabla: `briefing_items`

Elementos individuales dentro de un briefing (tickers, datos, señales).

```sql
CREATE TABLE IF NOT EXISTS briefing_items (
  id TEXT PRIMARY KEY,
  briefing_id TEXT NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('ticker','metric','signal','news','action')),
  symbol TEXT,                       -- ticker symbol si aplica (AAPL, BTC, etc.)
  label TEXT NOT NULL,               -- nombre/descripción corta
  value TEXT,                        -- valor numérico o texto
  change_pct REAL,                   -- cambio porcentual si aplica
  sentiment TEXT CHECK (sentiment IN ('bullish','bearish','neutral')),
  notes TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefing_items_briefing ON briefing_items(briefing_id);
CREATE INDEX IF NOT EXISTS idx_briefing_items_symbol ON briefing_items(symbol);
```

---

## 2. Flujo de Ingestión

```
┌─────────────────────────────────────────────────────┐
│                   FUENTES                           │
├──────────┬──────────┬───────────┬───────────────────┤
│  n8n     │ Telegram │  API      │  Manual (Desk UI) │
│ workflow │  bot     │  directa  │                   │
└────┬─────┴────┬─────┴─────┬─────┴────────┬──────────┘
     │          │           │              │
     ▼          ▼           ▼              ▼
┌─────────────────────────────────────────────────────┐
│            POST /api/briefings                      │
│  (endpoint unificado de ingestión)                  │
├─────────────────────────────────────────────────────┤
│  1. Validación de payload                           │
│  2. Scan de seguridad (prompt injection)            │
│  3. Parsing de contenido                            │
│  4. Extracción de items (tickers, métricas)         │
│  5. Generación de summary (opcional, via Claude)    │
│  6. INSERT en briefings + briefing_items            │
│  7. Webhook a Yume (notificación)                   │
└─────────────────────────────────────────────────────┘
```

### 2.1 Fuente principal: n8n workflow

El workflow de n8n es la fuente principal de briefings automatizados:

1. **Trigger**: Cron diario (ej. 6:30 AM CET)
2. **Recolección**: n8n agrega datos de APIs financieras (Yahoo Finance, Alpha Vantage, etc.)
3. **Procesamiento**: Formatea los datos en estructura JSON
4. **Entrega**: POST al endpoint `/api/briefings` con auth header

### 2.2 Fuente secundaria: Telegram

Mensajes con formato especial enviados via Telegram:
- Prefijo: `/briefing` o comando dedicado
- Se rutea via el bridge existente hacia el endpoint de briefings

### 2.3 API directa

Cualquier sistema autenticado puede enviar briefings via POST.

---

## 3. API Endpoints

### `POST /api/briefings` — Crear briefing

```json
// Request
{
  "date": "2026-03-22",              // opcional, default: hoy
  "source": "n8n",
  "category": "market_overview",
  "title": "Morning Market Brief — 22 Mar 2026",
  "body": "## S&P 500\n+0.4% ...",   // markdown
  "sentiment": "bullish",
  "priority": "media",
  "items": [                          // opcional
    {
      "kind": "ticker",
      "symbol": "SPY",
      "label": "S&P 500 ETF",
      "value": "542.30",
      "change_pct": 0.4,
      "sentiment": "bullish"
    },
    {
      "kind": "metric",
      "label": "VIX",
      "value": "14.2",
      "change_pct": -3.1,
      "sentiment": "neutral"
    },
    {
      "kind": "signal",
      "label": "RSI oversold alert",
      "symbol": "BABA",
      "notes": "RSI(14) = 28.5, near 52w low"
    }
  ]
}

// Response: 201
{
  "id": "brf_xxx",
  "date": "2026-03-22",
  "title": "Morning Market Brief — 22 Mar 2026",
  "category": "market_overview",
  "items_count": 3,
  "created_at": "2026-03-22T06:30:00Z"
}
```

### `GET /api/briefings` — Listar briefings

Query params:
- `date` — filtrar por fecha (YYYY-MM-DD)
- `category` — filtrar por categoría
- `unread` — solo no leídos (`1`)
- `pinned` — solo fijados (`1`)
- `limit` — paginación (default: 20)
- `offset` — paginación

### `GET /api/briefings/{id}` — Detalle de briefing

Retorna el briefing completo con todos sus items.

### `PATCH /api/briefings/{id}` — Actualizar briefing

Campos actualizables: `read`, `pinned`, `priority`, `notes`.

### `DELETE /api/briefings/{id}` — Eliminar briefing

Soft delete (campo `deleted` o hard delete, a decidir).

### `GET /api/briefings/today` — Briefing del día

Shortcut que retorna todos los briefings de hoy, agrupados por categoría.

---

## 4. Integración con n8n

### Workflow sugerido: `daily-market-briefing`

```
[Cron 6:30 CET]
  → [HTTP: fetch market data APIs]
  → [Code: parse & structure]
  → [HTTP: POST desk.yumewagener.com/api/briefings]
  → [IF error → Telegram notify Yume]
```

**Auth**: Usa el mismo mecanismo de session token o un header dedicado:
```
Authorization: Bearer <DESK_BRIEFING_TOKEN>
```

Se puede agregar un `DESK_BRIEFING_TOKEN` al `.env` para autenticar ingestiones automatizadas sin necesidad de sesión de usuario.

---

## 5. UI en Desk

### Nueva vista: "Briefings" (o integrada en Dashboard)

**Opción recomendada**: Sección dedicada en el Dashboard, no vista separada.

```
┌──────────────────────────────────────────────┐
│  📊 Daily Intelligence                       │
├──────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────┐ │
│  │ Morning Market Brief — 22 Mar 2026     │ │
│  │ ▲ Bullish · 3 tickers · 2 signals      │ │
│  │ S&P +0.4% | VIX 14.2 | BTC $87.4k     │ │
│  └─────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────┐ │
│  │ Earnings Watch — Q1 2026               │ │
│  │ ◆ Neutral · 5 companies reporting      │ │
│  └─────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────┐ │
│  │ Risk Alert: China tariff exposure       │ │
│  │ ▼ Bearish · alta prioridad             │ │
│  └─────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

- Cards con glassmorphism siguiendo el design system existente
- Indicador de sentimiento con color (verde/rojo/gris)
- Click expande el briefing completo con items
- Botones: marcar leído, pin, archivar

---

## 6. Seguridad

1. **Auth**: Token dedicado (`DESK_BRIEFING_TOKEN`) para ingestiones automatizadas
2. **Scan**: Todo briefing pasa por `scan_task_for_injection()` antes de persistir
3. **Rate limit**: Max 50 briefings/hora por source
4. **Validación**: Schema estricto, sanitización de markdown
5. **No URLs externas**: Los datos llegan al endpoint, Desk nunca sale a buscarlos

---

## 7. Plan de Implementación

### Fase 1: Backend (prioritaria)
1. Agregar tablas `briefings` + `briefing_items` al schema.sql
2. Implementar funciones CRUD en app.py
3. Endpoint `POST /api/briefings` con validación y scan de seguridad
4. Endpoints GET/PATCH/DELETE
5. Token auth para ingestión automatizada

### Fase 2: n8n Workflow
1. Crear workflow `daily-market-briefing` en n8n
2. Configurar fuentes de datos (APIs financieras)
3. Mapear datos al schema de briefings
4. Probar entrega al endpoint

### Fase 3: UI
1. Sección "Daily Intelligence" en Dashboard
2. Cards de briefing con expandido
3. Vista detalle de briefing items
4. Acciones: read, pin, archive

### Fase 4: Inteligencia
1. Summary automático via Claude al ingerir
2. Correlación entre briefings y tasks/proyectos existentes
3. Alertas personalizadas basadas en watchlist del usuario

---

## 8. Formato de Payload desde n8n (ejemplo completo)

```json
{
  "date": "2026-03-22",
  "source": "n8n",
  "category": "market_overview",
  "title": "Morning Market Brief — 22 Mar 2026",
  "body": "## Indices\n- S&P 500: 5,423 (+0.4%)\n- Nasdaq: 17,102 (+0.6%)\n- Euro Stoxx 50: 4,891 (-0.1%)\n\n## Commodities\n- Gold: $2,185 (+0.2%)\n- Oil (WTI): $68.40 (-1.3%)\n\n## Crypto\n- BTC: $87,400 (+2.1%)\n- ETH: $3,420 (+1.8%)\n\n## Key Events Today\n- Fed speaker Williams at 14:00 CET\n- EU PMI data release",
  "sentiment": "bullish",
  "priority": "media",
  "metadata_json": {
    "workflow_id": "daily-market-brief-v1",
    "data_sources": ["yahoo_finance", "coinmarketcap", "economic_calendar"],
    "generated_at": "2026-03-22T06:25:00Z"
  },
  "items": [
    {"kind": "ticker", "symbol": "SPY", "label": "S&P 500", "value": "5423", "change_pct": 0.4, "sentiment": "bullish"},
    {"kind": "ticker", "symbol": "QQQ", "label": "Nasdaq 100", "value": "17102", "change_pct": 0.6, "sentiment": "bullish"},
    {"kind": "ticker", "symbol": "BTC-USD", "label": "Bitcoin", "value": "87400", "change_pct": 2.1, "sentiment": "bullish"},
    {"kind": "metric", "symbol": "VIX", "label": "Volatility Index", "value": "14.2", "change_pct": -3.1, "sentiment": "neutral"},
    {"kind": "metric", "label": "Gold", "value": "2185", "change_pct": 0.2, "sentiment": "neutral"},
    {"kind": "signal", "label": "Fed speaker today", "notes": "Williams at 14:00 CET — watch for rate guidance"}
  ]
}
```
