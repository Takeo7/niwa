# Cambios requeridos en archivos protegidos: `status_changed` en `task_events`

**Fecha:** 2026-03-25
**Tarea padre:** 59c7175a-3963-40a7-9a03-1a78bfd0cc27
**Subtarea:** 3/3 — Registrar `status_changed` en `task_events` para TODAS las transiciones
**Estado:** Pendiente de intervención manual

---

## Resumen

Los consumidores de eventos (`pipeline.py`, `timeline.py`) filtran por `type IN ('status_changed', 'completed', 'created')`, pero muchas transiciones de estado se registran como `'updated'` o no se registran en absoluto. Este documento detalla los cambios exactos necesarios en los 3 archivos protegidos.

### Formato de payload esperado por los consumidores

```python
# pipeline.py lee: payload.get('new') or payload.get('to') or payload.get('status')
# timeline.py lee: payload.get('old_status') or payload.get('from')
#                   payload.get('new_status') or payload.get('to') or payload.get('status')
```

Payload estándar recomendado:
```python
{'old_status': '<anterior>', 'status': '<nuevo>', 'source': '<origen>'}
```

---

## ARCHIVO 1: `backend/app.py`

### Cambio 1A: `update_task()` — Usar `status_changed` en transiciones de estado

**Ubicación:** línea 613
**Problema:** Cuando hay cambio de status, se registra `'completed'` (solo si `hecha`) o `'updated'` (para todo lo demás). Las transiciones intermedias (inbox→pendiente, pendiente→en_progreso, etc.) son invisibles para pipeline/timeline.

**Código actual (línea 613):**
```python
        record_task_event(conn, task_id, 'completed' if status_value == 'hecha' else 'updated', event_payload)
```

**Reemplazar por (línea 613):**
```python
        if status_value:
            old_status = current_task.get('status', '')
            event_type = 'completed' if status_value == 'hecha' else 'status_changed'
            event_payload['old_status'] = old_status
            event_payload['status'] = status_value
            record_task_event(conn, task_id, event_type, event_payload)
        else:
            record_task_event(conn, task_id, 'updated', event_payload)
```

**Contexto circundante para ubicar:**
```python
    # línea 611:
    with db_conn() as conn:
        conn.execute(f'UPDATE tasks SET {", ".join(sets)} WHERE id=?', params)
        # >>> CAMBIAR LÍNEA 613 <<<
        conn.commit()
```

---

### Cambio 1B: `create_task()` — Registrar evento `created`

**Ubicación:** entre líneas 639 y 640 (después del INSERT, antes del `conn.commit()`)
**Problema:** No se registra ningún evento al crear una tarea. Pipeline y timeline esperan un evento `'created'` para determinar el timestamp y status inicial.

**Código actual (líneas 639-641):**
```python
        )
        conn.commit()
    return task_id
```

**Reemplazar por:**
```python
        )
        record_task_event(conn, task_id, 'created', {
            'status': payload.get('status', 'inbox'),
            'source': 'desk-ui',
            'title': payload.get('title', 'Nueva tarea'),
        })
        conn.commit()
    return task_id
```

---

## ARCHIVO 2: `scripts/task-worker.sh` (Python embebido)

> Nota: task-worker.sh está en `/home/yume/.openclaw/workspace/scripts/task-worker.sh`.
> Contiene Python embebido entre `<< 'PYEOF'` y `PYEOF`. Los números de línea se refieren al archivo completo.

### Cambio 2A: Transient retry → pendiente (SIN evento)

**Ubicación:** línea 452
**Problema:** Cambio de `en_progreso` a `pendiente` sin `record_event`.

**Código actual (línea 452):**
```python
                conn.execute("UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=? WHERE id=?", (now_iso(), TASK_ID))
                conn.commit()
```

**Reemplazar por:**
```python
                conn.execute("UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=? WHERE id=?", (now_iso(), TASK_ID))
                record_event(conn, TASK_ID, 'status_changed', {'old_status': 'en_progreso', 'status': 'pendiente', 'source': 'task-worker', 'reason': 'transient_retry'})
                conn.commit()
```

---

### Cambio 2B: Transient exhausted → bloqueada (SIN evento)

**Ubicación:** línea 460
**Problema:** Cambio de `en_progreso` a `bloqueada` sin `record_event`.

**Código actual (línea 460):**
```python
                    conn.execute("UPDATE tasks SET status='bloqueada', updated_at=? WHERE id=?", (now_iso(), TASK_ID))
                    conn.commit()
```

**Reemplazar por:**
```python
                    record_event(conn, TASK_ID, 'status_changed', {'old_status': 'en_progreso', 'status': 'bloqueada', 'source': 'task-worker', 'reason': 'transient_exhausted'})
                    conn.execute("UPDATE tasks SET status='bloqueada', updated_at=? WHERE id=?", (now_iso(), TASK_ID))
                    conn.commit()
```

---

### Cambio 2C: Exec error → bloqueada (SIN evento)

**Ubicación:** línea 468
**Problema:** Cambio de `en_progreso` a `bloqueada` sin `record_event`.

**Código actual (línea 468):**
```python
                conn.execute("UPDATE tasks SET status='bloqueada', updated_at=? WHERE id=?", (now_iso(), TASK_ID))
                conn.commit()
```

**Reemplazar por:**
```python
                record_event(conn, TASK_ID, 'status_changed', {'old_status': 'en_progreso', 'status': 'bloqueada', 'source': 'task-worker', 'reason': 'exec_error'})
                conn.execute("UPDATE tasks SET status='bloqueada', updated_at=? WHERE id=?", (now_iso(), TASK_ID))
                conn.commit()
```

---

### Cambio 2D: Health check → bloqueada (SIN evento)

**Ubicación:** línea 490
**Problema:** Cambio de `en_progreso` a `bloqueada` sin `record_event`.

**Código actual (línea 490):**
```python
        conn.execute("UPDATE tasks SET status='bloqueada', updated_at=? WHERE id=?", (now_iso(), TASK_ID))
        conn.commit()
```

**Reemplazar por:**
```python
        record_event(conn, TASK_ID, 'status_changed', {'old_status': 'en_progreso', 'status': 'bloqueada', 'source': 'task-worker', 'reason': 'health_check_failed'})
        conn.execute("UPDATE tasks SET status='bloqueada', updated_at=? WHERE id=?", (now_iso(), TASK_ID))
        conn.commit()
```

---

### Cambio 2E: Triage split → hecha (SIN evento)

**Ubicación:** línea 379
**Problema:** Tarea original se marca como `hecha` tras dividirse en subtareas, sin evento.

**Código actual (línea 379):**
```python
                conn.execute("UPDATE tasks SET status='hecha', completed_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), TASK_ID))
                conn.commit()
```

**Reemplazar por:**
```python
                record_event(conn, TASK_ID, 'status_changed', {'old_status': 'en_progreso', 'status': 'hecha', 'source': 'task-worker', 'reason': 'triage_split'})
                conn.execute("UPDATE tasks SET status='hecha', completed_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), TASK_ID))
                conn.commit()
```

---

### Cambio 2F: Review approved → hecha (SIN evento)

**Ubicación:** línea 572
**Problema:** Cambio de `en_progreso` a `hecha` sin `record_event`.

**Código actual (línea 572):**
```python
        conn.execute("UPDATE tasks SET status='hecha', completed_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), TASK_ID))
        conn.commit()
```

**Reemplazar por:**
```python
        record_event(conn, TASK_ID, 'status_changed', {'old_status': 'en_progreso', 'status': 'hecha', 'source': 'task-worker', 'reason': 'review_approved'})
        conn.execute("UPDATE tasks SET status='hecha', completed_at=?, updated_at=? WHERE id=?", (now_iso(), now_iso(), TASK_ID))
        conn.commit()
```

---

### Cambio 2G: Review failed → bloqueada (SIN evento)

**Ubicación:** línea 589
**Problema:** Cambio de `en_progreso` a `bloqueada` sin `record_event`.

**Código actual (línea 589):**
```python
            conn.execute("UPDATE tasks SET status='bloqueada', updated_at=? WHERE id=?", (now_iso(), TASK_ID))
            conn.commit()
```

**Reemplazar por:**
```python
            record_event(conn, TASK_ID, 'status_changed', {'old_status': 'en_progreso', 'status': 'bloqueada', 'source': 'task-worker', 'reason': 'review_failed'})
            conn.execute("UPDATE tasks SET status='bloqueada', updated_at=? WHERE id=?", (now_iso(), TASK_ID))
            conn.commit()
```

---

### Cambio 2H: Crash recovery → pendiente (SIN evento)

**Ubicación:** líneas 600-607
**Problema:** En el except final, la tarea vuelve a `pendiente` sin evento.

**Código actual (líneas 600-607):**
```python
        rconn = sqlite3.connect(DB)
        rconn.execute(
            "UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=?, "
            "notes=COALESCE(notes,'')||? WHERE id=?",
            (now_iso(), f"\n[{now_iso()}] [task-worker] Crash recuperado: {str(e)[:200]}. Devuelta a pendiente.", TASK_ID),
        )
        rconn.commit()
        rconn.close()
```

**Reemplazar por:**
```python
        rconn = sqlite3.connect(DB)
        import uuid as _uuid_crash
        rconn.execute(
            "INSERT INTO task_events (id, task_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(_uuid_crash.uuid4()), TASK_ID, 'status_changed',
             json.dumps({'old_status': 'en_progreso', 'status': 'pendiente', 'source': 'task-worker', 'reason': 'crash_recovery'}, ensure_ascii=False),
             now_iso()),
        )
        rconn.execute(
            "UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=?, "
            "notes=COALESCE(notes,'')||? WHERE id=?",
            (now_iso(), f"\n[{now_iso()}] [task-worker] Crash recuperado: {str(e)[:200]}. Devuelta a pendiente.", TASK_ID),
        )
        rconn.commit()
        rconn.close()
```

> Nota: Se usa SQL directo en lugar de `record_event()` porque estamos en el bloque except, fuera del scope donde `record_event` está definido (y `conn` puede estar cerrado).

---

### Cambio 2I: Auto-recovery transient → pendiente (función `attempt_unblock`)

**Ubicación:** línea 153
**Problema:** Cambio de status actual a `pendiente` sin evento.

**Código actual (líneas 153-154):**
```python
        conn.execute("UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=? WHERE id=?", (now_iso(), task_id))
        conn.commit()
```

**Reemplazar por:**
```python
        record_event(conn, task_id, 'status_changed', {'old_status': 'bloqueada', 'status': 'pendiente', 'source': 'auto-recovery', 'reason': 'transient'})
        conn.execute("UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=? WHERE id=?", (now_iso(), task_id))
        conn.commit()
```

---

### Cambio 2J: Auto-recovery review_error → pendiente (función `attempt_unblock`)

**Ubicación:** línea 166
**Problema:** Cambio de status actual a `pendiente` sin evento.

**Código actual (líneas 166-167):**
```python
        conn.execute("UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=? WHERE id=?", (now_iso(), task_id))
        conn.commit()
```

**Reemplazar por:**
```python
        record_event(conn, task_id, 'status_changed', {'old_status': 'bloqueada', 'status': 'pendiente', 'source': 'auto-recovery', 'reason': 'review_error'})
        conn.execute("UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=? WHERE id=?", (now_iso(), task_id))
        conn.commit()
```

---

### Cambio 2K: Auto-recovery fix subtask → pendiente (función `attempt_unblock`)

**Ubicación:** línea 242
**Problema:** Tarea original vuelve a `pendiente` sin evento.

**Código actual (línea 242):**
```python
    conn.execute("UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=? WHERE id=?", (now_iso(), task_id))
    conn.commit()
```

**Reemplazar por:**
```python
    record_event(conn, task_id, 'status_changed', {'old_status': 'bloqueada', 'status': 'pendiente', 'source': 'auto-recovery', 'reason': 'fix_subtask_created'})
    conn.execute("UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=? WHERE id=?", (now_iso(), task_id))
    conn.commit()
```

---

## ARCHIVO 3: `scripts/task-executor.sh` (Python embebido — watchdog)

### Cambio 3A: Watchdog stuck recovery → pendiente (SIN evento)

**Ubicación:** líneas 79-84
**Problema:** Tareas stuck se devuelven a `pendiente` sin registrar evento.

**Código actual (líneas 79-84):**
```python
        ts = now.strftime('%Y-%m-%dT%H:%M:%S')
        conn.execute(
            "UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=?, "
            "notes=COALESCE(notes,'')||? WHERE id=?",
            (ts, f"\n[{ts}] [watchdog] Tarea stuck {int(age_min)}min sin worker vivo. Devuelta a pendiente.", task_id),
        )
        conn.commit()
```

**Reemplazar por:**
```python
        import uuid as _uuid_wd
        ts = now.strftime('%Y-%m-%dT%H:%M:%S')
        conn.execute(
            "INSERT INTO task_events (id, task_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(_uuid_wd.uuid4()), task_id, 'status_changed',
             json.dumps({'old_status': 'en_progreso', 'status': 'pendiente', 'source': 'watchdog', 'reason': f'stuck_{int(age_min)}min'}, ensure_ascii=False),
             ts),
        )
        conn.execute(
            "UPDATE tasks SET status='pendiente', assigned_to_claude=0, updated_at=?, "
            "notes=COALESCE(notes,'')||? WHERE id=?",
            (ts, f"\n[{ts}] [watchdog] Tarea stuck {int(age_min)}min sin worker vivo. Devuelta a pendiente.", task_id),
        )
        conn.commit()
```

> Nota: Se necesita `import json` al inicio del bloque WATCHDOG (actualmente ya está importado en línea 27).
> Verificar: el bloque WATCHDOG (línea 27) ya importa `json` — correcto.

---

## Resumen de cambios

| # | Archivo | Función/Zona | Transición | Tipo evento |
|---|---------|-------------|-----------|-------------|
| 1A | app.py:613 | `update_task()` | cualquier status → otro | `status_changed` |
| 1B | app.py:639 | `create_task()` | (nuevo) | `created` |
| 2A | task-worker.sh:452 | transient retry | en_progreso → pendiente | `status_changed` |
| 2B | task-worker.sh:460 | transient exhausted | en_progreso → bloqueada | `status_changed` |
| 2C | task-worker.sh:468 | exec error | en_progreso → bloqueada | `status_changed` |
| 2D | task-worker.sh:490 | health check | en_progreso → bloqueada | `status_changed` |
| 2E | task-worker.sh:379 | triage split | en_progreso → hecha | `status_changed` |
| 2F | task-worker.sh:572 | review approved | en_progreso → hecha | `status_changed` |
| 2G | task-worker.sh:589 | review failed | en_progreso → bloqueada | `status_changed` |
| 2H | task-worker.sh:600 | crash recovery | en_progreso → pendiente | `status_changed` |
| 2I | task-worker.sh:153 | auto-recovery transient | bloqueada → pendiente | `status_changed` |
| 2J | task-worker.sh:166 | auto-recovery review_error | bloqueada → pendiente | `status_changed` |
| 2K | task-worker.sh:242 | auto-recovery fix | bloqueada → pendiente | `status_changed` |
| 3A | task-executor.sh:79 | watchdog | en_progreso → pendiente | `status_changed` |

**Total: 13 cambios en 3 archivos protegidos.**

### Transiciones ya cubiertas (no requieren cambio)

| Archivo | Línea | Transición | Evento |
|---------|-------|-----------|--------|
| task-worker.sh | 310 | pendiente → en_progreso | `status_changed` ✅ |
| task-worker.sh | 414 | en_progreso → pendiente (rate limit) | `status_changed` ✅ |
| desk_close_task.py | 44-53 | cualquiera → hecha (deploy close) | `status_changed` ✅ |
