from __future__ import annotations

import pytest

from app.core.errors import InvalidStateError
from app.domain.enums import (
    DocumentType,
    ReviewReason,
    ReviewStatus,
    ReviewTargetType,
    ValidationStatus,
    WorkflowStatus,
)
from app.services.container import Container
from tests.support import ingest_and_process


def pending_review(c: Container, file: str) -> tuple[str, str]:
    doc, state = ingest_and_process(c, file)
    assert doc.status == WorkflowStatus.NEEDS_REVIEW
    assert state.review_id is not None
    return doc.document_id, state.review_id


def test_review_case_contents(container: Container) -> None:
    doc_id, review_id = pending_review(container, "income_statement_03_aurora.pdf")
    case = container.reviews.get(review_id)
    assert case.status == ReviewStatus.PENDING
    assert case.target_type == ReviewTargetType.DOCUMENT_PROCESSING
    assert ReviewReason.MISSING_REQUIRED_FIELDS in case.reasons
    assert case.model_version and case.prompt_version
    assert case.original_output and "extraction" in case.original_output
    assert (
        container.reviews.list(status=ReviewStatus.PENDING, document_id=doc_id)[0].review_id
        == review_id
    )


def test_approve_moves_document_to_ready(container: Container) -> None:
    doc_id, review_id = pending_review(container, "income_statement_03_aurora.pdf")
    case = container.reviews.approve(review_id, "alice", "looks fine")
    assert case.status == ReviewStatus.APPROVED
    assert case.reviewer_id == "alice" and case.resolved_at is not None
    assert container.documents.get(doc_id).status == WorkflowStatus.READY
    events = [
        e for e in container.audit.history(document_id=doc_id) if e.event_type == "review.approved"
    ]
    assert events and events[0].actor == "reviewer:alice"


def test_reject_moves_document_to_rejected(container: Container) -> None:
    doc_id, review_id = pending_review(container, "edge_injection_invoice.pdf")
    container.reviews.reject(review_id, "bob", "embedded instructions")
    assert container.documents.get(doc_id).status == WorkflowStatus.REJECTED
    with pytest.raises(InvalidStateError):
        container.rag.ask("What is the amount due?", document_id=doc_id)


def test_cannot_resolve_twice(container: Container) -> None:
    _, review_id = pending_review(container, "income_statement_03_aurora.pdf")
    container.reviews.approve(review_id, "alice")
    with pytest.raises(InvalidStateError):
        container.reviews.reject(review_id, "bob")


def test_field_correction_creates_new_extraction_version(container: Container) -> None:
    doc_id, review_id = pending_review(container, "income_statement_03_aurora.pdf")
    before = container.extractions.latest_for_document(doc_id)
    assert before is not None and before.value("currency") is None

    case = container.reviews.correct(review_id, "carol", {"currency": "usd"}, "confirmed")
    assert case.status == ReviewStatus.CORRECTED
    after = container.extractions.latest_for_document(doc_id)
    assert after is not None and after.extraction_id != before.extraction_id
    assert after.corrected_by_review_id == review_id
    entity = after.entity("currency")
    assert entity is not None
    assert entity.value == "USD"
    assert entity.validation_status == ValidationStatus.CORRECTED
    assert len(container.extractions.list_for_document(doc_id)) == 2  # history kept
    assert container.documents.get(doc_id).status == WorkflowStatus.READY


def test_invalid_correction_is_rejected(container: Container) -> None:
    _, review_id = pending_review(container, "income_statement_03_aurora.pdf")
    with pytest.raises(InvalidStateError):
        container.reviews.correct(review_id, "carol", {"currency": "DOLLARS"})
    with pytest.raises(InvalidStateError):
        container.reviews.correct(review_id, "carol", {"not_a_field": 1})
    with pytest.raises(InvalidStateError):
        container.reviews.correct(review_id, "carol", {})
    assert container.reviews.get(review_id).status == ReviewStatus.PENDING


def test_document_type_correction_reprocesses(container: Container) -> None:
    doc_id, review_id = pending_review(container, "edge_ambiguous_memo.pdf")
    container.reviews.correct(review_id, "dave", {"document_type": "invoice"})
    doc = container.documents.get(doc_id)
    assert doc.document_type == DocumentType.INVOICE
    assert doc.classification is not None and doc.classification.provider == "human"
    assert container.reviews.get(review_id).status == ReviewStatus.CORRECTED
    # the memo has no invoice fields, so reprocessing opens a new review for missing fields
    assert doc.status == WorkflowStatus.NEEDS_REVIEW


def test_answer_review_correction(container: Container) -> None:
    doc, _ = ingest_and_process(container, "invoice_01_acme.pdf")
    answer = container.rag.ask("What is the vendor's credit rating?", document_id=doc.document_id)
    assert answer.refused and answer.review_id
    case = container.reviews.get(answer.review_id)
    assert case.target_type == ReviewTargetType.ANSWER
    assert ReviewReason.INSUFFICIENT_EVIDENCE in case.reasons
    with pytest.raises(InvalidStateError):
        container.reviews.correct(case.review_id, "erin", {"currency": "USD"})
    done = container.reviews.correct(
        case.review_id, "erin", {"answer": "Not stated in the invoice."}
    )
    assert done.corrected_output == {"answer": "Not stated in the invoice."}
    # answer reviews never change the document state
    assert container.documents.get(doc.document_id).status == WorkflowStatus.READY
