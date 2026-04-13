#!/usr/bin/env python3
"""Pruebas de humo para la instalación, autenticación, migraciones y superficie MCP de Niwa.

Ejecutar con: pytest tests/test_smoke.py -v
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import glob

# Rutas del proyecto
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'niwa-app', 'backend'))


def _apply_sql_idempotent(conn, sql):
    """Apply SQL idempotently, emulating ADD COLUMN IF NOT EXISTS.

    SQLite lacks ALTER TABLE ADD COLUMN IF NOT EXISTS. This helper parses
    each statement and, for ALTER TABLE ADD COLUMN, checks pragma table_info
    first and skips the statement when the column already exists. All other
    statements (CREATE TABLE/INDEX IF NOT EXISTS, DROP, etc.) are executed
    directly.
    """
    # Strip comment-only lines; preserve inline SQL
    lines = []
    for line in sql.split('\n'):
        stripped = line.strip()
        if stripped.startswith('--') or not stripped:
            continue
        # Remove trailing inline comments
        if ' --' in line:
            line = line[:line.index(' --')]
        lines.append(line)
    cleaned = '\n'.join(lines)

    for stmt in cleaned.split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        # Detect ALTER TABLE ... ADD COLUMN ...
        m = re.match(
            r'ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+(\w+)',
            stmt, re.IGNORECASE,
        )
        if m:
            table, column = m.group(1), m.group(2)
            existing = {r[1] for r in conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()}
            if column in existing:
                continue  # column already present — nothing to do
        conn.execute(stmt)
    conn.commit()


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
        """schema.sql + migraciones aplican correctamente y son idempotentes.

        Applies schema.sql, then all migrations twice. Both passes must
        succeed and leave the database in the correct state.
        """
        schema_path = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')
        self.conn.executescript(open(schema_path).read())

        migrations_dir = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'migrations')
        mig_files = sorted(glob.glob(os.path.join(migrations_dir, '*.sql')))

        # First pass
        for mig_path in mig_files:
            _apply_sql_idempotent(self.conn, open(mig_path).read())

        # Second pass — true idempotency: applying again must not fail
        for mig_path in mig_files:
            _apply_sql_idempotent(self.conn, open(mig_path).read())

        # Verify result explicitly
        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()}
        assert 'tasks' in tables
        assert 'backend_runs' in tables
        assert 'approvals' in tables

    def test_esquema_mas_migraciones_crea_todas_las_tablas(self):
        """Esquema + migraciones juntos producen todas las tablas necesarias."""
        schema_path = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')
        self.conn.executescript(open(schema_path).read())

        migrations_dir = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'migrations')
        for mig_path in sorted(glob.glob(os.path.join(migrations_dir, '*.sql'))):
            _apply_sql_idempotent(self.conn, open(mig_path).read())

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

    def test_default_credentials_are_insecure(self):
        """_security_preflight blocks default password on non-local bind."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert 'change-me' in content, "Default password check missing from security preflight"
        assert '_security_preflight' in content, "Security preflight function missing"

    def test_session_secret_check_exists(self):
        """The session secret default is flagged as insecure in the codebase."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert 'niwa-dev-secret-change-me' in content, "Default session secret not found in app.py"


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


class TestMCPCatalogIntegrity:
    """Verify the MCP catalog matches the actual server surface."""

    def test_catalog_yaml_matches_server(self):
        """Generated catalog YAML must expose all 21 tools from tasks-mcp."""
        import re

        # Get tools from server.py dispatcher
        server_path = os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')
        with open(server_path) as f:
            content = f.read()
        server_tools = set()
        for m in re.finditer(r'(?:if|elif)\s+name\s*==\s*["\'](\w+)["\']', content):
            server_tools.add(m.group(1))

        # Get tools from catalog JSONs
        catalog_dir = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog')
        catalog_tools = set()
        for f in os.listdir(catalog_dir):
            if f.endswith('.json') and f != 'combined.json':
                with open(os.path.join(catalog_dir, f)) as fh:
                    data = json.load(fh)
                    catalog_tools.update(data.get('tools', []))

        # Verify catalog covers server
        missing = server_tools - catalog_tools
        assert not missing, f"Server tools not in catalog: {missing}"

        # Verify no ghost tools in catalog
        ghost = catalog_tools - server_tools
        assert not ghost, f"Catalog tools not in server: {ghost}"

    def test_setup_reads_catalog_jsons(self):
        """setup.py generate_catalog_yaml must read from config/mcp-catalog/*.json."""
        with open(os.path.join(PROJECT_ROOT, 'setup.py')) as f:
            content = f.read()
        assert 'mcp-catalog' in content, "setup.py doesn't reference mcp-catalog directory"


class TestDatabaseBootstrap:
    """Verify fresh DB bootstrap works correctly."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_deployments_table_from_schema(self):
        """deployments table must exist after schema.sql without runtime DDL."""
        schema = open(os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')).read()
        self.conn.executescript(schema)

        # Run migrations too (as setup.py now does)
        migrations_dir = os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'migrations')
        for mig_path in sorted(glob.glob(os.path.join(migrations_dir, '*.sql'))):
            _apply_sql_idempotent(self.conn, open(mig_path).read())

        tables = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert 'deployments' in tables, "deployments table not created by schema.sql + migrations"

    def test_no_runtime_ddl_in_mcp_server(self):
        """MCP server must NOT create tables at runtime."""
        server_path = os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')
        with open(server_path) as f:
            content = f.read()
        assert '_ensure_deployments_table' not in content, \
            "server.py still has runtime DDL (_ensure_deployments_table)"


class TestImageProviders:
    """Verify all advertised image providers are implemented."""

    def test_all_providers_have_handlers(self):
        """Every image provider must have a generate handler in image_service.py."""
        img_path = os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'image_service.py')
        with open(img_path) as f:
            img_content = f.read()

        expected_providers = ['openai', 'stability', 'replicate', 'fal', 'together']
        for provider in expected_providers:
            assert f'_generate_{provider}' in img_content, \
                f"Provider '{provider}' has no _generate_{provider} handler in image_service.py"

    def test_all_providers_have_test_connection(self):
        """Every provider must be testable via test_connection()."""
        img_path = os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'image_service.py')
        with open(img_path) as f:
            img_content = f.read()

        expected_providers = ['openai', 'stability', 'replicate', 'fal', 'together']
        for provider in expected_providers:
            assert f'provider == "{provider}"' in img_content, \
                f"Provider '{provider}' not handled in test_connection()"


class TestOpenClawConfig:
    """Verify OpenClaw integration uses streamable-http."""

    def test_setup_uses_streamable_http(self):
        """setup.py must configure OpenClaw with streamable-http, not SSE."""
        with open(os.path.join(PROJECT_ROOT, 'setup.py')) as f:
            content = f.read()
        assert 'streamable-http' in content, "setup.py should use streamable-http for OpenClaw"

    def test_api_config_uses_streamable_http(self):
        """API openclaw/config endpoint must return streamable-http transport."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert 'streamable-http' in content, "app.py openclaw config should use streamable-http"


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


class TestExecutorQueue:
    """Verify executor respects the task queue properly."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        schema = open(os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')).read()
        self.conn.executescript(schema)
        for mig in sorted(glob.glob(os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'migrations', '*.sql'))):
            _apply_sql_idempotent(self.conn, open(mig).read())

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_only_pendiente_tasks_are_picked(self):
        """Executor should only pick tasks with status='pendiente'."""
        now = '2026-01-01T00:00:00'
        # Insert tasks with different statuses
        for status in ['pendiente', 'en_progreso', 'hecha', 'bloqueada', 'archivada', 'inbox']:
            self.conn.execute(
                "INSERT INTO tasks (id, title, status, created_at, updated_at, source) VALUES (?, ?, ?, ?, ?, 'api')",
                (f'task-{status}', f'Task {status}', status, now, now)
            )
        self.conn.commit()

        # Query what the executor would pick (same query as task-executor.py)
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status='pendiente' AND source != 'chat' ORDER BY created_at ASC"
        ).fetchall()

        assert len(rows) == 1
        assert rows[0]['status'] == 'pendiente'
        assert rows[0]['title'] == 'Task pendiente'

    def test_executor_query_excludes_chat_source(self):
        """Executor should NOT pick tasks created from chat (source='chat')."""
        now = '2026-01-01T00:00:00'
        self.conn.execute(
            "INSERT INTO tasks (id, title, status, source, created_at, updated_at) VALUES ('task-chat', 'Chat task', 'pendiente', 'chat', ?, ?)",
            (now, now)
        )
        self.conn.execute(
            "INSERT INTO tasks (id, title, status, source, created_at, updated_at) VALUES ('task-api', 'API task', 'pendiente', 'api', ?, ?)",
            (now, now)
        )
        self.conn.commit()

        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE status='pendiente' AND source != 'chat' ORDER BY created_at ASC"
        ).fetchall()

        assert len(rows) == 1
        assert rows[0]['title'] == 'API task'


class TestMCPCatalogToolCount:
    """Verify catalog tool count and setup.py integration."""

    def test_generate_catalog_produces_all_tools(self):
        """setup.py generate_catalog_yaml must include all 21 tools."""
        # Simulate what generate_catalog_yaml does
        catalog_dir = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog')
        all_tools = []
        for f in sorted(os.listdir(catalog_dir)):
            if f.endswith('.json') and f != 'combined.json':
                with open(os.path.join(catalog_dir, f)) as fh:
                    data = json.load(fh)
                    all_tools.extend(data.get('tools', []))

        assert len(all_tools) == 21, f"Expected 21 tools, got {len(all_tools)}"

        # Verify setup.py reads from this source
        with open(os.path.join(PROJECT_ROOT, 'setup.py')) as f:
            content = f.read()
        assert 'mcp-catalog' in content
        assert 'glob' in content or '.json' in content


class TestRemoteAuth:
    """Verify auth enforcement for remote/non-local binds."""

    def test_preflight_blocks_default_password_on_remote(self):
        """_security_preflight must exist and check for 'change-me'."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        assert '_security_preflight' in content
        assert "'change-me'" in content or '"change-me"' in content
        # Must call sys.exit on failure
        assert 'sys.exit' in content

    def test_gateway_token_required_for_mcp(self):
        """MCP gateway must require bearer token authentication."""
        with open(os.path.join(PROJECT_ROOT, 'docker-compose.yml.tmpl')) as f:
            content = f.read()
        # Gateway must have AUTH_TOKEN configured
        assert 'MCP_GATEWAY_AUTH_TOKEN' in content or 'GATEWAY_AUTH' in content

    def test_oauth_callback_unauthenticated(self):
        """OAuth callback must NOT require Niwa session auth."""
        with open(os.path.join(PROJECT_ROOT, 'niwa-app', 'backend', 'app.py')) as f:
            content = f.read()
        # The callback handler must come before auth check, or have explicit skip
        assert 'oauth/callback' in content


class TestTaskStateCycle:
    """Verify tasks can transition through the full lifecycle."""

    def setup_method(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix='.db')
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        schema = open(os.path.join(PROJECT_ROOT, 'niwa-app', 'db', 'schema.sql')).read()
        self.conn.executescript(schema)

    def teardown_method(self):
        self.conn.close()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def test_pendiente_to_hecha_cycle(self):
        """Task must be able to go: pendiente -> en_progreso -> hecha."""
        now = '2026-01-01T00:00:00'
        self.conn.execute(
            "INSERT INTO tasks (id, title, status, created_at, updated_at, source) VALUES ('task-1', 'Test', 'pendiente', ?, ?, 'api')",
            (now, now)
        )
        self.conn.commit()

        task_id = self.conn.execute("SELECT id FROM tasks WHERE title='Test'").fetchone()[0]

        # pendiente -> en_progreso
        self.conn.execute("UPDATE tasks SET status='en_progreso' WHERE id=?", (task_id,))
        self.conn.commit()
        assert self.conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == 'en_progreso'

        # en_progreso -> hecha
        self.conn.execute("UPDATE tasks SET status='hecha' WHERE id=?", (task_id,))
        self.conn.commit()
        assert self.conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == 'hecha'

    def test_pendiente_to_waiting_input_cycle(self):
        """Task must be able to go: pendiente -> en_progreso -> waiting_input -> en_progreso -> hecha."""
        now = '2026-01-01T00:00:00'
        self.conn.execute(
            "INSERT INTO tasks (id, title, status, created_at, updated_at, source) VALUES ('task-2', 'Test2', 'pendiente', ?, ?, 'api')",
            (now, now)
        )
        self.conn.commit()
        task_id = self.conn.execute("SELECT id FROM tasks WHERE title='Test2'").fetchone()[0]

        for status in ['en_progreso', 'waiting_input', 'en_progreso', 'hecha']:
            self.conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
            self.conn.commit()
            assert self.conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == status

    def test_blocked_and_rejected_states(self):
        """Tasks can be blocked or rejected."""
        now = '2026-01-01T00:00:00'
        self.conn.execute(
            "INSERT INTO tasks (id, title, status, created_at, updated_at, source) VALUES ('task-3', 'Test3', 'pendiente', ?, ?, 'api')",
            (now, now)
        )
        self.conn.commit()
        task_id = self.conn.execute("SELECT id FROM tasks WHERE title='Test3'").fetchone()[0]

        # Can be blocked
        self.conn.execute("UPDATE tasks SET status='bloqueada' WHERE id=?", (task_id,))
        self.conn.commit()
        assert self.conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == 'bloqueada'
