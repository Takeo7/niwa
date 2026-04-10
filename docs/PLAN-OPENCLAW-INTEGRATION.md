# Plan: Integración OpenClaw ↔ Niwa

## Visión

OpenClaw actúa como **orquestador principal** (conversacional, multi-canal: Telegram, WhatsApp, Slack, terminal). Niwa actúa como **backend de gestión** (tareas, proyectos, memoria, hosting, ejecución). OpenClaw accede a Niwa a través de su MCP Gateway existente.

```
┌─────────────┐      MCP (SSE/HTTP)       ┌──────────────────┐
│  OpenClaw   │ ◄─────────────────────────► │  Niwa MCP Gateway │
│  (Gateway)  │                             │  (port 28812)     │
│             │   tools: task_create,       │                    │
│  Channels:  │   project_list,            │  ┌──────────────┐  │
│  - Telegram │   memory_store,            │  │ tasks-mcp    │  │
│  - WhatsApp │   web_search,              │  │ notes-mcp    │  │
│  - Slack    │   generate_image,          │  │ platform-mcp │  │
│  - Terminal │   deploy_web, ...          │  │ filesystem   │  │
│             │                             │  └──────────────┘  │
└─────────────┘                             └──────────────────┘
       │                                            │
       │                                            │
       ▼                                            ▼
  Multi-modelo                              SQLite + filesystem
  (Claude, GPT, Gemini)                     (tareas, proyectos, memoria)
```

## ¿Por qué tiene sentido?

1. **OpenClaw ya es multi-canal** — Telegram, WhatsApp, Discord, Slack, terminal. Niwa solo tiene web UI + chat Haiku. Con OpenClaw, todo lo que Niwa sabe hacer (gestión de tareas, memoria, web search, hosting) se expone a cualquier canal.

2. **OpenClaw ya es multi-modelo** — routing inteligente entre Claude, GPT-5.4, Gemini, Ollama. Niwa tiene su sistema 3-tier pero es más rígido. OpenClaw puede elegir el mejor modelo por tarea.

3. **MCP es el puente natural** — Niwa ya tiene un MCP Gateway (docker-mcp) con 20+ tools. OpenClaw soporta MCP servers externos via SSE o streamable-http. Solo hay que conectarlos.

4. **Separación de responsabilidades** — OpenClaw maneja la conversación y el routing. Niwa maneja los datos y la ejecución. Cada uno hace lo que mejor sabe hacer.

## Arquitectura de integración

### Opción A: OpenClaw como MCP client de Niwa (Recomendada)

OpenClaw se conecta al Niwa MCP Gateway como un servidor MCP remoto:

```json
// ~/.openclaw/openclaw.json
{
  "mcp": {
    "servers": {
      "niwa": {
        "url": "http://72.62.2.139:28812/sse",
        "transport": "sse",
        "headers": {
          "Authorization": "Bearer <MCP_GATEWAY_AUTH_TOKEN>"
        },
        "connectionTimeoutMs": 15000
      }
    }
  }
}
```

**Ventajas:**
- Zero cambios en Niwa — el MCP Gateway ya expone todas las tools
- OpenClaw auto-descubre las 20+ tools de Niwa
- Funciona con cualquier canal de OpenClaw
- El agente de OpenClaw puede combinar tools de Niwa con sus propias capacidades

**Limitaciones:**
- El MCP Gateway actual usa transport SSE, hay que verificar compatibilidad
- Auth: necesita el token de MCP Gateway
- Latencia: cada tool call es HTTP round-trip al VPS

### Opción B: OpenClaw Gateway + Niwa como skill

Crear un "skill" de OpenClaw que envuelve las interacciones con Niwa:

```yaml
# ~/.openclaw/skills/niwa-integration.md
---
name: niwa
description: Gestión de tareas, proyectos y memoria personal via Niwa
---
# Niwa Integration

Tienes acceso a un sistema de gestión personal llamado Niwa con estas capacidades:
- Crear y gestionar tareas (task_create, task_update, task_list)
- Gestionar proyectos (project_create, project_list, project_context)  
- Memoria persistente (memory_store, memory_search, memory_list)
- Búsqueda web (web_search)
- Generar imágenes (generate_image)
- Deploy de webs (deploy_web, undeploy_web)

Usa las tools MCP de "niwa" para interactuar con el sistema.
```

### Opción C: Bidireccional — OpenClaw también como MCP server para Niwa

OpenClaw puede funcionar como MCP server (`openclaw mcp serve`). Esto permitiría que el executor de Niwa delegue tareas a OpenClaw cuando necesite capacidades que no tiene (multi-modelo, channels, etc.).

```
Niwa executor → OpenClaw MCP server → Canales de OpenClaw
```

Esto es más complejo y lo dejaría para una fase posterior.

## Plan de implementación

### Fase 1: Conexión básica (1-2 horas)

1. **Verificar que el MCP Gateway de Niwa es accesible externamente**
   - El gateway corre en port 28812 (SSE) y 28810 (streaming)
   - Verificar que acepta conexiones externas (no solo localhost)
   - Verificar que el auth token funciona desde fuera del Docker network

2. **Configurar OpenClaw para conectarse al MCP Gateway de Niwa**
   ```bash
   openclaw mcp set niwa '{"url":"http://72.62.2.139:28812/sse","headers":{"Authorization":"Bearer <token>"}}'
   openclaw gateway restart
   ```

3. **Verificar que OpenClaw ve las tools de Niwa**
   ```bash
   openclaw mcp list
   # Debería mostrar: task_list, task_create, project_list, etc.
   ```

4. **Test básico**: Pedirle a OpenClaw via terminal que cree una tarea en Niwa

### Fase 2: Skill + contexto (2-3 horas)

1. **Crear un skill de OpenClaw para Niwa** que enseñe al agente:
   - Cómo están organizados los datos (proyectos → tareas → subtareas)
   - Convenciones (statuses, prioridades, áreas)
   - Cuándo usar cada tool
   - Cómo formatear respuestas

2. **Configurar bindings** para que mensajes de ciertos canales se routeen al agente con el skill de Niwa

3. **Morning brief via OpenClaw**: En vez del cron de Niwa que envía por Telegram, OpenClaw genera el brief usando las tools de Niwa y lo envía por el canal que toque

### Fase 3: Multi-canal (3-4 horas)

1. **Telegram via OpenClaw**: Conectar el bot de Telegram a OpenClaw en vez de directamente a Niwa
   - OpenClaw recibe mensajes de Telegram
   - Usa tools de Niwa para crear tareas, buscar memoria, etc.
   - Responde por Telegram

2. **WhatsApp**: Si tienes cuenta business, añadir WhatsApp como canal adicional

3. **Slack/Discord**: Opcional, mismo patrón

### Fase 4: Bidireccional (futuro)

1. **OpenClaw como MCP server para Niwa**: El executor de Niwa puede delegar a OpenClaw
2. **Workflow compuesto**: Usuario pide algo en chat Niwa → Niwa delega a OpenClaw → OpenClaw usa múltiples modelos y tools → resultado vuelve a Niwa

## Cambios necesarios en Niwa

### Mínimos (Fase 1)
- Verificar que el MCP Gateway acepta conexiones externas con auth
- Documentar el token y la URL del gateway

### Opcionales (mejoras)
- Añadir un servicio "OpenClaw" al SERVICES_REGISTRY para configurar la conexión desde la UI
- Endpoint `/api/services/openclaw/status` que verifica si OpenClaw está conectado
- Webhook de OpenClaw → Niwa para notificaciones bidireccionales

## Consideraciones

### Seguridad
- El MCP Gateway token es la barrera de auth — trátalo como una API key
- Considerar rate limiting en el gateway
- El gateway actual expone tools que pueden crear/modificar datos — asegurarse de que solo OpenClaw autenticado pueda llamarlas

### Rendimiento  
- Cada tool call es HTTP — añade ~50-100ms de latencia
- Para operaciones batch (listar 100 tareas), puede ser lento
- Considerar caching en OpenClaw para datos frecuentes

### Deduplicación
- Si OpenClaw tiene su propia memoria y Niwa también, ¿dónde se guarda qué?
- Propuesta: Niwa es el "source of truth" para tareas y proyectos. OpenClaw puede tener memoria conversacional propia para contexto de chat.

### Executor de Niwa vs OpenClaw
- Con OpenClaw como orquestador, ¿sigue siendo necesario el executor de Niwa?
- Sí, para tareas que se crean desde la web UI de Niwa o que se programan via routines
- OpenClaw complementa, no reemplaza
