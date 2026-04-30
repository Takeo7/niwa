"""Caddyfile generator for Niwa (Phase 5, NET-04/05).

Generates a Caddyfile that:
- Reverse-proxies the Niwa UI/API from ui_domain → localhost:bind_port
- Routes static deployments: slug.apps_domain → /api/deploy/{slug}/
- Routes process deployments: slug.apps_domain → localhost:{port}
- Respects project.public_enabled (skipped when False)

Usage:
    niwa-executor proxy render   — write to ~/.niwa/caddy/Caddyfile
    niwa-executor proxy validate — render + syntax-check (requires caddy binary)
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class ProjectRoute:
    slug: str
    deploy_type: Literal["static", "process"]
    port: int | None = None
    public_enabled: bool = True


def render_caddyfile(
    ui_domain: str,
    apps_domain: str,
    backend_port: int,
    routes: list[ProjectRoute],
    *,
    tls_email: str | None = None,
    local_tls: bool = False,
) -> str:
    """Return a Caddyfile string for the given configuration.

    Args:
        ui_domain: Domain for the Niwa UI/API (e.g. "niwa.example.com").
        apps_domain: Wildcard base for project deploys (e.g. "apps.example.com").
        backend_port: Port where FastAPI listens (default 8000).
        routes: Per-project routing config.
        tls_email: If set, enables ACME TLS with this email.
        local_tls: If True, use ``tls internal`` for local dev (Caddy's mkcert).
    """
    lines: list[str] = []

    tls_block = ""
    if tls_email:
        tls_block = f"\ttls {tls_email}\n"
    elif local_tls:
        tls_block = "\ttls internal\n"

    # UI / API block
    lines.append(f"{ui_domain} {{")
    if tls_block:
        lines.append(tls_block.rstrip())
    lines.append(f"\treverse_proxy localhost:{backend_port}")
    lines.append("}")
    lines.append("")

    # Per-project routes
    for r in routes:
        if not r.public_enabled:
            continue
        host = f"{r.slug}.{apps_domain}"
        lines.append(f"{host} {{")
        if tls_block:
            lines.append(tls_block.rstrip())
        if r.deploy_type == "static":
            lines.append(f"\treverse_proxy localhost:{backend_port}/api/deploy/{r.slug}/")
        else:
            if r.port:
                lines.append(f"\treverse_proxy localhost:{r.port}")
            else:
                lines.append(f"\t# process deployment not active — no port assigned")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def _niwa_home() -> Path:
    return Path(os.environ.get("NIWA_HOME", Path.home() / ".niwa"))


def write_caddyfile(content: str, path: Path | None = None) -> Path:
    """Write the Caddyfile to path (default: ~/.niwa/caddy/Caddyfile)."""
    target = path or (_niwa_home() / "caddy" / "Caddyfile")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target
