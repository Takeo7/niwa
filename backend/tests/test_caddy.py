"""Tests for Phase 5 Caddy generator — snapshot tests for Caddyfile output."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Deployment, Project
from app.network.caddy import ProjectRoute, render_caddyfile, routes_from_session


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
        routes=[ProjectRoute(slug="myapp", deploy_type="static", public_enabled=True)],
    )
    assert "myapp.apps.example.com" in result
    assert "rewrite * /api/deploy/myapp{uri}" in result
    assert "reverse_proxy localhost:8000" in result


def test_render_process_project_route() -> None:
    result = render_caddyfile(
        ui_domain="niwa.example.com",
        apps_domain="apps.example.com",
        backend_port=8000,
        routes=[
            ProjectRoute(
                slug="svc",
                deploy_type="process",
                port=41001,
                public_enabled=True,
            )
        ],
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
        routes=[
            ProjectRoute(
                slug="noport",
                deploy_type="process",
                port=None,
                public_enabled=True,
            )
        ],
    )
    assert "noport.apps.example.com" in result
    assert "not active" in result


def test_routes_from_session_include_public_projects_only() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    with SessionLocal() as session:
        session.add_all(
            [
                Project(
                    slug="private",
                    name="Private",
                    kind="web-deployable",
                    local_path="/tmp/private",
                    public_enabled=False,
                ),
                Project(
                    slug="static",
                    name="Static",
                    kind="web-deployable",
                    local_path="/tmp/static",
                    public_enabled=True,
                ),
                Project(
                    slug="worker",
                    name="Worker",
                    kind="web-deployable",
                    local_path="/tmp/worker",
                    public_enabled=True,
                ),
            ]
        )
        session.commit()
        worker = session.query(Project).filter(Project.slug == "worker").one()
        session.add(
            Deployment(
                project_id=worker.id,
                deploy_type="process",
                status="healthy",
                port=41099,
                healthcheck_path="/",
            )
        )
        session.commit()

        routes = routes_from_session(session)

    engine.dispose()
    assert routes == [
        ProjectRoute(slug="static", deploy_type="static", public_enabled=True),
        ProjectRoute(
            slug="worker",
            deploy_type="process",
            port=41099,
            public_enabled=True,
        ),
    ]


def test_routes_from_session_empty_when_no_public_projects() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SessionLocal = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        session.add(
            Project(
                slug="private",
                name="Private",
                kind="web-deployable",
                local_path="/tmp/private",
                public_enabled=False,
            )
        )
        session.commit()
        routes = routes_from_session(session)
    engine.dispose()

    assert routes == []
