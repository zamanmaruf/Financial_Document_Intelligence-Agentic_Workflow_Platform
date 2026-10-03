"""Browser front ends served by the API.

* ``/ui`` is the static operator console (plain HTML/CSS/JS, no build step).
* ``/`` is the public demo site, a Vite build of ``web/`` served from ``settings.site_dir`` in
  demo mode when that build exists (the site needs the ``/demo`` routes). Otherwise ``/``
  redirects to the console.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The console only talks to this origin and never needs inline script or style elements.
UI_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}

# The demo site bundles its fonts and never loads third-party code. React sets inline styles
# through the CSSOM, which style-src 'self' does not block.
SITE_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}

# Client-side routes of the demo site (see web/src/main.tsx). Other unknown paths still get the
# app shell, so the site can render its own "not found" page, but with a 404 status.
SITE_ROUTES = frozenset({"", "tour", "try", "how-it-works"})

# First path segments owned by the API or the console; these never fall through to the site.
RESERVED_SEGMENTS = frozenset(
    {
        "ask",
        "audit",
        "demo",
        "docs",
        "documents",
        "drift",
        "evaluations",
        "health",
        "metrics",
        "openapi.json",
        "redoc",
        "reviews",
        "ui",
    }
)

_IMMUTABLE = "public, max-age=31536000, immutable"
_NO_CACHE = "no-cache"


def mount_ui(app: FastAPI) -> None:
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


def site_available(site_dir: Path | None) -> bool:
    return site_dir is not None and (site_dir / "index.html").is_file()


def is_site_path(path: str) -> bool:
    first = path.lstrip("/").split("/", 1)[0]
    return first not in RESERVED_SEGMENTS


def mount_root(app: FastAPI, site_dir: Path | None, *, ui_enabled: bool) -> None:
    """Serve the demo site at ``/`` if it is built, otherwise redirect ``/`` to the console."""
    if site_dir is None or not site_available(site_dir):
        if ui_enabled:

            @app.get("/", include_in_schema=False)
            def root() -> RedirectResponse:
                return RedirectResponse(url="/ui/")

        return

    root_dir = site_dir.resolve()
    index = root_dir / "index.html"
    # Only files present at startup are servable: no request path is ever joined onto the disk.
    top_level = {p.name: p for p in root_dir.iterdir() if p.is_file() and p.name != "index.html"}
    assets = root_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="site-assets")

    def shell(status: int = 200) -> FileResponse:
        return FileResponse(index, status_code=status, headers={"Cache-Control": _NO_CACHE})

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def site_index() -> FileResponse:
        return shell()

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def site_fallback(path: str, request: Request) -> Response:
        if not is_site_path(request.url.path):
            return JSONResponse(
                status_code=404, content={"error": {"type": "not_found", "message": "not found"}}
            )
        if path in top_level:
            return FileResponse(top_level[path], headers={"Cache-Control": _NO_CACHE})
        return shell(200 if path.strip("/") in SITE_ROUTES else 404)


def site_headers(path: str) -> dict[str, str]:
    """Extra response headers for browser-facing paths (empty for API routes)."""
    if path.startswith("/ui"):
        return UI_SECURITY_HEADERS
    if path.startswith("/assets/"):
        return {**SITE_SECURITY_HEADERS, "Cache-Control": _IMMUTABLE}
    if is_site_path(path):
        return SITE_SECURITY_HEADERS
    return {}
