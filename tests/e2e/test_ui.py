"""The static operator console: served at /ui with a strict CSP, and safe by construction."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.web import STATIC_DIR
from tests.support import make_settings


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(tmp_path))) as c:
        yield c


def test_root_redirects_to_console(client: TestClient) -> None:
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/ui/"


@pytest.mark.parametrize("path", ["/ui/", "/ui/app.js", "/ui/styles.css"])
def test_console_assets_are_served_with_security_headers(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"


def test_api_responses_do_not_get_ui_headers(client: TestClient) -> None:
    assert "content-security-policy" not in client.get("/health").headers


def test_console_can_be_disabled(tmp_path: Path) -> None:
    settings = make_settings(tmp_path).model_copy(update={"ui_enabled": False})
    with TestClient(create_app(settings)) as c:
        assert c.get("/ui/").status_code == 404
        assert c.get("/", follow_redirects=False).status_code == 404


def test_console_never_renders_server_data_as_html() -> None:
    """Document text is untrusted (it may carry injected markup); the UI must use textContent."""
    js = (STATIC_DIR / "app.js").read_text()
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", js)


def test_console_loads_no_third_party_resources() -> None:
    for name in ("index.html", "app.js", "styles.css"):
        text = (STATIC_DIR / name).read_text()
        assert not re.search(r"https?://", text), f"{name} references an external URL"
