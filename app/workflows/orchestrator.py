"""Deterministic document-processing workflow.

INGESTED -> TEXT_EXTRACTED -> CLASSIFIED -> ENTITIES_EXTRACTED -> VALIDATED -> INDEXED
         -> READY | NEEDS_REVIEW          (FAILED on unrecoverable errors)

Decision points (all explicit, all audited):
  * OCR needed?                 native text layer too sparse -> OCR engine, else review
  * document safe?              injection patterns in document text -> flag + review
  * classification trustworthy? confidence < threshold or unknown -> review
  * extraction trustworthy?     low confidence / schema failure / conflicts / rule failure /
                                missing required / unverifiable evidence -> review
  * model failing?              provider errors after bounded retries -> review
  * indexing failed?            vector store error -> FAILED (retry via reprocess)

The pipeline continues past soft failures so a reviewer sees the complete picture in a single
review case, rather than one case per step.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.audit.service import SYSTEM_ACTOR, AuditService
from app.classification.service import DocumentClassifier
from app.core.clock import new_id, utcnow
from app.core.errors import (
    DocIntelError,
    EmptyDocumentError,
    InvalidDocumentError,
    InvalidStateError,
    OCRUnavailableError,
    ProviderError,
    VectorStoreError,
)
from app.domain.enums import (
    DocumentType,
    ReviewReason,
    ReviewTargetType,
    TextExtractionMethod,
    WorkflowStatus,
)
from app.domain.models import (
    ClassificationResult,
    Document,
    ExtractedText,
    ExtractionResult,
    WorkflowState,
)
from app.extraction.service import EntityExtractor
from app.guardrails.injection import scan_for_injection
from app.human_review.service import HumanReviewService
from app.ingestion.extractors import TextExtractionService
from app.observability.logging import document_id_var, log_event, workflow_id_var
from app.observability.metrics import MetricsRecorder
from app.persistence.repositories import (
    DocumentRepository,
    DocumentTextRepository,
    ExtractionRepository,
)
from app.providers.storage.local import DocumentStore
from app.retrieval.chunking import Chunker
from app.retrieval.indexer import Indexer
from app.workflows.state_machine import IN_PROGRESS, WorkflowStateMachine, can_transition

logger = logging.getLogger(__name__)


class DocumentWorkflow:
    def __init__(
        self,
        documents: DocumentRepository,
        texts: DocumentTextRepository,
        extractions: ExtractionRepository,
        store: DocumentStore,
        state_machine: WorkflowStateMachine,
        text_extraction: TextExtractionService,
        classifier: DocumentClassifier,
        extractor: EntityExtractor,
        chunker: Chunker,
        indexer: Indexer,
        reviews: HumanReviewService,
        audit: AuditService,
        metrics: MetricsRecorder,
        review_ocr_documents: bool = True,
    ) -> None:
        self._documents = documents
        self._texts = texts
        self._extractions = extractions
        self._store = store
        self._sm = state_machine
        self._text_extraction = text_extraction
        self._classifier = classifier
        self._extractor = extractor
        self._chunker = chunker
        self._indexer = indexer
        self._reviews = reviews
        self._audit = audit
        self._metrics = metrics
        self._review_ocr_documents = review_ocr_documents

    # ------------------------------------------------------------------ entry points

    def process(self, document_id: str, actor: str = SYSTEM_ACTOR) -> WorkflowState:
        return self._run(document_id, actor, forced_type=None)

    def reprocess_with_type(
        self, document_id: str, document_type: DocumentType, actor: str
    ) -> WorkflowState:
        return self._run(document_id, actor, forced_type=document_type)

    # ------------------------------------------------------------------ pipeline

    def _start(self, document_id: str, actor: str) -> tuple[Document, WorkflowState]:
        doc = self._documents.get(document_id)
        if doc.status in IN_PROGRESS:
            raise InvalidStateError(
                f"document {document_id} is already being processed ({doc.status.value})"
            )
        state = WorkflowState(workflow_id=new_id("wf"), document_id=document_id, status=doc.status)
        if doc.status != WorkflowStatus.INGESTED:
            self._reviews.supersede_pending_for_document(document_id, actor)
            doc = self._sm.transition(
                doc, WorkflowStatus.INGESTED, "reprocess requested", state, actor
            )
        doc.current_workflow_id = state.workflow_id
        doc.security_flags = [f for f in doc.security_flags if f == "pdf_active_content"]
        self._documents.update(doc)
        self._audit.record(
            "workflow.started", actor=actor, document_id=document_id, workflow_id=state.workflow_id
        )
        return doc, state

    def _run(self, document_id: str, actor: str, forced_type: DocumentType | None) -> WorkflowState:
        started = time.perf_counter()
        doc, state = self._start(document_id, actor)
        doc_token = document_id_var.set(document_id)
        wf_token = workflow_id_var.set(state.workflow_id)
        reasons: list[ReviewReason] = []
        details: list[str] = []
        classification: ClassificationResult | None = None
        extraction: ExtractionResult | None = None
        try:
            # 1. text extraction (+ OCR decision)
            try:
                text = self._text_extraction.extract(self._store.load(document_id))
            except OCRUnavailableError as exc:
                reasons.append(ReviewReason.OCR_UNAVAILABLE)
                details.append(exc.message)
                return self._finish_review_early(doc, state, reasons, details, started)
            except (EmptyDocumentError, InvalidDocumentError) as exc:
                return self._fail(doc, state, exc, started)
            except ProviderError as exc:  # OCR provider failure
                return self._fail(doc, state, exc, started)

            self._texts.save(document_id, text)
            if text.warnings:
                details.extend(text.warnings)
                log_event(
                    logger, "text_extraction_warnings", logging.WARNING, warnings=text.warnings
                )
            doc.text_extraction_method = text.method
            doc.char_count = text.char_count
            if text.method != TextExtractionMethod.NATIVE_PDF and self._review_ocr_documents:
                reasons.append(ReviewReason.OCR_USED)
            self._check_document_injection(doc, text, reasons, details, state)
            doc = self._sm.transition(
                doc,
                WorkflowStatus.TEXT_EXTRACTED,
                f"{text.method.value}: {len(text.pages)} pages, {text.char_count} chars",
                state,
            )

            # 2. classification
            if forced_type is not None:
                classification = ClassificationResult(
                    document_type=forced_type,
                    confidence=1.0,
                    reasoning_summary="Document type set by human reviewer.",
                    requires_review=False,
                    provider="human",
                    model_name="human",
                    prompt_version="n/a",
                )
            else:
                classification = self._classify(doc, text, state, reasons, details)
            doc.classification = classification
            doc.document_type = classification.document_type
            doc = self._sm.transition(
                doc,
                WorkflowStatus.CLASSIFIED,
                f"{classification.document_type.value} ({classification.confidence:.2f})",
                state,
            )

            # 3. entity extraction
            extraction = self._extract(doc, text, state, reasons, details)
            doc = self._sm.transition(
                doc,
                WorkflowStatus.ENTITIES_EXTRACTED,
                f"{len(extraction.entities)} fields" if extraction else "skipped",
                state,
            )

            # 4. validation (rules already applied by the extractor; record the outcome)
            n_issues = len(extraction.validation_issues) if extraction else 0
            doc = self._sm.transition(doc, WorkflowStatus.VALIDATED, f"{n_issues} issues", state)

            # 5. chunk + index
            try:
                chunks = self._chunker.chunk(
                    document_id, text, doc.document_type, workspace_id=doc.workspace_id
                )
                n_chunks = self._indexer.index(document_id, chunks)
            except (VectorStoreError, ProviderError) as exc:
                return self._fail(doc, state, exc, started)
            doc = self._sm.transition(doc, WorkflowStatus.INDEXED, f"{n_chunks} chunks", state)

            # 6. decision
            if reasons:
                self._open_review(doc, state, reasons, details, classification, extraction)
                doc = self._sm.transition(
                    doc,
                    WorkflowStatus.NEEDS_REVIEW,
                    ", ".join(sorted({r.value for r in reasons})),
                    state,
                )
            else:
                doc = self._sm.transition(doc, WorkflowStatus.READY, "all checks passed", state)
            return self._complete(state, started, reasons)
        except DocIntelError as exc:
            return self._fail(doc, state, exc, started)
        except Exception as exc:
            logger.exception("unexpected workflow error")
            self._fail(doc, state, exc, started)
            raise
        finally:
            document_id_var.reset(doc_token)
            workflow_id_var.reset(wf_token)

    # ------------------------------------------------------------------ steps

    def _check_document_injection(
        self,
        doc: Document,
        text: ExtractedText,
        reasons: list[ReviewReason],
        details: list[str],
        state: WorkflowState,
    ) -> None:
        scan = scan_for_injection(text.full_text)
        if not scan.flagged:
            return
        doc.security_flags = sorted({*doc.security_flags, "prompt_injection_suspected"})
        reasons.append(ReviewReason.GUARDRAIL_TRIGGERED)
        details.append(f"suspicious instructions in document text: {', '.join(scan.patterns)}")
        self._metrics.increment(
            "guardrail_triggers_total", labels={"guardrail": "document_injection"}
        )
        self._audit.record(
            "guardrail.document_injection_suspected",
            document_id=doc.document_id,
            workflow_id=state.workflow_id,
            details={"patterns": scan.patterns, "examples": [m.snippet for m in scan.matches[:3]]},
        )

    def _classify(
        self,
        doc: Document,
        text: ExtractedText,
        state: WorkflowState,
        reasons: list[ReviewReason],
        details: list[str],
    ) -> ClassificationResult:
        try:
            classification, _ = self._classifier.classify(
                text.full_text, doc.document_id, state.workflow_id
            )
        except ProviderError as exc:
            reasons.append(ReviewReason.RETRIES_EXHAUSTED)
            details.append(f"classification failed: {exc.message}")
            return ClassificationResult(
                document_type=DocumentType.UNKNOWN,
                confidence=0.0,
                reasoning_summary="Classification unavailable (model call failed).",
                requires_review=True,
                provider="n/a",
                model_name="n/a",
                prompt_version="n/a",
            )
        self._metrics.increment(
            "documents_classified_total",
            labels={"document_type": classification.document_type.value},
        )
        self._metrics.observe("classification_confidence", classification.confidence)
        if classification.document_type == DocumentType.UNKNOWN:
            reasons.append(ReviewReason.UNKNOWN_DOCUMENT_TYPE)
            details.append("document type could not be determined")
        elif classification.requires_review:
            reasons.append(ReviewReason.LOW_CLASSIFICATION_CONFIDENCE)
            details.append(
                f"classification confidence {classification.confidence:.2f} below threshold"
            )
        return classification

    def _extract(
        self,
        doc: Document,
        text: ExtractedText,
        state: WorkflowState,
        reasons: list[ReviewReason],
        details: list[str],
    ) -> ExtractionResult | None:
        if doc.document_type is None or doc.document_type == DocumentType.UNKNOWN:
            return None
        try:
            outcome = self._extractor.extract(
                doc.document_type, text, doc.document_id, state.workflow_id
            )
        except ProviderError as exc:
            reasons.append(ReviewReason.RETRIES_EXHAUSTED)
            details.append(f"extraction failed: {exc.message}")
            return None
        if outcome is None:
            return None
        extraction, _ = outcome
        self._extractions.save(extraction)
        self._metrics.observe(
            "extraction_confidence",
            extraction.overall_confidence,
            {"document_type": extraction.document_type.value},
        )
        for issue in extraction.validation_issues:
            self._metrics.increment("validation_issues_total", labels={"rule": issue.rule})
        log_event(
            logger,
            "extraction_validated",
            document_type=extraction.document_type.value,
            validation_result="failed" if extraction.validation_issues else "passed",
            validation_rules_failed=sorted({i.rule for i in extraction.validation_issues}),
            extraction_confidence=extraction.overall_confidence,
            review_required=extraction.requires_review,
            model_name=extraction.model_name,
            prompt_version=extraction.prompt_version,
        )
        reasons.extend(extraction.review_reasons)
        details.extend(i.message for i in extraction.validation_issues)
        return extraction

    # ------------------------------------------------------------------ outcomes

    def _open_review(
        self,
        doc: Document,
        state: WorkflowState,
        reasons: list[ReviewReason],
        details: list[str],
        classification: ClassificationResult | None,
        extraction: ExtractionResult | None,
    ) -> None:
        original: dict[str, Any] = {
            "classification": classification.model_dump(mode="json") if classification else None,
            "extraction": extraction.model_dump(mode="json") if extraction else None,
            "security_flags": doc.security_flags,
        }
        model_version = (
            extraction.model_name
            if extraction
            else classification.model_name
            if classification
            else "n/a"
        )
        prompt_version = (
            ";".join(
                v
                for v in (
                    f"classification@{classification.prompt_version}" if classification else "",
                    f"extraction@{extraction.prompt_version}" if extraction else "",
                )
                if v
            )
            or "n/a"
        )
        case = self._reviews.create_case(
            target_type=ReviewTargetType.DOCUMENT_PROCESSING,
            target_id=extraction.extraction_id if extraction else doc.document_id,
            reasons=reasons,
            original_output=original,
            model_version=model_version,
            prompt_version=prompt_version,
            document_id=doc.document_id,
            workflow_id=state.workflow_id,
            details=details,
            workspace_id=doc.workspace_id,
        )
        state.review_id = case.review_id
        state.review_reasons = case.reasons

    def _finish_review_early(
        self,
        doc: Document,
        state: WorkflowState,
        reasons: list[ReviewReason],
        details: list[str],
        started: float,
    ) -> WorkflowState:
        self._documents.update(doc)
        self._open_review(doc, state, reasons, details, None, None)
        self._sm.transition(
            doc, WorkflowStatus.NEEDS_REVIEW, ", ".join(r.value for r in reasons), state
        )
        return self._complete(state, started, reasons)

    def _fail(
        self, doc: Document, state: WorkflowState, exc: Exception, started: float
    ) -> WorkflowState:
        error_type = exc.error_type if isinstance(exc, DocIntelError) else "internal_error"
        message = exc.message if isinstance(exc, DocIntelError) else "unexpected error"
        state.error_type = error_type
        state.error_message = message
        current = self._documents.get(doc.document_id)
        if can_transition(current.status, WorkflowStatus.FAILED):
            self._sm.transition(current, WorkflowStatus.FAILED, f"{error_type}: {message}", state)
        log_event(logger, "workflow_failed", logging.WARNING, error_type=error_type)
        return self._complete(state, started, [])

    def _complete(
        self, state: WorkflowState, started: float, reasons: list[ReviewReason]
    ) -> WorkflowState:
        state.finished_at = utcnow()
        duration = (time.perf_counter() - started) * 1000
        self._metrics.increment("workflow_runs_total", labels={"final_status": state.status.value})
        self._metrics.observe("workflow_duration_ms", duration)
        self._audit.record(
            "workflow.completed",
            document_id=state.document_id,
            workflow_id=state.workflow_id,
            details={
                "final_status": state.status.value,
                "review_reasons": sorted({r.value for r in reasons}),
                "duration_ms": round(duration, 2),
                "error_type": state.error_type,
            },
        )
        log_event(
            logger,
            "workflow_completed",
            final_status=state.status.value,
            review_required=bool(reasons),
            latency_ms=round(duration, 2),
            error_type=state.error_type,
        )
        return state
