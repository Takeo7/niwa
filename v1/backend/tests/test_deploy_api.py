"""HTTP tests for the deploy static handler (PR-V1-17).

The handler serves ``<project.local_path>/dist/`` for projects with
``kind == "web-deployable"`` under ``/api/deploy/{slug}/{path}``. These tests
exercise the five cases declared in the PR brief:

* index fallback for the root path,
* asset files under ``dist/assets/*``,
* 404 for unknown slugs,
* 404 for projects whose ``kind`` is not ``web-deployable``,
* 404 on path-traversal attempts without leaking existence outside ``dist/``.

The shared ``client`` fixture already wires an in-memory SQLite engine, so we
create projects via the standard ``POST /api/projects`` endpoint and write
the ``dist/`` tree to ``tmp_path`` so the handler can read it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _make_web_project(
    client, tmp_path: Path, *, slug: str = "site", kind: str = "web-deployable"
) -> Path:
    """Create a project with a ``dist/`` tree and return its local path."""

    local_path = tmp_path / slug
    dist = local_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>hello</body></html>")
    (dist / "assets" / "app.js").write_text("console.log('niwa');")
    (dist / "other.txt").write_text("plain")

    payload: dict[str, Any] = {
        "slug": slug,
        "name": slug.title(),
        "kind": kind,
        "local_path": str(local_path),
    }
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    return local_path


def test_serves_index_for_root_path(client, tmp_path: Path) -> None:
    _make_web_project(client, tmp_path)

    response = client.get("/api/deploy/site/")
    assert response.status_code == 200, response.text
    assert "hello" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_serves_asset_file(client, tmp_path: Path) -> None:
    _make_web_project(client, tmp_path)

    response = client.get("/api/deploy/site/assets/app.js")
    assert response.status_code == 200, response.text
    assert "console.log" in response.text


def test_404_on_missing_project(client, tmp_path: Path) -> None:
    response = client.get("/api/deploy/nope/anything.html")
    assert response.status_code == 404


def test_404_on_non_web_deployable_kind(client, tmp_path: Path) -> None:
    # Same ``dist/`` layout but ``kind=library`` — handler must refuse.
    _make_web_project(client, tmp_path, slug="lib", kind="library")

    response = client.get("/api/deploy/lib/index.html")
    assert response.status_code == 404


def test_404_on_path_traversal_attempt(client, tmp_path: Path) -> None:
    local_path = _make_web_project(client, tmp_path)
    # Create a sibling file OUTSIDE dist/ that the traversal would target.
    secret = local_path.parent / "secret.txt"
    secret.write_text("do not leak")

    # TestClient / httpx normalizes ``..`` in the URL, so send the encoded
    # form so FastAPI sees the raw segments and the handler's resolve-guard
    # is what actually rejects it.
    response = client.get("/api/deploy/site/%2E%2E/%2E%2E/secret.txt")
    assert response.status_code == 404
    assert "do not leak" not in response.text
