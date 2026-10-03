"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api.routes import demo, documents, evaluations, reviews, system
from app.core.config import Settings, get_settings
from app.core.errors import DocIntelError, RateLimitedError
from app.demo.limits import client_ip
from app.demo.retention import PURGE_INTERVAL_S, purge_expired
from app.observability.logging import configure_logging, log_event, request_id_var
from app.services.container import Container, build_container
from app.web import mount_root, mount_ui, site_headers

logger = logging.getLogger("app.api")

# Paths that do work on behalf of a caller; static assets and health probes are not limited.
_RATE_LIMITED_PREFIXES = ("/documents", "/ask", "/reviews", "/demo")


async def _retention_loop(container: Container) -> None:
    while True:
        try:
            await run_in_threadpool(purge_expired, container)
        except Exception:
            logger.exception("demo retention purge failed")
        await asyncio.sleep(PURGE_INTERVAL_S)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"type": error_type, "message": message},
            "request_id": request_id_var.get(),
        },
    )


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or (container.settings if container else get_settings())
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        c: Container = app.state.container
        log_event(
            logger,
            "startup",
            version=__version__,
            mock_mode=c.llm.is_mock,
            **settings.public_summary(),
        )
        retention = asyncio.create_task(_retention_loop(c)) if settings.demo_mode else None
        try:
            yield
        finally:
            if retention is not None:
                retention.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await retention
            c.close()

    app = FastAPI(
        title="Financial Document Intelligence API",
        version=__version__,
        description="Ingestion, classification, extraction, validation, grounded Q&A with "
        "citations, human review, audit and evaluation for financial documents.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = (
            incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex
        )
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            limited = _check_request_rate(request)
            response = limited if limited is not None else await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers.update(site_headers(request.url.path))
            return response
        finally:
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            c = getattr(request.app.state, "container", None)
            if c is not None:
                labels = {"method": request.method, "route": path, "status": str(status_code)}
                c.metrics.increment("http_requests_total", labels=labels)
                c.metrics.observe("http_latency_ms", elapsed, {"route": path})
            log_event(
                logger,
                "http_request",
                method=request.method,
                route=path,
                status=status_code,
                latency_ms=elapsed,
            )
            request_id_var.reset(token)

    def _check_request_rate(request: Request) -> Response | None:
        if not settings.demo_mode or not request.url.path.startswith(_RATE_LIMITED_PREFIXES):
            return None
        c: Container | None = getattr(request.app.state, "container", None)
        if c is None:
            return None
        ip = client_ip(request, settings.demo_trusted_proxy_hops)
        try:
            c.limiter.hit(
                f"req:{ip}", settings.demo_requests_per_ip_minute, 60, "requests per minute"
            )
        except RateLimitedError as exc:
            response = _error(exc.http_status, exc.error_type, exc.message)
            response.headers["Retry-After"] = str(exc.retry_after_s)
            return response
        return None

    @app.exception_handler(DocIntelError)
    async def domain_error(_: Request, exc: DocIntelError) -> JSONResponse:
        level = logging.WARNING if exc.http_status < 500 else logging.ERROR
        log_event(logger, "request_error", level, error_type=exc.error_type, status=exc.http_status)
        response = _error(exc.http_status, exc.error_type, exc.message)
        if isinstance(exc, RateLimitedError):
            response.headers["Retry-After"] = str(exc.retry_after_s)
        return response

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"fields": {"error_type": type(exc).__name__}})
        return _error(500, "internal_error", "an unexpected error occurred")

    app.include_router(system.router)
    app.include_router(documents.router)
    app.include_router(reviews.router)
    app.include_router(evaluations.router)
    if settings.demo_mode:
        app.include_router(demo.router)
    if settings.ui_enabled:
        mount_ui(app)
    # Registered last: the site's catch-all route must never shadow an API route.
    mount_root(
        app, settings.site_dir if settings.demo_mode else None, ui_enabled=settings.ui_enabled
    )
    return app


app = create_app()
