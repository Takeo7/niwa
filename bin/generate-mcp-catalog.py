#!/usr/bin/env python3
"""Genera y valida el catálogo MCP desde la implementación real del servidor."""
import json
import os
import re
import sys

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..')


def get_tools_from_server():
    """Extrae nombres de herramientas del handler call_tool en server.py."""
    server_path = os.path.join(PROJECT_ROOT, 'servers', 'tasks-mcp', 'server.py')
    with open(server_path) as f:
        content = f.read()

    # Extract tool names from the call_tool dispatcher (elif name == "xxx" patterns)
    # This is the most reliable source — it's what actually gets executed
    tools = set()
    for m in re.finditer(r'(?:if|elif)\s+name\s*==\s*["\'](\w+)["\']', content):
        tools.add(m.group(1))

    # Also extract from Tool(name="xxx") definitions in list_tools
    for m in re.finditer(r'Tool\(\s*name\s*=\s*["\'](\w+)["\']', content):
        tools.add(m.group(1))

    return sorted(tools)


def load_catalogs():
    """Carga todos los archivos de catálogo."""
    catalog_dir = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog')
    catalogs = {}
    for f in sorted(os.listdir(catalog_dir)):
        if f.endswith('.json') and f != 'combined.json':
            with open(os.path.join(catalog_dir, f)) as fh:
                data = json.load(fh)
                catalogs[data['name']] = data
    return catalogs


def main():
    server_tools = get_tools_from_server()
    catalogs = load_catalogs()

    catalog_tools = set()
    for name, cat in catalogs.items():
        print(f"\n{name}: {cat['description']}")
        for t in cat['tools']:
            print(f"  - {t}")
            catalog_tools.add(t)

    # Herramientas no documentadas
    undocumented = set(server_tools) - catalog_tools
    if undocumented:
        print(f"\n⚠ Herramientas en el servidor pero NO en ningún catálogo: {undocumented}")
        sys.exit(1)

    # Herramientas fantasma (en catálogo pero no en servidor)
    ghost = catalog_tools - set(server_tools)
    if ghost:
        print(f"\n⚠ Herramientas en catálogos pero NO en el servidor: {ghost}")
        sys.exit(1)

    print(f"\n✓ Las {len(catalog_tools)} herramientas están contabilizadas en {len(catalogs)} dominios")

    # Generar catálogo combinado
    combined = {
        "version": "1.0",
        "domains": {name: cat for name, cat in catalogs.items()},
        "total_tools": len(catalog_tools),
    }
    combined_path = os.path.join(PROJECT_ROOT, 'config', 'mcp-catalog', 'combined.json')
    with open(combined_path, 'w') as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
    print(f"Catálogo combinado escrito en config/mcp-catalog/combined.json")


if __name__ == '__main__':
    main()
