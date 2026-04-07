#!/usr/bin/env python3
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

MARKER = 'desk-deploy:verified'


def main() -> int:
    if len(sys.argv) != 3:
        print('Uso: desk_close_task.py <db_path> <task_id>', file=sys.stderr)
        return 2

    db_path = Path(sys.argv[1])
    task_id = sys.argv[2]
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

    with sqlite3.connect(db_path) as conn:
        row = conn.execute('SELECT project_id, notes FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            print('Tarea no encontrada', file=sys.stderr)
            return 1
        if row[0] != 'proj-desk':
            print('La tarea no pertenece al proyecto Desk', file=sys.stderr)
            return 1

        notes = row[1] or ''
        entry = f'{MARKER} | closed_at={ts}'
        if MARKER in notes:
            lines = [line for line in notes.splitlines() if MARKER not in line]
            lines.append(entry)
            notes = '\n'.join([line for line in lines if line.strip()])
        else:
            notes = (notes.rstrip() + '\n' + entry).strip()

        old_status = conn.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()[0]
        conn.execute(
            "UPDATE tasks SET notes=?, status='hecha', completed_at=?, updated_at=? WHERE id=?",
            (notes, ts, ts, task_id),
        )
        conn.execute(
            'INSERT INTO task_events (id, task_id, type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)',
            (
                str(uuid.uuid4()),
                task_id,
                'status_changed',
                json.dumps({'status': 'hecha', 'old_status': old_status, 'source': 'desk-deploy-close'}, ensure_ascii=False),
                ts,
            ),
        )
        conn.commit()
        print(ts)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
