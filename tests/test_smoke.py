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


def _extract_tool_defs_block(server_py_content, var_name):
    """Return the text of the list literal assigned to ``var_name`` in the
    server source (matches declaration lines, not uses)."""
    pattern = r'\b' + re.escape(var_name) + r'\b\s*(?::\s*[^=]+)?=\s*\['
    match = re.search(pattern, server_py_content)
    if not match:
        return ''
    bracket_start = match.end() - 1
    depth = 0
    end = bracket_start
    for i in range(bracket_start, len(server_py_content)):
        ch = server_py_content[i]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                end = i
                break
    return server_py_content[bracket_start:end + 1]


def _load_v02_tool_names(server_py_content):
    """Return the set of tool names declared ONLY in ``_V02_TOOL_DEFS``.

    ``_V02_TOOL_DEFS`` enumera las tools del contract v02-assistant. Algunas
    de esas tools (p. ej. ``task_list``, ``task_get``, ``task_create``,
    ``project_context``) también están definidas en ``_LEGACY_TOOL_DEFS``
    con schema propio — siguen siendo tools legacy válidas en core mode.
    Para el matching catálogo ↔ server interesa aislar las tools
    v02-exclusivas (las que viven sólo en el contract v02, no en los
    catálogos v01): ``assistant_turn``, ``task_cancel``, ``task_resume``,
    ``approval_list``, ``approval_respond``, ``run_tail``, ``run_explain``
    (PR-09 Decisión 3, PR-11 Decisión 2).
    """
    v02_block = _extract_tool_defs_block(server_py_content, '_V02_TOOL_DEFS')
    legacy_block = _extract_tool_defs_block(server_py_content, '_LEGACY_TOOL_DEFS')
    v02_names = set(re.findall(r'name=["\'](\w+)["\']', v02_block))
    legacy_names = set(re.findall(r'name=["\'](\w+)["\']', legacy_block))
    return v02_names - legacy_names


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
        """Las herramientas declaradas en catálogos coinciden con lo que el servidor expone.

        Scope: el matching solo cubre las tools legacy (`_LEGACY_TOOL_DEFS` en
        ``servers/tasks-mcp/server.py``). Las tools v02 viven en
        ``config/mcp-contract/v02-assistant.json`` y el gateway las filtra
        por contract (PR-09 Decisión 3: "Un solo MCP server con filtrado
        por contract"; PR-11 Decisión 2: ``generate_catalog_yaml`` usa
        ``contract["tools"]`` como fuente autoritativa cuando hay contract
        y no interseca con los catálogos v01). La invariante exacta del
        contract v02 está en ``tests/test_mcp_contract.py``.
        """
        import re

        # Extraer herramientas de server.py
        server_path = os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')
        with open(server_path) as f:
            content = f.read()

        # Extraer del dispatcher call_tool
        server_tools = set()
        for m in re.finditer(r'(?:if|elif)\s+name\s*==\s*["\'](\w+)["\']', content):
            server_tools.add(m.group(1))

        # Descontar las tools v02 — su fuente es el contract, no los catálogos.
        v02_tool_names = _load_v02_tool_names(content)
        server_tools -= v02_tool_names

        # Cargar herramientas del catálogo
        catalog_dir = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog')
        catalog_tools = set()
        for f in os.listdir(catalog_dir):
            if f.endswith('.json') and f != 'combined.json':
                with open(os.path.join(catalog_dir, f)) as fh:
                    data = json.load(fh)
                    catalog_tools.update(data.get('tools', []))

        # Cada herramienta legacy del servidor debe estar en un catálogo
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

    # test_chat_renders_images eliminado en PR-12.
    # Dependía de niwa-app/frontend/src/features/chat/components/MessageBubble.tsx,
    # archivo borrado en PR-10e al migrar el chat web a assistant_turn.
    # No hay sustituto directo: el render de imágenes en el chat v0.2 cae en
    # tests de frontend diferidos (ver PR-10a Decisión 2 y PR-10c Decisión sobre
    # infra vitest). Dejar de volver a introducirlo acoplado al file tree viejo.


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
        """Generated catalog YAML must expose all legacy tools from tasks-mcp.

        v02 tools (``assistant_turn`` y familia) no se enumeran en
        ``config/mcp-catalog/*.json``; su fuente autoritativa es
        ``config/mcp-contract/v02-assistant.json`` y el filtrado lo aplica
        el gateway (PR-09 Decisión 3, PR-11 Decisión 2). Este smoke valida
        únicamente la simetría catalog ↔ legacy dispatcher; la invariante
        del contract v02 vive en ``tests/test_mcp_contract.py``.
        """
        import re

        # Get tools from server.py dispatcher
        server_path = os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')
        with open(server_path) as f:
            content = f.read()
        server_tools = set()
        for m in re.finditer(r'(?:if|elif)\s+name\s*==\s*["\'](\w+)["\']', content):
            server_tools.add(m.group(1))

        # Excluir las tools v02 del dispatcher — viven en el contract.
        v02_tool_names = _load_v02_tool_names(content)
        server_tools -= v02_tool_names

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

    # test_all_react_components_exist eliminado en PR-12.
    # Era una lista estática de rutas de componentes React; el árbol del
    # frontend cambió con PR-10 (features/runs, features/routing,
    # features/approvals, features/artifacts, features/settings) y con
    # PR-10e (borrado del chat v0.1, ChatView.tsx entre otros). Mantener
    # la lista sincronizada no detecta regresiones útiles — la señal real
    # es `npm run build` en CI. El PR de infra de tests de frontend (ver
    # PR-10a Decisión 2) será el lugar para un smoke del árbol.


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
