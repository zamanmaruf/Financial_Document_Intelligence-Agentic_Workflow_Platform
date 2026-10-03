"""Health, metrics, drift and audit-verification endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import text

from app import __version__
from app.api.deps import Admin, ContainerDep, Operator
from app.api.schemas import AuditVerifyResponse, HealthResponse
from app.drift.monitor import DriftReport

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health(container: ContainerDep, response: Response) -> HealthResponse:
    """Liveness + dependency checks. Unauthenticated so load balancers can probe it.

    Returns 503 when a dependency is down so probes take the instance out of rotation.
    """
    try:
        with container.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("health check: database unavailable (%s)", type(exc).__name__)
        db_ok = False
    vs_ok = container.vector_store.healthcheck()
    if not (db_ok and vs_ok):
        response.status_code = 503
    s = container.settings
    return HealthResponse(
        status="ok" if db_ok and vs_ok else "degraded",
        version=__version__,
        mock_mode=container.llm.is_mock,
        providers={
            "llm": f"{container.llm.provider_name}:{container.llm.model_name}",
            "embeddings": f"{container.embedder.provider_name}:{container.embedder.model_name}",
            "vector_store": container.vector_store.name,
            "ocr": "available" if container.text_extraction.ocr_available else "unavailable",
            "ocr_provider_setting": s.ocr_provider.value,
        },
        checks={"database": db_ok, "vector_store": vs_ok},
    )


@router.get("/metrics", response_model=None)
def metrics(
    container: ContainerDep,
    _: Operator,
    format: Annotated[str, Query(pattern="^(json|prometheus)$")] = "json",
) -> Response | dict[str, Any]:
    """Operational metrics from the in-process registry (JSON or Prometheus text format)."""
    if format == "prometheus":
        return PlainTextResponse(
            container.metrics.prometheus_text(), media_type="text/plain; version=0.0.4"
        )
    snapshot = container.metrics.snapshot()
    snapshot["totals"] = {
        "documents": len(container.documents.all()),
        "model_invocations": container.invocations.count(),
        "indexed_chunks": container.vector_store.count(),
    }
    snapshot["mock_mode"] = container.llm.is_mock
    return snapshot


@router.get("/drift/report", response_model=DriftReport)
def drift_report(container: ContainerDep, _: Operator) -> DriftReport:
    """Compare current operational data against the stored drift baseline."""
    return container.drift.report(container.settings.drift_baseline_path)


@router.get("/audit/verify", response_model=AuditVerifyResponse)
def verify_audit_chain(container: ContainerDep, _: Admin) -> AuditVerifyResponse:
    """Recompute the audit hash chain to detect after-the-fact modification."""
    ok, broken = container.audit.verify_chain()
    return AuditVerifyResponse(valid=ok, first_broken_sequence=broken)
