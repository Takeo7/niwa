# Auditoría de Transiciones de Status — Desk

**Fecha:** 2026-03-25
**Alcance:** Todos los archivos del proyecto Desk que realizan `UPDATE` de status en tareas de la DB.

---

## Resumen ejecutivo

| Métrica | Valor |
|---|---|
| Archivos que modifican status en DB | **3** |
| Puntos de transición encontrados | **4** |
| Puntos con `record_task_event` | **2** |
| **Gaps (sin `record_task_event`)** | **2** |

---

## Archivos analizados

### Archivos que SÍ modifican status en la DB

| # | Archivo | Función/Línea | Transición | `record_task_event` | Gap |
|---|---|---|---|---|---|
| 1 | `backend/app.py` | `update_task()` L612 | any → any (via PATCH payload) | **SÍ** (L613) — tipo `'completed'` si `status='hecha'`, `'updated'` en otros casos | — |
| 2 | `backend/app.py` | `create_task()` L622 | (nueva) → `inbox` (default) o status del payload | **NO** | **GAP** |
| 3 | `scripts/desk_close_task.py` | `main()` L41 | any → `hecha` | **SÍ** (L44-53) — tipo `'status_changed'`, incluye `old_status` y source `'desk-deploy-close'` | — |

### Detalle por archivo

#### 1. `backend/app.py` — `update_task()` (línea 577)

- **UPDATE SQL:** línea 612 — `UPDATE tasks SET {sets} WHERE id=?`
- **Transición:** Cualquier campo permitido, incluyendo `status`. Si `status='hecha'`, también setea `completed_at`.
- **Validación Desk:** Si `status='hecha'` y es tarea del proyecto Desk, requiere marcador `desk-deploy:verified` en notes (L597-598).
- **Evento registrado:** `record_task_event(conn, task_id, 'completed' if status_value == 'hecha' else 'updated', event_payload)` (L613).
- **Payload del evento:** `{'changes': {k: v for changed fields}, 'old_values': {k: old_v}}` (L604-610).
- **Observación:** Cuando el status cambia a cualquier valor que NO sea `'hecha'`, el tipo de evento es `'updated'` en vez de `'status_changed'`. Esto dificulta que `pipeline.py` y `timeline.py` detecten transiciones intermedias, ya que ambos filtran por `type='status_changed'`.

#### 2. `backend/app.py` — `create_task()` (línea 617)

- **INSERT SQL:** línea 622 — `INSERT INTO tasks (..., status, ...) VALUES (...)`
- **Transición:** Nueva tarea con `status = payload.get('status', 'inbox')`.
- **Evento registrado:** **NINGUNO** — no hay llamada a `record_task_event`.
- **GAP:** No se registra evento `'created'` al insertar la tarea. Tanto `pipeline.py` (L63) como `timeline.py` (L89-93) esperan un evento tipo `'created'` para inicializar el tracking de duración por stage.

#### 3. `scripts/desk_close_task.py` — `main()` (línea 12)

- **UPDATE SQL:** línea 41 — `UPDATE tasks SET notes=?, status='hecha', completed_at=?, updated_at=? WHERE id=?`
- **Transición:** any → `hecha` (solo tareas de `proj-desk`).
- **Evento registrado:** Inserta directamente en `task_events` (L44-53) con tipo `'status_changed'` y payload `{'changes': {'status': 'hecha', 'old_status': old_status}, 'source': 'desk-deploy-close'}`.
- **Observación:** Este script captura `old_status` (L39) antes del UPDATE. Usa `'status_changed'` como tipo de evento (coherente con lo que esperan pipeline.py y timeline.py). Sin embargo, el campo en el payload es `changes.status` / `changes.old_status`, mientras que `timeline.py` busca `old_status` o `from` y `new_status` o `to` o `status` directamente en el payload raíz — **potencial incompatibilidad de formato**.

#### 4. `scripts/desk_change_flow.sh` — `close_task()` (línea 159)

- **Transición:** Delega a `desk_close_task.py` (L160) — no hace UPDATE directo.
- **Evento:** Se registra vía `desk_close_task.py`.
- **Sin gap adicional.**

---

### Archivos que NO modifican status (solo lectura/análisis)

| Archivo | Rol |
|---|---|
| `backend/pipeline.py` | Lee `task_events` para calcular duración por stage. Espera eventos `'created'`, `'status_changed'`, `'completed'`. |
| `backend/timeline.py` | Lee `task_events` para calcular timeline de cada tarea. Espera eventos `'created'`, `'status_changed'`, `'completed'`. |
| `scripts/sandbox_enforcer.py` | Protege archivos con chmod. No toca status de tareas. |
| `backend/trigger_idle_review.py` | Microservicio HTTP que lanza `idle-project-review.sh` (script externo al workspace Desk). No modifica la DB de Desk directamente. |
| `frontend/app.js` | Llama a `PATCH /api/tasks/:id` con `{status: 'hecha'}` o cualquier status vía drag-and-drop del kanban. No modifica la DB directamente. |
| `frontend/index.html` | UI legacy — misma situación que `app.js`. |

### Archivos referenciados en la tarea pero NO existentes

| Archivo | Nota |
|---|---|
| `task-worker.sh` | **No existe** en el workspace Desk |
| `task-executor.sh` | **No existe** en el workspace Desk |
| `idle-project-review.sh` | **No existe** dentro de Desk (referenciado en `trigger_idle_review.py` como `scripts/routines/idle-project-review.sh` del workspace padre) |
| `task-closer.sh` | **No existe** en el workspace Desk |

---

## Gaps encontrados

### GAP 1: `create_task()` no registra evento `'created'`

- **Archivo:** `backend/app.py`, línea 617-641
- **Impacto:** `pipeline.py` y `timeline.py` no pueden determinar cuándo una tarea entró en su status inicial. El cálculo de duración en el primer stage (normalmente `inbox` o `pendiente`) queda sin punto de inicio.
- **Fix recomendado:** Añadir `record_task_event(conn, task_id, 'created', {'status': status, 'title': title, 'source': 'desk-ui'})` después del INSERT en `create_task()`. **Requiere modificar `backend/app.py` (archivo protegido) — intervención manual necesaria.**

### GAP 2: `update_task()` usa tipo `'updated'` para cambios de status intermedios

- **Archivo:** `backend/app.py`, línea 613
- **Impacto:** Cuando una tarea pasa de `inbox` → `pendiente` → `en_progreso` → `bloqueada` (o cualquier transición que no sea a `'hecha'`), el evento se registra como `'updated'` en vez de `'status_changed'`. Tanto `pipeline.py` (L74) como `timeline.py` (L95) filtran por `type='status_changed'` y no ven estos eventos.
- **Consecuencia:** Las métricas de pipeline y timeline solo capturan la transición final a `'hecha'`, perdiendo todas las intermedias.
- **Fix recomendado:** En `update_task()`, cuando `status` cambia, usar `record_task_event(conn, task_id, 'status_changed', {...})` con el old/new status. **Requiere modificar `backend/app.py` (archivo protegido) — intervención manual necesaria.**

### GAP 3 (menor): Incompatibilidad de formato en payload de `status_changed` — **RESUELTO**

- **`desk_close_task.py`** ahora escribe: `{'status': 'hecha', 'old_status': ..., 'source': 'desk-deploy-close'}` (payload plano).
- **`timeline.py`** lee: `payload.get('old_status')` o `payload.get('from')` y `payload.get('new_status')` o `payload.get('to')` o `payload.get('status')` — busca en el **nivel raíz** del payload.
- **`pipeline.py`** lee: `payload.get('new')` o `payload.get('to')` or `payload.get('status')` — también nivel raíz.
- **Fix aplicado:** Se cambió `desk_close_task.py` para usar payload plano en vez de anidar dentro de `changes`. Ahora `pipeline.py` y `timeline.py` detectan correctamente las transiciones de cierre por deploy verificado.

---

## Mapa de flujo de transiciones

```
                   create_task()
                       │
                       ▼
                    [inbox] ──────────────────────┐
                       │                          │
              update_task(PATCH)                   │
                       │                          │
                       ▼                          │
                 [pendiente] ◄────────────────────┤
                       │                          │
              update_task(PATCH)                   │
                       │                          │
                       ▼                          │
                [en_progreso] ◄───────────────────┤
                       │                          │
              update_task(PATCH)                   │  Todas via update_task()
                       │                          │  con tipo 'updated' (GAP 2)
                       ▼                          │
                 [bloqueada] ◄────────────────────┘
                       │
              update_task(PATCH)
                       │
                       ▼
                   [hecha] ◄──── desk_close_task.py (tipo 'status_changed')
                       │         update_task() (tipo 'completed')
                       │
              update_task(PATCH)
                       │
                       ▼
                 [archivada]
```

---

## Conclusión

El sistema tiene **2 gaps críticos** (ambos en `backend/app.py`, archivo protegido):

1. **Falta evento `'created'`** en `create_task()` — las tareas nacen sin registro en `task_events`, rompiendo el tracking de pipeline y timeline desde el inicio.
2. **Transiciones intermedias usan tipo `'updated'` en vez de `'status_changed'`** — pipeline.py y timeline.py ignoran estos eventos, perdiendo visibilidad de todo el flujo excepto la transición final a `'hecha'`.
3. ~~**Formato de payload inconsistente**~~ — **RESUELTO**: `desk_close_task.py` ahora usa payload plano compatible con `pipeline.py` y `timeline.py`.

Los gaps 1 y 2 requieren modificar `backend/app.py` (archivo protegido) — **requieren intervención manual**.
