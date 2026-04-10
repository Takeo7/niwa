#!/usr/bin/env python3
"""End-to-end test: creates a task, waits for executor, verifies result."""
import os, sqlite3, time, sys, uuid

DB = os.environ.get("NIWA_DB_PATH", os.path.expanduser("~/.niwa/data/niwa.sqlite3"))

def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def test_executor():
    task_id = f"e2e-{uuid.uuid4().hex[:8]}"
    now = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
    
    c = db()
    c.execute(
        "INSERT INTO tasks (id,title,description,area,status,priority,source,created_at,updated_at,assigned_to_yume,assigned_to_claude) "
        "VALUES (?,?,?,?,?,?,?,?,?,0,1)",
        (task_id, "E2E Test", "Reply with exactly: E2E_PASS", "sistema", "pendiente", "alta", "test", now, now)
    )
    c.commit()
    print(f"Created task {task_id}")
    
    for i in range(60):
        time.sleep(5)
        row = db().execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        status = row["status"] if row else "not found"
        print(f"  [{(i+1)*5}s] {status}")
        if status in ("hecha", "bloqueada"):
            break
    
    # Check result
    evt = db().execute(
        "SELECT payload_json FROM task_events WHERE task_id=? AND type='comment' ORDER BY created_at DESC LIMIT 1",
        (task_id,)
    ).fetchone()
    
    if not evt:
        print("FAIL: no output")
        return False
    
    import json
    output = json.loads(evt["payload_json"]).get("output", "")
    passed = "E2E_PASS" in output
    print(f"{'PASS' if passed else 'FAIL'}: output contains {'E2E_PASS' if passed else repr(output[:100])}")
    
    # Cleanup
    db().execute("DELETE FROM tasks WHERE id=?", (task_id,))
    db().execute("DELETE FROM task_events WHERE task_id=?", (task_id,))
    db().commit()
    
    return passed

if __name__ == "__main__":
    ok = test_executor()
    sys.exit(0 if ok else 1)
