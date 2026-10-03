"""Human-in-the-loop review queue.

Cases are created with explicit reason codes by the workflow (document processing) and the RAG
service (answers). Reviewers approve, reject or correct. Every case keeps the original AI output,
the model and prompt versions that produced it, the reviewer decision and a timestamp; every
action is written to the audit trail.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import ValidationError

from app.audit.service import AuditService
from app.core.clock import new_id, utcnow
from app.core.errors import InvalidStateError
from app.domain.enums import (
    DocumentType,
    ReviewReason,
    ReviewStatus,
    ReviewTargetType,
    ValidationStatus,
    WorkflowStatus,
)
from app.domain.models import (
    DEFAULT_WORKSPACE,
    ExtractedEntity,
    ExtractionResult,
    FieldValue,
    ReviewCase,
    WorkflowState,
)
from app.extraction.schemas import SCHEMAS, field_specs
from app.extraction.service import coerce_field_value
from app.extraction.validation import validate_extraction, validate_field
from app.observability.logging import log_event
from app.observability.metrics import MetricsRecorder
from app.persistence.repositories import (
    DocumentRepository,
    DocumentTextRepository,
    ExtractionRepository,
    ReviewRepository,
)
from app.workflows.state_machine import WorkflowStateMachine

logger = logging.getLogger(__name__)


class ReviewInputError(InvalidStateError):
    error_type = "invalid_review_input"
    http_status = 422


class DocumentReprocessor(Protocol):
    def reprocess_with_type(
        self, document_id: str, document_type: DocumentType, actor: str
    ) -> WorkflowState: ...


class HumanReviewService:
    def __init__(
        self,
        reviews: ReviewRepository,
        documents: DocumentRepository,
        texts: DocumentTextRepository,
        extractions: ExtractionRepository,
        state_machine: WorkflowStateMachine,
        audit: AuditService,
        metrics: MetricsRecorder,
        tolerance_ratio: float,
    ) -> None:
        self._reviews = reviews
        self._documents = documents
        self._texts = texts
        self._extractions = extractions
        self._sm = state_machine
        self._audit = audit
        self._metrics = metrics
        self._tolerance = tolerance_ratio
        self._reprocessor: DocumentReprocessor | None = None

    def set_reprocessor(self, reprocessor: DocumentReprocessor) -> None:
        self._reprocessor = reprocessor

    # ------------------------------------------------------------------ queue

    def create_case(
        self,
        target_type: ReviewTargetType,
        target_id: str,
        reasons: list[ReviewReason],
        original_output: dict[str, Any],
        model_version: str,
        prompt_version: str,
        document_id: str | None = None,
        workflow_id: str | None = None,
        details: list[str] | None = None,
        workspace_id: str = DEFAULT_WORKSPACE,
    ) -> ReviewCase:
        case = ReviewCase(
            review_id=new_id("rev"),
            document_id=document_id,
            workflow_id=workflow_id,
            target_type=target_type,
            target_id=target_id,
            reasons=sorted(set(reasons), key=lambda r: r.value),
            details=details or [],
            original_output=original_output,
            model_version=model_version,
            prompt_version=prompt_version,
            workspace_id=workspace_id,
        )
        self._reviews.save(case)
        for reason in case.reasons:
            self._metrics.increment(
                "reviews_created_total",
                labels={"target": target_type.value, "reason": reason.value},
            )
        self._audit.record(
            "review.created",
            document_id=document_id,
            workflow_id=workflow_id,
            details={
                "review_id": case.review_id,
                "target_type": target_type.value,
                "target_id": target_id,
                "reasons": [r.value for r in case.reasons],
            },
        )
        log_event(
            logger,
            "review_created",
            review_id=case.review_id,
            review_required=True,
            reasons=[r.value for r in case.reasons],
            target_type=target_type.value,
        )
        return case

    def list(
        self,
        status: ReviewStatus | None = None,
        document_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
        workspace_id: str | None = None,
    ) -> list[ReviewCase]:
        return self._reviews.search(
            status=status,
            document_id=document_id,
            limit=limit,
            offset=offset,
            workspace_id=workspace_id,
        )

    def get(self, review_id: str) -> ReviewCase:
        return self._reviews.get(review_id)

    def supersede_pending_for_document(self, document_id: str, actor: str) -> int:
        pending = self._reviews.search(
            status=ReviewStatus.PENDING, document_id=document_id, limit=1000
        )
        count = 0
        for case in pending:
            if case.target_type != ReviewTargetType.DOCUMENT_PROCESSING:
                continue
            case.status = ReviewStatus.SUPERSEDED
            case.resolved_at = utcnow()
            case.reviewer_comment = "superseded by reprocessing"
            self._reviews.save(case)
            self._audit.record(
                "review.superseded",
                actor=actor,
                document_id=document_id,
                details={"review_id": case.review_id},
            )
            count += 1
        return count

    # ------------------------------------------------------------------ decisions

    def _pending(self, review_id: str) -> ReviewCase:
        case = self._reviews.get(review_id)
        if case.status != ReviewStatus.PENDING:
            raise InvalidStateError(f"review {review_id} is already {case.status.value}")
        return case

    def _finish(
        self,
        case: ReviewCase,
        status: ReviewStatus,
        reviewer_id: str,
        comment: str | None,
        action: str,
    ) -> ReviewCase:
        case.status = status
        case.reviewer_id = reviewer_id
        case.reviewer_comment = comment
        case.resolved_at = utcnow()
        self._reviews.save(case)
        self._metrics.increment("reviews_resolved_total", labels={"action": action})
        self._metrics.observe(
            "review_resolution_seconds", (case.resolved_at - case.created_at).total_seconds()
        )
        self._audit.record(
            f"review.{action}",
            actor=f"reviewer:{reviewer_id}",
            document_id=case.document_id,
            workflow_id=case.workflow_id,
            details={
                "review_id": case.review_id,
                "target_type": case.target_type.value,
                "comment": comment,
                "corrected_output": case.corrected_output,
            },
        )
        return case

    def _move_document(self, case: ReviewCase, target: WorkflowStatus, reviewer_id: str) -> None:
        if case.target_type != ReviewTargetType.DOCUMENT_PROCESSING or not case.document_id:
            return
        doc = self._documents.get(case.document_id)
        if doc.status == WorkflowStatus.NEEDS_REVIEW:
            self._sm.transition(
                doc, target, reason=f"review {case.review_id}", actor=f"reviewer:{reviewer_id}"
            )

    def approve(self, review_id: str, reviewer_id: str, comment: str | None = None) -> ReviewCase:
        case = self._pending(review_id)
        self._move_document(case, WorkflowStatus.READY, reviewer_id)
        return self._finish(case, ReviewStatus.APPROVED, reviewer_id, comment, "approved")

    def reject(self, review_id: str, reviewer_id: str, comment: str | None = None) -> ReviewCase:
        case = self._pending(review_id)
        self._move_document(case, WorkflowStatus.REJECTED, reviewer_id)
        return self._finish(case, ReviewStatus.REJECTED, reviewer_id, comment, "rejected")

    def correct(
        self,
        review_id: str,
        reviewer_id: str,
        corrections: dict[str, Any],
        comment: str | None = None,
    ) -> ReviewCase:
        case = self._pending(review_id)
        if not corrections:
            raise ReviewInputError("corrections must not be empty")

        if case.target_type == ReviewTargetType.ANSWER:
            answer = corrections.get("answer")
            if not isinstance(answer, str) or not answer.strip() or set(corrections) != {"answer"}:
                raise ReviewInputError("answer corrections must be {'answer': '<text>'}")
            case.corrected_output = {"answer": answer.strip()}
            return self._finish(case, ReviewStatus.CORRECTED, reviewer_id, comment, "corrected")

        if not case.document_id:
            raise ReviewInputError("review has no document")
        doc = self._documents.get(case.document_id)
        fields = dict(corrections)
        new_type_raw = fields.pop("document_type", None)
        new_type: DocumentType | None = None
        if new_type_raw is not None:
            try:
                new_type = DocumentType(str(new_type_raw))
            except ValueError as exc:
                raise ReviewInputError(f"unknown document_type '{new_type_raw}'") from exc
            if new_type == DocumentType.UNKNOWN:
                raise ReviewInputError("document_type correction must be a supported type")

        has_text = self._texts.get(doc.document_id) is not None
        type_changed = new_type is not None and new_type != doc.document_type
        if type_changed and has_text and not fields:
            # Re-run extraction/validation/indexing for the reviewer-supplied type.
            if self._reprocessor is None:
                raise InvalidStateError("reprocessing is not configured")
            assert new_type is not None
            case.corrected_output = {"document_type": new_type.value}
            self._finish(case, ReviewStatus.CORRECTED, reviewer_id, comment, "corrected")
            self._reprocessor.reprocess_with_type(
                doc.document_id, new_type, f"reviewer:{reviewer_id}"
            )
            return self._reviews.get(review_id)

        doc_type = new_type or doc.document_type
        if doc_type is None or doc_type not in SCHEMAS:
            raise ReviewInputError("a supported document_type is required to correct fields")
        extraction = self._apply_field_corrections(case, doc_type, fields, reviewer_id)
        if type_changed and new_type is not None:
            doc.document_type = new_type
            self._documents.update(doc)
        case.corrected_output = {
            "document_type": doc_type.value,
            "fields": {k: extraction.value(k) for k in fields},
            "extraction_id": extraction.extraction_id,
        }
        self._move_document(case, WorkflowStatus.READY, reviewer_id)
        return self._finish(case, ReviewStatus.CORRECTED, reviewer_id, comment, "corrected")

    def _apply_field_corrections(
        self, case: ReviewCase, doc_type: DocumentType, fields: dict[str, Any], reviewer_id: str
    ) -> ExtractionResult:
        specs = {s.name: s for s in field_specs(doc_type)}
        unknown = sorted(set(fields) - set(specs))
        if unknown:
            raise ReviewInputError(f"unknown fields for {doc_type.value}: {unknown}")

        schema = SCHEMAS[doc_type]
        coerced: dict[str, FieldValue] = {}
        for name, raw in fields.items():
            value = coerce_field_value(specs[name].kind, raw)
            try:
                coerced[name] = getattr(schema.model_validate({name: value}), name)
            except ValidationError as exc:
                raise ReviewInputError(f"invalid value for '{name}': {raw!r}") from exc
            problems = validate_field(
                ExtractedEntity(name=name, value=coerced[name]), specs[name].kind
            )
            if problems:
                raise ReviewInputError(f"invalid value for '{name}': {'; '.join(problems)}")

        assert case.document_id is not None
        base = self._extractions.get(case.target_id) or self._extractions.latest_for_document(
            case.document_id
        )
        if base is not None and base.document_type == doc_type:
            entities = [e.model_copy(deep=True) for e in base.entities]
        else:
            entities = [ExtractedEntity(name=s) for s in specs]

        corrected_names = set(coerced)
        for ent in entities:
            if ent.name in coerced:
                ent.value = coerced[ent.name]
                ent.confidence = 1.0
                ent.alternatives = []
                ent.messages = [f"corrected by reviewer {reviewer_id} (review {case.review_id})"]

        present = [e for e in entities if e.value is not None]
        result = ExtractionResult(
            extraction_id=new_id("ext"),
            document_id=case.document_id,
            document_type=doc_type,
            entities=entities,
            overall_confidence=round(sum(e.confidence for e in present) / len(present), 4)
            if present
            else 0.0,
            provider=base.provider if base else "human",
            model_name=base.model_name if base else "human",
            prompt_version=base.prompt_version if base else "n/a",
            is_mock=base.is_mock if base else False,
            corrected_by_review_id=case.review_id,
        )
        issues = validate_extraction(result, self._tolerance)
        # reviewer-supplied values need no source evidence
        result.validation_issues = [
            i
            for i in issues
            if not (i.rule == "evidence_not_found" and set(i.fields) <= corrected_names)
        ]
        for ent in result.entities:
            if ent.name in corrected_names:
                ent.validation_status = ValidationStatus.CORRECTED
        self._extractions.save(result)
        return result
