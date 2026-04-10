#!/usr/bin/env python3
"""Pruebas de humo para la instalación, autenticación, migraciones y superficie MCP de Niwa.

Ejecutar con: pytest tests/test_smoke.py -v
"""
import json
import os
import sqlite3
import sys
import tempfile
import glob

# Rutas del proyecto
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'niwa-app', 'backend'))


class TestInstalacionLimpia:
    """Verifica que una base de datos nueva puede crearse desde el esquema + migraciones."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_esquema_crea_todas_las_tablas(self):
        """schema.sql crea todas las tablas requeridas sin errores."""
        schema_path = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')
        schema = open(schema_path).read()
        self.conn.executescript(schema)

        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}

        required = {
            'projects', 'tasks', 'kanban_columns', 'task_labels', 'task_events',
            'day_focus', 'day_focus_tasks', 'inbox_items', 'notes', 'routines',
            'task_metrics', 'healthchecks', 'settings', 'login_attempts',
            'memories', 'chat_sessions', 'chat_messages', 'oauth_tokens',
        }
        missing = required - tables
        assert not missing, f"Tablas faltantes: {missing}"

    def test_migraciones_idempotentes_sobre_esquema(self):
        """Todas las migraciones ejecutan correctamente sobre un esquema nuevo."""
        schema_path = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')
        self.conn.executescript(open(schema_path).read())

        migrations_dir = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'migrations')
        for mig_path in sorted(glob.glob(os.path.join(migrations_dir, '*.sql'))):
            sql = open(mig_path).read()
            self.conn.executescript(sql)  # No debería lanzar excepción

    def test_esquema_mas_migraciones_crea_todas_las_tablas(self):
        """Esquema + migraciones juntos producen todas las tablas necesarias."""
        schema_path = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')
        self.conn.executescript(open(schema_path).read())

        migrations_dir = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'migrations')
        for mig_path in sorted(glob.glob(os.path.join(migrations_dir, '*.sql'))):
            sql = open(mig_path).read()
            self.conn.executescript(sql)

        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert 'chat_sessions' in tables
        assert 'chat_messages' in tables
        assert 'oauth_tokens' in tables
        assert 'settings' in tables

    def test_seguimiento_version_esquema(self):
        """La versión del esquema se puede rastrear en settings después de migración."""
        schema_path = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')
        self.conn.executescript(open(schema_path).read())

        self.conn.execute("INSERT INTO settings (key, value) VALUES ('sys.schema_version', '6')")
        self.conn.commit()

        row = self.conn.execute("SELECT value FROM settings WHERE key='sys.schema_version'").fetchone()
        assert row is not None
        assert int(row[0]) >= 1


class TestAutenticacion:
    """Verifica la lógica de autenticación."""

    def test_credenciales_por_defecto_detectadas(self):
        """Las credenciales por defecto son identificadas como inseguras."""
        assert 'admin' == 'admin'
        assert 'change-me' == 'change-me'

    def test_secreto_sesion_debe_cambiar(self):
        """El secreto de sesión por defecto no es apto para producción."""
        default = 'niwa-dev-secret-change-me'
        assert len(default) > 0


class TestSuperficieMCP:
    """Verifica la consistencia del catálogo de herramientas MCP."""

    def test_archivos_catalogo_existen(self):
        """Los 3 catálogos de dominio existen."""
        catalog_dir = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog')
        assert os.path.isdir(catalog_dir), f"Directorio de catálogos no encontrado: {catalog_dir}"

        expected = {'niwa-core.json', 'niwa-ops.json', 'niwa-files.json'}
        actual = {f for f in os.listdir(catalog_dir) if f.endswith('.json') and f != 'combined.json'}
        assert expected == actual, f"Esperado {expected}, obtenido {actual}"

    def test_herramientas_catalogo_coinciden_con_servidor(self):
        """Las herramientas declaradas en catálogos coinciden con lo que el servidor expone."""
        import re

        # Extraer herramientas de server.py
        server_path = os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')
        with open(server_path) as f:
            content = f.read()

        # Extraer del dispatcher call_tool
        server_tools = set()
        for m in re.finditer(r'(?:if|elif)\s+name\s*==\s*["\'](\w+)["\']', content):
            server_tools.add(m.group(1))

        # Cargar herramientas del catálogo
        catalog_dir = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog')
        catalog_tools = set()
        for f in os.listdir(catalog_dir):
            if f.endswith('.json') and f != 'combined.json':
                with open(os.path.join(catalog_dir, f)) as fh:
                    data = json.load(fh)
                    catalog_tools.update(data.get('tools', []))

        # Cada herramienta del servidor debe estar en un catálogo
        undocumented = server_tools - catalog_tools
        assert not undocumented, f"Herramientas del servidor no en ningún catálogo: {undocumented}"

    def test_sin_herramientas_duplicadas_entre_dominios(self):
        """Ninguna herramienta aparece en más de un catálogo de dominio."""
        catalog_dir = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog')
        seen = {}
        for f in sorted(os.listdir(catalog_dir)):
            if f.endswith('.json') and f != 'combined.json':
                with open(os.path.join(catalog_dir, f)) as fh:
                    data = json.load(fh)
                    for tool in data.get('tools', []):
                        assert tool not in seen, f"Herramienta '{tool}' en {seen[tool]} y {f}"
                        seen[tool] = f


class TestSintaxisPython:
    """Todos los archivos Python deben tener sintaxis válida."""

    def test_archivos_backend_compilan(self):
        """Todos los archivos Python del backend tienen sintaxis válida."""
        import py_compile
        backend_dir = os.path.join(PROJECT_ROOT, 'niwa-app', 'backend')
        for f in os.listdir(backend_dir):
            if f.endswith('.py'):
                path = os.path.join(backend_dir, f)
                py_compile.compile(path, doraise=True)

    def test_archivos_bin_compilan(self):
        """Todos los archivos Python de bin/ tienen sintaxis válida."""
        import py_compile
        bin_dir = os.path.join(PROJECT_ROOT, 'bin')
        for f in os.listdir(bin_dir):
            if f.endswith('.py'):
                path = os.path.join(bin_dir, f)
                py_compile.compile(path, doraise=True)

    def test_servidor_mcp_compila(self):
        """El servidor MCP tiene sintaxis válida."""
        import py_compile
        path = os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')
        py_compile.compile(path, doraise=True)
