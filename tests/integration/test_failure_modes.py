"""Failure injection: model errors, timeouts, malformed output, vector-store outages, bad input."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from app.core.errors import InvalidDocumentError, InvalidStateError
from app.core.resilience import RetryPolicy
from app.domain.enums import ReviewReason, ReviewStatus, WorkflowStatus
from app.providers.llm.mock import MockLLMProvider
from app.providers.vectorstore.memory import InMemoryVectorStore
from app.services.container import Container
from tests.support import ingest, ingest_and_process, make_pdf, make_settings, sample_pdf

ContainerFactory = Callable[..., Container]
LLMFactory = Callable[..., MockLLMProvider]


def test_model_outage_routes_to_review_not_crash(
    container_factory: ContainerFactory, mock_llm_factory: LLMFactory
) -> None:
    c = container_factory(llm=mock_llm_factory(fail_first_n=100))
    doc, state = ingest_and_process(c, "invoice_01_acme.pdf")
    assert doc.status == WorkflowStatus.NEEDS_REVIEW
    assert ReviewReason.RETRIES_EXHAUSTED in state.review_reasons
    failed = [i for i in c.invocations.all() if not i.success]
    assert failed and all(i.error_type == "provider_error" for i in failed)


def test_transient_model_failure_recovers(
    container_factory: ContainerFactory, mock_llm_factory: LLMFactory
) -> None:
    c = container_factory(llm=mock_llm_factory(fail_first_n=1))
    doc, _ = ingest_and_process(c, "invoice_01_acme.pdf")
    assert doc.status == WorkflowStatus.READY
    assert any(i.retry_count == 1 for i in c.invocations.all())


def test_model_timeout_routes_to_review(
    container_factory: ContainerFactory, mock_llm_factory: LLMFactory, tmp_path: Path
) -> None:
    settings = make_settings(tmp_path / "timeout", llm_timeout_s=0.05)
    c = container_factory(
        settings=settings,
        llm=mock_llm_factory(delay_s=0.2),
        retry_policy=RetryPolicy(max_retries=0, backoff_s=0),
    )
    doc, state = ingest_and_process(c, "invoice_01_acme.pdf")
    assert doc.status == WorkflowStatus.NEEDS_REVIEW
    assert ReviewReason.RETRIES_EXHAUSTED in state.review_reasons
    assert any(i.error_type == "provider_timeout" for i in c.invocations.all())


def test_malformed_model_output_is_repaired(
    container_factory: ContainerFactory, mock_llm_factory: LLMFactory
) -> None:
    c = container_factory(llm=mock_llm_factory(malformed_first_n=1))
    doc, _ = ingest_and_process(c, "invoice_01_acme.pdf")
    assert doc.status == WorkflowStatus.READY


def test_persistently_malformed_output_routes_to_review(
    container_factory: ContainerFactory, mock_llm_factory: LLMFactory
) -> None:
    c = container_factory(llm=mock_llm_factory(malformed_first_n=100))
    doc, state = ingest_and_process(c, "invoice_01_acme.pdf")
    assert doc.status == WorkflowStatus.NEEDS_REVIEW
    assert ReviewReason.RETRIES_EXHAUSTED in state.review_reasons


def test_vector_store_outage_fails_workflow_and_can_retry(
    container_factory: ContainerFactory,
) -> None:
    store = InMemoryVectorStore(fail=True)
    c = container_factory(vector_store=store)
    doc, state = ingest_and_process(c, "invoice_01_acme.pdf")
    assert doc.status == WorkflowStatus.FAILED
    assert state.error_type == "vector_store_error"

    store.fail = False
    retried = c.workflow.process(doc.document_id)
    assert retried.status == WorkflowStatus.READY


def test_duplicate_upload_is_detected(container: Container) -> None:
    first = container.ingestion.upload(
        "a.pdf", "application/pdf", sample_pdf("invoice_01_acme.pdf")
    )
    second = container.ingestion.upload(
        "b.pdf", "application/pdf", sample_pdf("invoice_01_acme.pdf")
    )
    assert not first.duplicate and second.duplicate
    assert second.document.document_id == first.document.document_id


@pytest.mark.parametrize(
    ("filename", "content_type", "data", "message"),
    [
        ("x.pdf", "application/pdf", b"", "empty"),
        ("x.pdf", "application/pdf", b"MZ\x90\x00 not a pdf", "not a PDF"),
        ("x.exe", "application/pdf", b"%PDF-1.4\n", "only .pdf"),
        ("x.pdf", "text/html", b"%PDF-1.4\n", "content type"),
    ],
)
def test_upload_validation(
    container: Container, filename: str, content_type: str, data: bytes, message: str
) -> None:
    with pytest.raises(InvalidDocumentError, match=message):
        container.ingestion.upload(filename, content_type, data)


def test_oversized_upload_rejected(container_factory: ContainerFactory, tmp_path: Path) -> None:
    c = container_factory(settings=make_settings(tmp_path / "small", max_upload_mb=0.001))
    with pytest.raises(InvalidDocumentError, match="exceeds"):
        c.ingestion.upload("big.pdf", "application/pdf", sample_pdf("invoice_01_acme.pdf"))


def test_reprocessing_supersedes_pending_reviews(container: Container) -> None:
    doc, state = ingest_and_process(container, "income_statement_03_aurora.pdf")
    first_review = state.review_id
    assert first_review is not None
    state2 = container.workflow.process(doc.document_id)
    assert container.reviews.get(first_review).status == ReviewStatus.SUPERSEDED
    assert state2.review_id and state2.review_id != first_review


def test_cannot_ask_unprocessed_document(container: Container) -> None:
    doc = ingest(container, "invoice_01_acme.pdf")
    with pytest.raises(InvalidStateError):
        container.rag.ask("What is the amount due?", document_id=doc.document_id)


def test_document_with_no_recognisable_fields(container: Container) -> None:
    data = make_pdf(
        [
            "INVOICE\nThis page intentionally has no labelled values at all.\n"
            "Bill To: nobody in particular. Thank you for your business."
        ]
    )
    doc, state = ingest_and_process(container, "sparse.pdf", data)
    assert doc.status == WorkflowStatus.NEEDS_REVIEW
    assert ReviewReason.MISSING_REQUIRED_FIELDS in state.review_reasons
