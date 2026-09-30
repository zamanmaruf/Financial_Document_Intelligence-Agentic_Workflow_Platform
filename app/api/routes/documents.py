"""Document upload, processing, extraction results, Q&A and audit history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile, status

from app.api.deps import Analyst, ContainerDep, Viewer
from app.api.schemas import (
    AskRequest,
    AskResponse,
    AuditResponse,
    DocumentResponse,
    ExtractionsResponse,
    ProcessResponse,
    UploadResponse,
)
from app.core.errors import InvalidDocumentError

router = APIRouter(tags=["documents"])


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
    outcome = container.ingestion.upload(file.filename, file.content_type, data, principal.actor)
    return UploadResponse(
        document=DocumentResponse.from_domain(outcome.document), duplicate=outcome.duplicate
    )


@router.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    container: ContainerDep,
    _: Viewer,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DocumentResponse]:
    return [DocumentResponse.from_domain(d) for d in container.documents.list_page(limit, offset)]


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: str, container: ContainerDep, _: Viewer) -> DocumentResponse:
    return DocumentResponse.from_domain(container.documents.get(document_id))


@router.post("/documents/{document_id}/process", response_model=ProcessResponse)
def process_document(
    document_id: str, container: ContainerDep, principal: Analyst
) -> ProcessResponse:
    """Run (or re-run) the deterministic processing workflow synchronously."""
    state = container.workflow.process(document_id, principal.actor)
    return ProcessResponse.from_domain(state, container.documents.get(document_id))


@router.get("/documents/{document_id}/extractions", response_model=ExtractionsResponse)
def get_extractions(document_id: str, container: ContainerDep, _: Viewer) -> ExtractionsResponse:
    container.documents.get(document_id)
    history = container.extractions.list_for_document(document_id)
    return ExtractionsResponse(
        document_id=document_id, latest=history[0] if history else None, history=history
    )


@router.post("/documents/{document_id}/ask", response_model=AskResponse)
def ask_document(
    document_id: str, body: AskRequest, container: ContainerDep, principal: Viewer
) -> AskResponse:
    answer = container.rag.ask(
        body.question,
        document_id=document_id,
        filters=body.filters,
        top_k=body.top_k,
        actor=principal.actor,
    )
    return AskResponse.from_domain(answer)


@router.post("/ask", response_model=AskResponse)
def ask_corpus(body: AskRequest, container: ContainerDep, principal: Viewer) -> AskResponse:
    """Question across all indexed documents (optionally metadata-filtered)."""
    answer = container.rag.ask(
        body.question,
        document_id=None,
        filters=body.filters,
        top_k=body.top_k,
        actor=principal.actor,
    )
    return AskResponse.from_domain(answer)


@router.get("/documents/{document_id}/audit", response_model=AuditResponse)
def get_audit(document_id: str, container: ContainerDep, _: Viewer) -> AuditResponse:
    container.documents.get(document_id)
    return AuditResponse(
        document_id=document_id, events=container.audit.history(document_id=document_id)
    )
