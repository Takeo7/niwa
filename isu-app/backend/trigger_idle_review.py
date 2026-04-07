#!/usr/bin/env python3
"""
Lightweight HTTP trigger for the idle-project-review routine.

Runs on port 8081 (configurable via TRIGGER_PORT env var).
Single endpoint: POST /api/trigger/idle-review

Since backend/app.py is a protected file, this runs as a separate
microservice alongside the main Desk backend.

Usage:
    python3 backend/trigger_idle_review.py
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = Path(os.environ.get('WORKSPACE_DIR', str(BASE_DIR.parent)))
SCRIPT_PATH = WORKSPACE / 'scripts' / 'routines' / 'idle-project-review.sh'
PORT = int(os.environ.get('TRIGGER_PORT', '8081'))
HOST = os.environ.get('TRIGGER_HOST', '0.0.0.0')

# Simple in-memory lock to prevent concurrent runs
_running_lock = threading.Lock()
_is_running = False


class TriggerHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f'[trigger] {fmt % args}\n')

    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', 'https://desk.yumewagener.com')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Credentials', 'true')

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_POST(self):
        global _is_running

        if self.path.rstrip('/') != '/api/trigger/idle-review':
            return self._json({'error': 'not_found'}, 404)

        if not SCRIPT_PATH.is_file():
            return self._json({'error': 'script_not_found', 'path': str(SCRIPT_PATH)}, 500)

        with _running_lock:
            if _is_running:
                return self._json({'error': 'already_running'}, 409)
            _is_running = True

        try:
            result = subprocess.run(
                ['bash', str(SCRIPT_PATH)],
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(WORKSPACE),
                env=os.environ.copy(),
            )
            stdout = result.stdout.strip()
            try:
                parsed = json.loads(stdout)
            except (json.JSONDecodeError, ValueError):
                parsed = {'raw_output': stdout}

            if result.returncode != 0:
                return self._json({
                    'ok': False,
                    'error': parsed.get('detail', result.stderr.strip()[:500]),
                    'returncode': result.returncode,
                }, 500)

            action = parsed.get('action')
            if action == 'skip':
                return self._json({'ok': True, 'message': 'No hay tareas que revisar (hay tareas pendientes)'})
            elif action == 'created':
                count = parsed.get('count', 0)
                return self._json({'ok': True, 'message': f'{count} tareas nuevas creadas', 'count': count})
            elif action == 'error':
                return self._json({'error': parsed.get('detail', 'unknown')}, 500)
            else:
                return self._json({'ok': True, 'message': 'Idle review completed', **parsed})
        except subprocess.TimeoutExpired:
            return self._json({'error': 'timeout', 'detail': 'Script exceeded 10 minute limit'}, 504)
        except Exception as e:
            return self._json({'error': str(e)}, 500)
        finally:
            with _running_lock:
                _is_running = False


def main():
    server = ThreadingHTTPServer((HOST, PORT), TriggerHandler)
    print(f'[trigger] idle-review trigger listening on {HOST}:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n[trigger] shutting down')
        server.shutdown()


if __name__ == '__main__':
    main()
