"""Core domain objects.

These are persistence- and transport-agnostic. API request/response models live in
``app.api.schemas`` and map to/from these types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.clock import utcnow
from app.domain.enums import (
    DocumentType,
    ReviewReason,
    ReviewStatus,
    ReviewTargetType,
    Severity,
    TextExtractionMethod,
    ValidationStatus,
    WorkflowStatus,
)

FieldValue = float | str | None


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# --------------------------------------------------------------------------- documents


class DocumentMetadata(DomainModel):
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int
    has_text_layer: bool
    pdf_producer: str | None = None
    pdf_title: str | None = None
    uploaded_at: datetime = Field(default_factory=utcnow)


class PageText(DomainModel):
    page_number: int  # 1-based
    text: str


class ExtractedText(DomainModel):
    pages: list[PageText]
    method: TextExtractionMethod
    warnings: list[str] = Field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(p.text.strip()) for p in self.pages)


class ClassificationResult(DomainModel):
    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_summary: str
    requires_review: bool
    provider: str
    model_name: str
    prompt_version: str
    is_mock: bool = False


class Document(DomainModel):
    document_id: str
    metadata: DocumentMetadata
    status: WorkflowStatus = WorkflowStatus.INGESTED
    document_type: DocumentType | None = None
    classification: ClassificationResult | None = None
    text_extraction_method: TextExtractionMethod | None = None
    char_count: int | None = None
    current_workflow_id: str | None = None
    security_flags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- extraction


class Evidence(DomainModel):
    page_number: int | None = None
    snippet: str
    verified: bool = False  # snippet located verbatim (whitespace-normalized) in source text


class ExtractedEntity(DomainModel):
    name: str
    value: FieldValue = None
    raw_text: str | None = None
    evidence: Evidence | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validation_status: ValidationStatus = ValidationStatus.MISSING
    messages: list[str] = Field(default_factory=list)
    alternatives: list[FieldValue] = Field(default_factory=list)


class ValidationIssue(DomainModel):
    rule: str
    severity: Severity
    message: str
    fields: list[str] = Field(default_factory=list)


class ExtractionResult(DomainModel):
    extraction_id: str
    document_id: str
    document_type: DocumentType
    entities: list[ExtractedEntity]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    requires_review: bool = False
    review_reasons: list[ReviewReason] = Field(default_factory=list)
    provider: str
    model_name: str
    prompt_version: str
    is_mock: bool = False
    corrected_by_review_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    def entity(self, name: str) -> ExtractedEntity | None:
        return next((e for e in self.entities if e.name == name), None)

    def value(self, name: str) -> FieldValue:
        ent = self.entity(name)
        return ent.value if ent else None


# --------------------------------------------------------------------------- retrieval / RAG


class Chunk(DomainModel):
    chunk_id: str
    document_id: str
    text: str
    page_number: int | None = None
    chunk_index: int
    start_char: int
    end_char: int
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class RetrievalResult(DomainModel):
    chunk: Chunk
    score: float
    rank: int


class Citation(DomainModel):
    document_id: str
    page_number: int | None
    chunk_id: str
    text_snippet: str
    retrieval_score: float


class GroundednessReport(DomainModel):
    score: float = Field(ge=0.0, le=1.0)
    total_sentences: int
    supported_sentences: int
    unsupported_sentences: list[str] = Field(default_factory=list)
    unsupported_numbers: list[str] = Field(default_factory=list)


class RAGAnswer(DomainModel):
    answer_id: str
    document_id: str | None
    question: str
    answer: str
    citations: list[Citation]
    confidence: float = Field(ge=0.0, le=1.0)
    groundedness: GroundednessReport | None = None
    requires_review: bool
    refused: bool = False
    refusal_reason: str | None = None
    review_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    retrieval_scores: list[float] = Field(default_factory=list)
    provider: str
    model_name: str
    prompt_version: str
    embedding_model: str
    is_mock: bool = False
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- HITL / audit


class ReviewCase(DomainModel):
    review_id: str
    document_id: str | None
    workflow_id: str | None = None
    target_type: ReviewTargetType
    target_id: str  # extraction_id or answer_id
    reasons: list[ReviewReason]
    details: list[str] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.PENDING
    original_output: dict[str, Any]
    corrected_output: dict[str, Any] | None = None
    reviewer_id: str | None = None
    reviewer_comment: str | None = None
    model_version: str
    prompt_version: str
    created_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None


class AuditEvent(DomainModel):
    event_id: str
    sequence: int = 0
    event_type: str
    actor: str  # "system" or "reviewer:<id>" / "api_key:<role>"
    document_id: str | None = None
    workflow_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=utcnow)
    prev_hash: str = ""
    event_hash: str = ""


# --------------------------------------------------------------------------- workflow


class WorkflowTransition(DomainModel):
    from_status: WorkflowStatus | None
    to_status: WorkflowStatus
    at: datetime = Field(default_factory=utcnow)
    reason: str | None = None


class WorkflowState(DomainModel):
    workflow_id: str
    document_id: str
    status: WorkflowStatus
    history: list[WorkflowTransition] = Field(default_factory=list)
    review_reasons: list[ReviewReason] = Field(default_factory=list)
    review_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


# --------------------------------------------------------------------------- operations


class ModelInvocation(DomainModel):
    invocation_id: str
    operation: str  # classification | extraction | rag_answer | judge | embedding
    provider: str
    model_name: str
    prompt_name: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    document_id: str | None = None
    workflow_id: str | None = None
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    tokens_estimated: bool = False
    estimated_cost_usd: float | None = None  # None: model missing from config/pricing.yaml
    retry_count: int = 0
    success: bool = True
    error_type: str | None = None
    is_mock: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class EvaluationResult(DomainModel):
    run_id: str
    created_at: datetime = Field(default_factory=utcnow)
    config: dict[str, Any]
    metrics: dict[str, dict[str, Any]]
    gate_passed: bool
    gate_failures: list[str] = Field(default_factory=list)
    duration_s: float
    is_mock: bool
