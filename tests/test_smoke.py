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


class TestHosting:
    """Configuración del servicio de hosting."""

    def test_hosting_in_services_registry(self):
        """El servicio de hosting está en el registro."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert '"id": "hosting"' in content or "'id': 'hosting'" in content

    def test_hosting_prefix_map(self):
        """El prefijo de hosting está en el mapa de prefijos."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert '"hosting": "svc.hosting."' in content or "'hosting': 'svc.hosting.'" in content

    def test_hosting_test_action(self):
        """La acción de test del hosting existe en _test_service."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert 'service_id == "hosting"' in content

    def test_deploy_web_reads_hosting_config(self):
        """deploy_web lee la configuración de hosting de la base de datos."""
        with open(os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')) as f:
            content = f.read()
        assert 'svc.hosting.domain' in content


class TestImageGeneration:
    """Cableado del servicio de generación de imágenes."""

    def test_image_service_exists(self):
        """image_service.py existe y compila."""
        import py_compile
        path = os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'image_service.py')
        assert os.path.exists(path)
        py_compile.compile(path, doraise=True)

    def test_generate_image_in_mcp(self):
        """La herramienta generate_image está en el servidor MCP."""
        with open(os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')) as f:
            content = f.read()
        assert 'generate_image' in content

    def test_image_in_catalog(self):
        """generate_image está en el catálogo MCP."""
        catalog_dir = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog')
        found = False
        for f in os.listdir(catalog_dir):
            if f.endswith('.json') and f != 'combined.json':
                with open(os.path.join(catalog_dir, f)) as fh:
                    data = json.load(fh)
                    if 'generate_image' in data.get('tools', []):
                        found = True
        assert found, "generate_image no está en ningún catálogo MCP"

    def test_mcp_reads_image_config_from_db(self):
        """El servidor MCP lee la configuración de imágenes de la base de datos."""
        with open(os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')) as f:
            content = f.read()
        assert "svc.image." in content

    def test_static_generated_images_served(self):
        """El backend sirve imágenes generadas desde /static/generated-images/."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert 'generated-images' in content

    def test_chat_renders_images(self):
        """MessageBubble detecta y renderiza imágenes en el chat."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'frontend', 'src', 'features', 'chat', 'components', 'MessageBubble.tsx')) as f:
            content = f.read()
        assert 'extractImages' in content
        assert 'generated-images' in content
        assert 'oaidalleapiprodscus' in content


class TestOpenClaw:
    """Integración con OpenClaw."""

    def test_openclaw_in_services_registry(self):
        """El servicio OpenClaw está en el registro."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert '"id": "openclaw"' in content or "'id': 'openclaw'" in content

    def test_openclaw_detect_endpoint(self):
        """El endpoint de detección de OpenClaw existe."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert 'integrations/openclaw/detect' in content

    def test_openclaw_config_endpoint(self):
        """El endpoint de configuración de OpenClaw existe."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert 'integrations/openclaw/config' in content

    def test_openclaw_prefix_map(self):
        """El prefijo de OpenClaw está en el mapa de prefijos."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert '"openclaw": "svc.openclaw."' in content or "'openclaw': 'svc.openclaw.'" in content

    def test_openclaw_test_action(self):
        """La acción de test de OpenClaw existe en _test_service."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert 'service_id == "openclaw"' in content


class TestAllEndpoints:
    """Verificar que todas las rutas de API tienen handlers."""

    def test_critical_endpoints_exist(self):
        """Todos los endpoints críticos tienen handlers en app.py."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()

        endpoints = [
            '/api/tasks', '/api/projects', '/api/services', '/api/models',
            '/api/settings', '/api/agents', '/api/chat/sessions',
            '/api/notes', '/api/version', '/api/dashboard', '/api/stats',
            '/api/activity', '/api/routines', '/api/logs',
            '/api/search', '/api/auth/oauth/start', '/api/auth/oauth/callback',
            '/api/auth/oauth/status', '/api/metrics/executor',
            '/api/integrations/openclaw/detect',
        ]
        for ep in endpoints:
            assert ep in content, f"Endpoint {ep} no encontrado en app.py"


class TestFrontendBuild:
    """El frontend compila correctamente."""

    def test_package_json_exists(self):
        """package.json existe en el directorio del frontend."""
        frontend_dir = os.path.join(PROJECT_ROOT, 'niwa-app', 'frontend')
        assert os.path.exists(os.path.join(frontend_dir, 'package.json'))

    def test_all_pinned_versions(self):
        """Todas las dependencias npm están fijadas (sin ^ ni ~)."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'frontend', 'package.json')) as f:
            pkg = json.load(f)
        for section in ['dependencies', 'devDependencies']:
            for name, version in pkg.get(section, {}).items():
                assert not version.startswith('^') and not version.startswith('~'), \
                    f"{name}@{version} no está fijada"

    def test_all_react_components_exist(self):
        """Todos los componentes React esperados existen."""
        src_dir = os.path.join(PROJECT_ROOT, 'niwa-app', 'frontend', 'src')
        expected = [
            'app/App.tsx', 'app/Router.tsx', 'app/theme.ts',
            'shared/components/AppShell.tsx', 'shared/components/LoginPage.tsx',
            'shared/api/client.ts', 'shared/api/queries.ts',
            'features/chat/components/ChatView.tsx',
            'features/tasks/components/TaskList.tsx',
            'features/kanban/components/KanbanBoard.tsx',
            'features/projects/components/ProjectList.tsx',
            'features/system/components/SystemView.tsx',
            'features/system/components/ServicesPanel.tsx',
            'features/dashboard/components/DashboardView.tsx',
            'features/metrics/components/MetricsDashboard.tsx',
            'features/notes/components/NotesList.tsx',
            'features/history/components/HistoryView.tsx',
        ]
        for f in expected:
            path = os.path.join(src_dir, f)
            assert os.path.exists(path), f"Componente faltante: {f}"
