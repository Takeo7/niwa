#!/usr/bin/env python3
"""Prueba end-to-end: crea una tarea, espera al executor, verifica el resultado.

Requiere una instancia de Niwa en ejecución con el executor habilitado.
Ejecutar con: pytest tests/test_e2e.py -v
O directamente: python3 tests/test_e2e.py
"""
import json
import os
import sqlite3
import sys
import time
import uuid

DB = os.environ.get("NIWA_DB_PATH", os.path.expanduser("~/.niwa/data/niwa.sqlite3"))


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def test_executor():
    """Crea una tarea, espera a que el executor la procese y verifica el resultado."""
    task_id = f"e2e-{uuid.uuid4().hex[:8]}"
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()

    c = db()
    c.execute(
        "INSERT INTO tasks (id,title,description,area,status,priority,source,created_at,updated_at,assigned_to_yume,assigned_to_claude) "
        "VALUES (?,?,?,?,?,?,?,?,?,0,1)",
        (task_id, "E2E Test", "Reply with exactly: E2E_PASS", "sistema", "pendiente", "alta", "test", now, now)
    )
    c.commit()
    print(f"Tarea creada: {task_id}")

    status = "not found"
    for i in range(60):
        time.sleep(5)
        row = db().execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        status = row["status"] if row else "not found"
        print(f"  [{(i+1)*5}s] {status}")
        if status in ("hecha", "bloqueada"):
            break

    # Verificar resultado
    evt = db().execute(
        "SELECT payload_json FROM task_events WHERE task_id=? AND type='comment' ORDER BY created_at DESC LIMIT 1",
        (task_id,)
    ).fetchone()

    assert evt is not None, f"Sin salida del executor para la tarea {task_id}"

    output = json.loads(evt["payload_json"]).get("output", "")
    assert "E2E_PASS" in output, f"La salida no contiene E2E_PASS: {output[:100]}"

    # Limpieza
    try:
        conn = db()
        conn.execute("DELETE FROM task_events WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        conn.commit()
        conn.close()
    except Exception as cleanup_err:
        print(f"  (aviso de limpieza: {cleanup_err})")


if __name__ == "__main__":
    test_executor()
    print("PASS")
