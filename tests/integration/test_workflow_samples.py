"""Full processing workflow over every synthetic sample document (mock provider, no network)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.core.errors import InvalidDocumentError
from app.core.registry import DocumentTypeRegistry
from app.domain.enums import ReviewReason, WorkflowStatus
from app.evaluation.metrics import values_normalized_match
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.mock_handlers import MockHandler, default_handlers
from app.services.container import Container
from tests.support import GROUND_TRUTH, ingest_and_process, sample_pdf

DOCS: list[dict[str, Any]] = GROUND_TRUTH["documents"]
PROCESSABLE = [d for d in DOCS if d["expected_outcome"] != "UPLOAD_REJECTED"]


@pytest.mark.parametrize("entry", PROCESSABLE, ids=[d["file"] for d in PROCESSABLE])
def test_sample_document_outcome(container: Container, entry: dict[str, Any]) -> None:
    doc, state = ingest_and_process(container, entry["file"])
    expected = entry["expected_outcome"]
    if entry["kind"] == "scanned":  # no OCR engine in this container
        expected = "NEEDS_REVIEW"
    assert doc.status.value == expected, state.review_reasons
    assert state.status == doc.status

    if expected == "READY":
        assert state.review_id is None
        assert doc.document_type is not None
        assert doc.document_type.value == entry["document_type"]


@pytest.mark.parametrize(
    "entry",
    [d for d in PROCESSABLE if d["include_in_eval"] and d["document_type"] != "unknown"],
    ids=lambda d: d["file"],
)
def test_extracted_fields_match_ground_truth(container: Container, entry: dict[str, Any]) -> None:
    doc, _ = ingest_and_process(container, entry["file"])
    extraction = container.extractions.latest_for_document(doc.document_id)
    assert extraction is not None
    for field, expected in entry["expected_fields"].items():
        predicted = extraction.value(field)
        assert values_normalized_match(expected, predicted), (field, expected, predicted)
        entity = extraction.entity(field)
        if expected is not None and entity is not None:
            assert entity.evidence is not None and entity.evidence.page_number is not None


@pytest.mark.parametrize(
    ("file", "unmasked_prefix"),
    [
        ("bank_statement_01_firstcoastal.pdf", "4432 1187 9023"),
        ("bank_statement_02_harbor.pdf", "GB29 NWBK 6016"),
        ("bank_statement_03_pinnacle.pdf", "7781-0045"),
    ],
)
def test_account_identifiers_are_masked_everywhere(
    container: Container, file: str, unmasked_prefix: str
) -> None:
    doc, _ = ingest_and_process(container, file)
    raw_text = container.texts.get(doc.document_id)
    assert raw_text is not None and unmasked_prefix in raw_text.full_text  # fixture sanity

    extraction = container.extractions.latest_for_document(doc.document_id)
    assert extraction is not None
    answer = container.rag.ask("What is the account number?", document_id=doc.document_id)
    hits = container.vector_store.query(
        container.embedder.embed_query("account number"), 50, {"document_id": doc.document_id}
    )
    exposed = [
        extraction.model_dump_json(),
        answer.model_dump_json(),
        *(e.model_dump_json() for e in container.audit.history(document_id=doc.document_id)),
        *(chunk.text for chunk, _ in hits),
    ]
    compact = unmasked_prefix.replace(" ", "").replace("-", "")
    for blob in exposed:
        assert unmasked_prefix not in blob
        assert compact not in blob


def _garbling_handlers(registry: DocumentTypeRegistry, printed: str) -> dict[str, MockHandler]:
    """Mock handlers whose extraction mis-masks the account number, as gpt-4.1-mini once did."""
    handlers = default_handlers(registry)
    base = handlers["extraction.financial_entities"]

    def garble(variables: dict[str, Any]) -> dict[str, Any]:
        out = base(variables)
        account = out["fields"].get("account_number_masked")
        if account and account.get("value"):
            out["fields"]["account_number_masked"] = {
                **account,
                "value": "****2619",
                "raw_text": printed,
            }
        return out

    handlers["extraction.financial_entities"] = garble
    return handlers


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("GB29 NWBK 6016 1331 9268 19", "****6819"),  # printed in the PDF: authoritative
        ("GB00 0000 0000 0000 0000 99", "****2619"),  # not in the PDF: model value kept
    ],
)
def test_masked_account_is_recomputed_from_printed_number(
    container_factory: Callable[..., Container],
    registry: DocumentTypeRegistry,
    printed: str,
    expected: str,
) -> None:
    c = container_factory(llm=MockLLMProvider(_garbling_handlers(registry, printed)))
    doc, _ = ingest_and_process(c, "bank_statement_02_harbor.pdf")
    extraction = c.extractions.latest_for_document(doc.document_id)
    assert extraction is not None
    entity = extraction.entity("account_number_masked")
    assert entity is not None and entity.value == expected
    recomputed = any("recomputed" in m for m in entity.messages)
    assert recomputed == (expected == "****6819")


def test_conflicting_values_route_to_review(container: Container) -> None:
    doc, state = ingest_and_process(container, "balance_sheet_03_granite_conflict.pdf")
    assert doc.status == WorkflowStatus.NEEDS_REVIEW
    assert ReviewReason.CONFLICTING_VALUES in state.review_reasons
    review = container.reviews.get(state.review_id)  # type: ignore[arg-type]
    assert review.original_output is not None


def test_injection_document_is_flagged_but_processed(container: Container) -> None:
    doc, state = ingest_and_process(container, "edge_injection_invoice.pdf")
    assert "prompt_injection_suspected" in doc.security_flags
    assert ReviewReason.GUARDRAIL_TRIGGERED in state.review_reasons
    events = [e.event_type for e in container.audit.history(document_id=doc.document_id)]
    assert "guardrail.document_injection_suspected" in events


def test_empty_pdf_fails_cleanly(container: Container) -> None:
    doc, state = ingest_and_process(container, "edge_empty.pdf")
    assert doc.status == WorkflowStatus.FAILED
    assert state.error_type == "empty_document"


def test_malformed_pdf_rejected_at_upload(container: Container) -> None:
    with pytest.raises(InvalidDocumentError):
        container.ingestion.upload(
            "edge_malformed.pdf", "application/pdf", sample_pdf("edge_malformed.pdf")
        )


def test_scanned_pdf_without_ocr_routes_to_review(container: Container) -> None:
    doc, state = ingest_and_process(container, "edge_scanned_invoice.pdf")
    assert doc.status == WorkflowStatus.NEEDS_REVIEW
    assert state.review_reasons == [ReviewReason.OCR_UNAVAILABLE]


def test_every_transition_is_audited(container: Container) -> None:
    doc, state = ingest_and_process(container, "invoice_01_acme.pdf")
    transitions = [
        e
        for e in container.audit.history(document_id=doc.document_id)
        if e.event_type == "workflow.transition"
    ]
    assert [e.details["to"] for e in transitions] == [t.to_status.value for t in state.history]
    assert container.audit.verify_chain() == (True, None)
