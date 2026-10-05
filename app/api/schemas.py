"""HTTP request/response models (kept separate from domain models)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import (
    DocumentType,
    ReviewReason,
    ReviewStatus,
    ReviewTargetType,
    TextExtractionMethod,
    WorkflowStatus,
)
from app.domain.models import (
    AuditEvent,
    Citation,
    ClassificationResult,
    Document,
    ExtractionResult,
    RAGAnswer,
    ReviewCase,
    WorkflowState,
    WorkflowTransition,
)

ALLOWED_FILTER_KEYS = frozenset({"document_type", "extraction_method"})


class ErrorBody(BaseModel):
    type: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
    request_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    mock_mode: bool
    providers: dict[str, str]
    checks: dict[str, bool]


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    status: WorkflowStatus
    document_type: DocumentType | None
    classification: ClassificationResult | None
    page_count: int
    size_bytes: int
    sha256: str
    has_text_layer: bool
    text_extraction_method: TextExtractionMethod | None
    char_count: int | None
    security_flags: list[str]
    current_workflow_id: str | None
    created_at: datetime
    updated_at: datetime
    processing: bool = Field(
        default=False, description="True while a background processing run is active"
    )

    @classmethod
    def from_domain(cls, doc: Document, processing: bool = False) -> DocumentResponse:
        return cls(
            document_id=doc.document_id,
            filename=doc.metadata.filename,
            status=doc.status,
            document_type=doc.document_type,
            classification=doc.classification,
            page_count=doc.metadata.page_count,
            size_bytes=doc.metadata.size_bytes,
            sha256=doc.metadata.sha256,
            has_text_layer=doc.metadata.has_text_layer,
            text_extraction_method=doc.text_extraction_method,
            char_count=doc.char_count,
            security_flags=doc.security_flags,
            current_workflow_id=doc.current_workflow_id,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
            processing=processing,
        )


class UploadResponse(BaseModel):
    document: DocumentResponse
    duplicate: bool


class ProcessResponse(BaseModel):
    workflow_id: str
    document_id: str
    status: WorkflowStatus
    review_id: str | None
    review_reasons: list[ReviewReason]
    error_type: str | None
    error_message: str | None
    history: list[WorkflowTransition]
    document: DocumentResponse

    @classmethod
    def from_domain(cls, state: WorkflowState, doc: Document) -> ProcessResponse:
        return cls(
            workflow_id=state.workflow_id,
            document_id=state.document_id,
            status=state.status,
            review_id=state.review_id,
            review_reasons=state.review_reasons,
            error_type=state.error_type,
            error_message=state.error_message,
            history=state.history,
            document=DocumentResponse.from_domain(doc),
        )


class ExtractionsResponse(BaseModel):
    document_id: str
    latest: ExtractionResult | None
    history: list[ExtractionResult]


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    filters: dict[str, str] | None = Field(
        default=None, description=f"Equality filters; allowed keys: {sorted(ALLOWED_FILTER_KEYS)}"
    )

    @field_validator("filters")
    @classmethod
    def _allowed_keys(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v:
            bad = set(v) - ALLOWED_FILTER_KEYS
            if bad:
                raise ValueError(f"unsupported filter keys: {sorted(bad)}")
        return v


class LocateQueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    page: int | None = Field(
        default=None, ge=1, description="1-based page to search; omit to search every page"
    )


class LocateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[LocateQueryBody] = Field(min_length=1, max_length=50)


class HighlightRect(BaseModel):
    """Page-relative box: (0, 0) is the top-left corner and 1 spans the full page edge."""

    x: float
    y: float
    width: float
    height: float


class LocateMatch(BaseModel):
    page_number: int
    rects: list[HighlightRect]


class LocateResult(BaseModel):
    text: str
    page: int | None
    matches: list[LocateMatch]


class LocateResponse(BaseModel):
    document_id: str
    has_text_layer: bool = Field(
        description="False for scanned documents, which have no text positions to highlight"
    )
    results: list[LocateResult]


class AskResponse(BaseModel):
    answer_id: str
    document_id: str | None
    answer: str
    citations: list[Citation]
    confidence: float
    groundedness: float | None
    requires_review: bool
    review_id: str | None
    refused: bool
    refusal_reason: str | None
    warnings: list[str]
    retrieval_scores: list[float]
    model_provider: str
    model_name: str
    prompt_version: str
    embedding_model: str
    is_mock: bool

    @classmethod
    def from_domain(cls, a: RAGAnswer) -> AskResponse:
        return cls(
            answer_id=a.answer_id,
            document_id=a.document_id,
            answer=a.answer,
            citations=a.citations,
            confidence=a.confidence,
            groundedness=a.groundedness.score if a.groundedness else None,
            requires_review=a.requires_review,
            review_id=a.review_id,
            refused=a.refused,
            refusal_reason=a.refusal_reason,
            warnings=a.warnings,
            retrieval_scores=a.retrieval_scores,
            model_provider=a.provider,
            model_name=a.model_name,
            prompt_version=a.prompt_version,
            embedding_model=a.embedding_model,
            is_mock=a.is_mock,
        )


class ReviewResponse(BaseModel):
    review_id: str
    document_id: str | None
    target_type: ReviewTargetType
    target_id: str
    status: ReviewStatus
    reasons: list[ReviewReason]
    details: list[str]
    original_output: dict[str, Any]
    corrected_output: dict[str, Any] | None
    reviewer_id: str | None
    reviewer_comment: str | None
    model_version: str
    prompt_version: str
    created_at: datetime
    resolved_at: datetime | None

    @classmethod
    def from_domain(cls, r: ReviewCase) -> ReviewResponse:
        return cls(**r.model_dump(exclude={"workflow_id", "workspace_id"}))


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    count: int


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_id: str | None = Field(
        default=None,
        max_length=100,
        description="Placeholder reviewer identity; ignored when API-key auth is enabled.",
    )
    comment: str | None = Field(default=None, max_length=2000)


class ReviewCorrectionRequest(ReviewDecisionRequest):
    corrections: dict[str, Any] = Field(
        description="Field name -> corrected value; may include 'document_type'. For answer "
        "reviews use {'answer': '<text>'}."
    )


class AuditResponse(BaseModel):
    document_id: str
    events: list[AuditEvent]


class AuditVerifyResponse(BaseModel):
    valid: bool
    first_broken_sequence: int | None


class DocumentAuditVerifyResponse(AuditVerifyResponse):
    checked_events: int
