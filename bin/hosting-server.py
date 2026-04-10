#!/usr/bin/env python3
"""Lightweight static hosting server for Niwa projects.
Serves /slug/ → projects_dir/slug/ for each deployed project."""

import http.server
import os
import sqlite3
import socketserver
from pathlib import Path

PORT = int(os.environ.get("NIWA_HOSTING_PORT", "8880"))
DB_PATH = os.environ.get("NIWA_DB_PATH", os.path.expanduser("~/.niwa/data/niwa.sqlite3"))
PROJECTS_DIR = Path(os.environ.get("NIWA_PROJECTS_DIR", "/opt/niwatest/data/projects"))

class NiwaHostingHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        # /slug/file.html → PROJECTS_DIR/slug/file.html
        path = path.lstrip("/")
        parts = path.split("/", 1)
        if parts and parts[0]:
            slug = parts[0]
            rest = parts[1] if len(parts) > 1 else "index.html"
            project_dir = PROJECTS_DIR / slug
            if project_dir.is_dir():
                full = (project_dir / rest).resolve()
                # Prevent directory traversal — resolved path must stay inside PROJECTS_DIR
                if not str(full).startswith(str(PROJECTS_DIR.resolve())):
                    return str(PROJECTS_DIR / "index.html")
                if full.is_dir():
                    full = full / "index.html"
                return str(full)
        # Root: show list of projects
        return str(PROJECTS_DIR / "index.html")
    
    def do_GET(self):
        if self.path == "/" or self.path == "":
            # List deployed projects
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            projects = [d.name for d in PROJECTS_DIR.iterdir() if d.is_dir()] if PROJECTS_DIR.exists() else []
            html = "<html><head><title>Niwa Hosting</title></head><body style='font-family:sans-serif;padding:2rem;'>"
            html += "<h1>Niwa Projects</h1><ul>"
            for p in sorted(projects):
                html += f'<li><a href="/{p}/">{p}</a></li>'
            html += "</ul></body></html>"
            self.wfile.write(html.encode())
            return
        super().do_GET()
    
    def log_message(self, format, *args):
        pass  # silent

if __name__ == "__main__":
    with socketserver.TCPServer(("0.0.0.0", PORT), NiwaHostingHandler) as httpd:
        print(f"Niwa hosting on port {PORT}, serving {PROJECTS_DIR}")
        httpd.serve_forever()
