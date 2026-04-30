"""Tests for Phase 5 Caddy generator — snapshot tests for Caddyfile output."""

from __future__ import annotations

from app.network.caddy import ProjectRoute, render_caddyfile


def test_render_basic_ui_only() -> None:
    result = render_caddyfile(
        ui_domain="niwa.example.com",
        apps_domain="apps.example.com",
        backend_port=8000,
        routes=[],
    )
    assert "niwa.example.com" in result
    assert "reverse_proxy localhost:8000" in result


def test_render_static_project_route() -> None:
    result = render_caddyfile(
        ui_domain="niwa.example.com",
        apps_domain="apps.example.com",
        backend_port=8000,
        routes=[ProjectRoute(slug="myapp", deploy_type="static")],
    )
    assert "myapp.apps.example.com" in result
    assert "reverse_proxy localhost:8000/api/deploy/myapp/" in result


def test_render_process_project_route() -> None:
    result = render_caddyfile(
        ui_domain="niwa.example.com",
        apps_domain="apps.example.com",
        backend_port=8000,
        routes=[ProjectRoute(slug="svc", deploy_type="process", port=41001)],
    )
    assert "svc.apps.example.com" in result
    assert "reverse_proxy localhost:41001" in result


def test_skips_non_public_routes() -> None:
    result = render_caddyfile(
        ui_domain="niwa.example.com",
        apps_domain="apps.example.com",
        backend_port=8000,
        routes=[
            ProjectRoute(slug="public", deploy_type="static", public_enabled=True),
            ProjectRoute(slug="private", deploy_type="static", public_enabled=False),
        ],
    )
    assert "public.apps.example.com" in result
    assert "private.apps.example.com" not in result


def test_render_with_tls_email() -> None:
    result = render_caddyfile(
        ui_domain="niwa.example.com",
        apps_domain="apps.example.com",
        backend_port=8000,
        routes=[],
        tls_email="admin@example.com",
    )
    assert "tls admin@example.com" in result


def test_render_with_local_tls() -> None:
    result = render_caddyfile(
        ui_domain="niwa.local",
        apps_domain="apps.niwa.local",
        backend_port=8000,
        routes=[],
        local_tls=True,
    )
    assert "tls internal" in result


def test_render_process_no_port_shows_comment() -> None:
    result = render_caddyfile(
        ui_domain="niwa.example.com",
        apps_domain="apps.example.com",
        backend_port=8000,
        routes=[ProjectRoute(slug="noport", deploy_type="process", port=None)],
    )
    assert "noport.apps.example.com" in result
    assert "not active" in result
