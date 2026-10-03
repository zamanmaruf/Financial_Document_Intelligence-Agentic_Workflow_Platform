"""Public demo endpoints: visitor sessions and demo status.

Mounted only when ``DOCINTEL_DEMO_MODE=true``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Request, Response, status
from pydantic import BaseModel

from app.api.deps import Analyst, ContainerDep
from app.api.routes.documents import ingest_for
from app.api.schemas import DocumentResponse, UploadResponse
from app.demo.limits import DAY_S, client_ip, documents_key, questions_key
from app.demo.samples import SAMPLES, DemoSample, get_sample, sample_bytes
from app.demo.sessions import COOKIE_NAME, issue_session, verify_session
from app.providers.llm.mock import MOCK_MODEL_NAME

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoLimits(BaseModel):
    documents_per_day: int
    questions_per_day: int
    max_upload_mb: float
    max_pages: int
    retention_hours: int


class DemoSessionResponse(BaseModel):
    active: bool
    created: bool
    ttl_hours: int


class DemoStatusResponse(BaseModel):
    ai_mode: Literal["live", "offline"]
    offline_reason: Literal["budget_reached", "configured_offline"] | None
    model_provider: str
    model_name: str
    session_active: bool
    documents_remaining: int | None
    questions_remaining: int | None
    limits: DemoLimits


class DemoSampleResponse(BaseModel):
    sample_id: str
    title: str
    document_kind: str
    summary: str
    expected_outcome: Literal["READY", "NEEDS_REVIEW"]
    lesson: str
    suggested_questions: list[str]

    @classmethod
    def from_sample(cls, s: DemoSample) -> DemoSampleResponse:
        return cls(
            sample_id=s.sample_id,
            title=s.title,
            document_kind=s.document_kind,
            summary=s.summary,
            expected_outcome="READY" if s.expected_outcome == "READY" else "NEEDS_REVIEW",
            lesson=s.lesson,
            suggested_questions=list(s.suggested_questions),
        )


def _secret(container: ContainerDep) -> str:
    assert container.settings.demo_secret is not None
    return container.settings.demo_secret.get_secret_value()


@router.post("/session", response_model=DemoSessionResponse)
def start_session(
    request: Request,
    response: Response,
    container: ContainerDep,
    demo_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> DemoSessionResponse:
    """Start (or keep) an anonymous visitor session bound to a private workspace."""
    s = container.settings
    ttl_s = s.demo_session_ttl_hours * 3600
    if verify_session(_secret(container), demo_cookie, ttl_s) is not None:
        return DemoSessionResponse(active=True, created=False, ttl_hours=s.demo_session_ttl_hours)
    ip = client_ip(request, s.demo_trusted_proxy_hops)
    container.limiter.hit(
        f"session:{ip}", s.demo_sessions_per_ip_hour, 3600, "new sessions per hour"
    )
    workspace_id, value = issue_session(_secret(container))
    response.set_cookie(
        COOKIE_NAME,
        value,
        max_age=ttl_s,
        httponly=True,
        secure=s.demo_cookie_secure,
        samesite="strict",
        path="/",
    )
    container.audit.record(
        "demo.session_started",
        actor=f"visitor:{workspace_id.removeprefix('ws_')[:12]}",
        details={"workspace_id": workspace_id},
    )
    return DemoSessionResponse(active=True, created=True, ttl_hours=s.demo_session_ttl_hours)


@router.get("/status", response_model=DemoStatusResponse)
def demo_status(
    container: ContainerDep,
    demo_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> DemoStatusResponse:
    """Which AI engine is answering right now, and the visitor's remaining allowance."""
    s = container.settings
    offline_reason: Literal["budget_reached", "configured_offline"] | None = None
    if container.llm.is_mock:
        offline_reason = "configured_offline"
    elif container.budget is not None and container.budget.exhausted():
        offline_reason = "budget_reached"
    workspace_id = verify_session(_secret(container), demo_cookie, s.demo_session_ttl_hours * 3600)
    docs_left = questions_left = None
    if workspace_id is not None:
        docs_left = container.limiter.remaining(
            documents_key(workspace_id), s.demo_docs_per_session_day, DAY_S
        )
        questions_left = container.limiter.remaining(
            questions_key(workspace_id), s.demo_questions_per_session_day, DAY_S
        )
    return DemoStatusResponse(
        ai_mode="offline" if offline_reason else "live",
        offline_reason=offline_reason,
        model_provider="mock" if offline_reason else container.llm.provider_name,
        model_name=MOCK_MODEL_NAME if offline_reason else container.llm.model_name,
        session_active=workspace_id is not None,
        documents_remaining=docs_left,
        questions_remaining=questions_left,
        limits=DemoLimits(
            documents_per_day=s.demo_docs_per_session_day,
            questions_per_day=s.demo_questions_per_session_day,
            max_upload_mb=s.max_upload_bytes / (1024 * 1024),
            max_pages=s.effective_max_pages,
            retention_hours=s.demo_retention_hours,
        ),
    )


@router.get("/samples", response_model=list[DemoSampleResponse])
def list_samples() -> list[DemoSampleResponse]:
    """Synthetic sample documents a visitor can load with one click."""
    return [DemoSampleResponse.from_sample(s) for s in SAMPLES]


@router.get("/samples/{sample_id}/file", response_class=Response)
def sample_file(sample_id: str, container: ContainerDep) -> Response:
    """The original sample PDF, for side-by-side viewing."""
    sample = get_sample(sample_id)
    return Response(
        sample_bytes(sample, container.settings.sample_data_dir),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{sample.filename}"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.post(
    "/samples/{sample_id}",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def load_sample(
    sample_id: str, container: ContainerDep, principal: Analyst
) -> UploadResponse:
    """Copy an allow-listed sample into the caller's workspace (same path as an upload)."""
    sample = get_sample(sample_id)
    data = sample_bytes(sample, container.settings.sample_data_dir)
    outcome = await ingest_for(container, principal, sample.filename, "application/pdf", data)
    return UploadResponse(
        document=DocumentResponse.from_domain(outcome.document), duplicate=outcome.duplicate
    )
