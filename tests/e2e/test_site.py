"""The public demo site build is served at / with SPA fallback, without shadowing the API."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from tests.support import make_settings

INDEX = '<!doctype html><html><body><div id="root"></div></body></html>'
DEMO = {"demo_mode": True, "demo_secret": "s" * 40, "demo_cookie_secure": False}


@pytest.fixture
def site_dir(tmp_path: Path) -> Path:
    site = tmp_path / "dist"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text(INDEX)
    (site / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (site / "assets" / "index-abc123.js").write_text("console.log('ok')")
    (tmp_path / "secret.txt").write_text("outside the site")
    return site


@pytest.fixture
def client(tmp_path: Path, site_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(tmp_path, site_dir=site_dir, **DEMO))) as c:
        yield c


@pytest.mark.parametrize("path", ["/", "/tour", "/try", "/how-it-works"])
def test_client_routes_serve_the_app_shell(client: TestClient, path: str) -> None:
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 200
    assert r.text == INDEX
    assert r.headers["cache-control"] == "no-cache"
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"


def test_unknown_site_paths_get_the_shell_with_404(client: TestClient) -> None:
    r = client.get("/no-such-page")
    assert r.status_code == 404
    assert r.text == INDEX


def test_hashed_assets_are_cached_immutably(client: TestClient) -> None:
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]
    assert "content-security-policy" in r.headers


def test_top_level_files_are_served(client: TestClient) -> None:
    r = client.get("/favicon.svg")
    assert r.status_code == 200
    assert r.text.startswith("<svg")


@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"]
)
def test_paths_outside_the_site_are_not_served(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert "outside the site" not in r.text


def test_api_routes_are_not_shadowed(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in {"ok", "degraded"}
    assert "content-security-policy" not in r.headers


def test_unknown_api_paths_return_json_404(client: TestClient) -> None:
    r = client.get("/documents/does-not-exist/nothing-here")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_console_is_still_served(client: TestClient) -> None:
    assert client.get("/ui/").status_code == 200


def test_without_demo_mode_root_redirects_to_console(tmp_path: Path, site_dir: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, site_dir=site_dir))) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/ui/"


def test_without_a_build_root_redirects_to_console(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path, **DEMO))) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/ui/"
        assert c.get("/tour").status_code == 404
