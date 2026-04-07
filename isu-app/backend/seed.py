#!/usr/bin/env python3
"""
Standalone seed data module for Desk.

Provides seed_demo_data() to populate an empty database with sample tasks,
projects, and day focus entries for demo/development purposes.

Usage:
    python backend/seed.py          # Run directly to seed the database
    from backend.seed import seed_demo_data  # Import and call
"""
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get('DESK_DB_PATH', str(BASE_DIR / 'data' / 'desk.sqlite3')))


def _db_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def seed_demo_data():
    """Insert sample projects, tasks, and day focus if the tasks table is empty."""
    with _db_conn() as conn:
        count = conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
        if count:
            print(f'Database already has {count} tasks — skipping seed.')
            return False

        ts = _now_iso()
        today = date.today().isoformat()

        # Projects
        projects = [
            ('proj-desk', 'desk', 'Desk', 'proyecto', 'Proyecto Desk'),
            ('proj-yume', 'yume', 'Yume', 'proyecto', 'Tareas operativas de Yume'),
        ]
        for pid, slug, name, area, desc in projects:
            conn.execute(
                "INSERT OR IGNORE INTO projects (id, slug, name, area, description, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (pid, slug, name, area, desc, ts, ts),
            )

        # Sample tasks
        sample_tasks = [
            ('task-1', 'Definir columnas del kanban', 'Pulir la logica del tablero principal', 'proyecto', 'proj-desk', 'en_progreso', 'alta', 0, today, None),
            ('task-2', 'Cerrar MVP de Desk', 'Validar pantallas, interaccion y flujo base', 'proyecto', 'proj-desk', 'pendiente', 'critica', 1, today, today),
            ('task-3', 'Preparar My Day', 'Ordenar prioridades del dia', 'personal', None, 'pendiente', 'media', 0, today, None),
            ('task-4', 'Separar tareas de empresa', 'Limpiar backlog general', 'empresa', None, 'inbox', 'media', 0, None, None),
            ('task-5', 'Revisar referencia visual Desk', 'Tomar decisiones de diseno', 'proyecto', 'proj-desk', 'bloqueada', 'alta', 0, None, None),
            ('task-6', 'Conectar calendario mas adelante', 'Fuera del MVP visual', 'empresa', None, 'pendiente', 'baja', 0, None, None),
        ]
        for row in sample_tasks:
            conn.execute(
                'INSERT OR IGNORE INTO tasks (id,title,description,area,project_id,status,priority,urgent,scheduled_for,due_at,source,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (*row, 'desk-seed', '', ts, ts),
            )

        # Day focus
        conn.execute(
            'INSERT OR IGNORE INTO day_focus (day, summary, created_at, updated_at) VALUES (?, ?, ?, ?)',
            (today, 'Cerrar el nucleo util de Desk', ts, ts),
        )
        for i, task_id in enumerate(['task-2', 'task-1', 'task-3']):
            conn.execute(
                'INSERT OR IGNORE INTO day_focus_tasks (day, task_id, position) VALUES (?, ?, ?)',
                (today, task_id, i),
            )

        conn.commit()
        print(f'Seeded {len(sample_tasks)} tasks, {len(projects)} projects.')
        return True


if __name__ == '__main__':
    seed_demo_data()
