"""Document upload, processing, extraction results, Q&A and audit history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import (
    Analyst,
    ContainerDep,
    Principal,
    Viewer,
    charge_visitor,
    owned_document,
    require_allowance,
    workspace_for,
)
from app.api.schemas import (
    AskRequest,
    AskResponse,
    AuditResponse,
    DocumentAuditVerifyResponse,
    DocumentResponse,
    ExtractionsResponse,
    ProcessResponse,
    UploadResponse,
)
from app.core.errors import InvalidDocumentError, InvalidStateError
from app.core.hashing import sha256_bytes
from app.ingestion.service import UploadOutcome
from app.services.container import Container
from app.workflows.state_machine import IN_PROGRESS

router = APIRouter(tags=["documents"])


async def ingest_for(
    container: Container,
    principal: Principal,
    filename: str | None,
    content_type: str | None,
    data: bytes,
) -> UploadOutcome:
    """Upload into the caller's workspace, charging a demo visitor only for new documents."""
    workspace = workspace_for(principal)
    if container.documents.find_by_sha256(sha256_bytes(data), workspace) is None:
        require_allowance(container, principal, "documents")
    # PDF inspection, hashing and the database write are blocking; keep them off the event loop.
    outcome = await run_in_threadpool(
        container.ingestion.upload, filename, content_type, data, principal.actor, workspace
    )
    if not outcome.duplicate:
        charge_visitor(container, principal, "documents")
    return outcome


@router.post(
    "/documents/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_document(
    container: ContainerDep,
    principal: Analyst,
    file: Annotated[UploadFile, File(description="PDF document")],
) -> UploadResponse:
    limit = container.settings.max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise InvalidDocumentError(
            f"file exceeds maximum upload size of {limit / (1024 * 1024):g} MB"
        )
    outcome = await ingest_for(container, principal, file.filename, file.content_type, data)
    return UploadResponse(
        document=DocumentResponse.from_domain(outcome.document), duplicate=outcome.duplicate
    )


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    container: ContainerDep,
    principal: Viewer,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentResponse]:
    docs = container.documents.list_page(limit, offset, workspace_id=principal.workspace_id)
    return [
        DocumentResponse.from_domain(d, processing=container.jobs.is_running(d.document_id))
        for d in docs
    ]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, container: ContainerDep, principal: Viewer) -> DocumentResponse:
    doc = owned_document(container, principal, document_id)
    return DocumentResponse.from_domain(doc, processing=container.jobs.is_running(document_id))


@router.post("/documents/{document_id}/process", response_model=ProcessResponse)
def process_document(
    document_id: str, container: ContainerDep, principal: Analyst
) -> ProcessResponse:
    """Run (or re-run) the deterministic processing workflow synchronously."""
    owned_document(container, principal, document_id)
    if container.jobs.is_running(document_id):
        raise InvalidStateError(f"document {document_id} is already being processed")
    charge_visitor(container, principal, "runs")
    state = container.workflow.process(document_id, principal.actor)
    return ProcessResponse.from_domain(state, container.documents.get(document_id))


@router.post(
    "/documents/{document_id}/process/background",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def process_document_background(
    document_id: str, container: ContainerDep, principal: Analyst
) -> DocumentResponse:
    """Start processing in a background worker and return immediately.

    Poll ``GET /documents/{id}``: ``status`` advances through each workflow step and
    ``processing`` turns false when the run has finished.
    """
    doc = owned_document(container, principal, document_id)
    if doc.status in IN_PROGRESS:
        raise InvalidStateError(f"document {document_id} is already being processed")
    charge_visitor(container, principal, "runs")
    actor = principal.actor
    container.jobs.submit(document_id, lambda: container.workflow.process(document_id, actor))
    return DocumentResponse.from_domain(doc, processing=True)


@router.get("/documents/{document_id}/extractions", response_model=ExtractionsResponse)
def get_extractions(
    document_id: str, container: ContainerDep, principal: Viewer
) -> ExtractionsResponse:
    owned_document(container, principal, document_id)
    history = container.extractions.list_for_document(document_id)
    return ExtractionsResponse(
        document_id=document_id, latest=history[0] if history else None, history=history
    )


@router.post("/documents/{document_id}/ask", response_model=AskResponse)
def ask_document(
    document_id: str, body: AskRequest, container: ContainerDep, principal: Viewer
) -> AskResponse:
    owned_document(container, principal, document_id)
    charge_visitor(container, principal, "questions")
    answer = container.rag.ask(
        body.question,
        document_id=document_id,
        filters=body.filters,
        top_k=body.top_k,
        actor=principal.actor,
        workspace_id=principal.workspace_id,
    )
    return AskResponse.from_domain(answer)


@router.post("/ask", response_model=AskResponse)
def ask_corpus(body: AskRequest, container: ContainerDep, principal: Viewer) -> AskResponse:
    """Question across all indexed documents (optionally metadata-filtered).

    Demo visitors only search their own workspace.
    """
    charge_visitor(container, principal, "questions")
    answer = container.rag.ask(
        body.question,
        document_id=None,
        filters=body.filters,
        top_k=body.top_k,
        actor=principal.actor,
        workspace_id=principal.workspace_id,
    )
    return AskResponse.from_domain(answer)


@router.get("/documents/{document_id}/audit", response_model=AuditResponse)
def get_audit(document_id: str, container: ContainerDep, principal: Viewer) -> AuditResponse:
    owned_document(container, principal, document_id)
    return AuditResponse(
        document_id=document_id, events=container.audit.history(document_id=document_id)
    )


@router.get("/documents/{document_id}/audit/verify", response_model=DocumentAuditVerifyResponse)
def verify_document_audit(
    document_id: str, container: ContainerDep, principal: Viewer
) -> DocumentAuditVerifyResponse:
    """Tamper check for this document's audit events: each hash must match its content."""
    owned_document(container, principal, document_id)
    events = container.audit.history(document_id=document_id)
    ok, broken = container.audit.verify_events(events)
    return DocumentAuditVerifyResponse(
        valid=ok, first_broken_sequence=broken, checked_events=len(events)
    )
