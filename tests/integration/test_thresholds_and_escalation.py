"""Configurable thresholds: low-confidence escalation and retrieval top-k / similarity threshold."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.domain.enums import ReviewReason, WorkflowStatus
from app.services.container import Container
from tests.support import ingest_and_process, make_settings

ContainerFactory = Callable[..., Container]


class TestLowConfidenceEscalation:
    def test_low_classification_confidence_routes_to_review(
        self, container_factory: ContainerFactory, tmp_path: Path
    ) -> None:
        c = container_factory(settings=make_settings(tmp_path, classification_min_confidence=0.99))
        doc, state = ingest_and_process(c, "invoice_01_acme.pdf")
        assert doc.status == WorkflowStatus.NEEDS_REVIEW
        assert ReviewReason.LOW_CLASSIFICATION_CONFIDENCE in state.review_reasons
        assert state.review_id is not None
        case = c.reviews.get(state.review_id)
        assert ReviewReason.LOW_CLASSIFICATION_CONFIDENCE in case.reasons
        assert case.original_output  # the model output the reviewer is asked to judge

    def test_low_extraction_confidence_routes_to_review(
        self, container_factory: ContainerFactory, tmp_path: Path
    ) -> None:
        c = container_factory(settings=make_settings(tmp_path, extraction_min_confidence=0.99))
        doc, state = ingest_and_process(c, "invoice_01_acme.pdf")
        assert doc.status == WorkflowStatus.NEEDS_REVIEW
        assert ReviewReason.LOW_EXTRACTION_CONFIDENCE in state.review_reasons

    def test_default_thresholds_let_clean_document_through(self, container: Container) -> None:
        doc, state = ingest_and_process(container, "invoice_01_acme.pdf")
        assert doc.status == WorkflowStatus.READY
        assert state.review_reasons == []

    def test_low_answer_confidence_returns_answer_flagged_for_review(
        self, container_factory: ContainerFactory, tmp_path: Path
    ) -> None:
        c = container_factory(settings=make_settings(tmp_path, answer_min_confidence=0.99))
        doc, _ = ingest_and_process(c, "invoice_01_acme.pdf")
        answer = c.rag.ask("What is the total amount due?", document_id=doc.document_id)
        assert not answer.refused and answer.citations
        assert answer.requires_review and answer.review_id is not None
        assert ReviewReason.LOW_ANSWER_CONFIDENCE in c.reviews.get(answer.review_id).reasons


class TestRetrievalParameters:
    def test_top_k_limits_results(self, container: Container) -> None:
        for name in ("income_statement_01_northwind.pdf", "balance_sheet_01_northwind.pdf"):
            ingest_and_process(container, name)
        wide = container.retriever.retrieve("Northwind total", top_k=5, min_score=-1.0)
        narrow = container.retriever.retrieve("Northwind total", top_k=1, min_score=-1.0)
        assert len(wide.results) > 1
        assert len(narrow.results) == 1
        assert narrow.results[0].chunk.chunk_id == wide.results[0].chunk.chunk_id
        assert [r.rank for r in wide.results] == list(range(1, len(wide.results) + 1))

    def test_similarity_threshold_filters_weak_matches(self, container: Container) -> None:
        ingest_and_process(container, "invoice_01_acme.pdf")
        loose = container.retriever.retrieve("amount due", top_k=4, min_score=-1.0)
        assert loose.results
        strict = container.retriever.retrieve("amount due", top_k=4, min_score=0.999)
        assert strict.results == []
        assert strict.candidate_scores == loose.candidate_scores  # scores kept for diagnostics

    def test_document_scope_is_enforced(self, container: Container) -> None:
        inv, _ = ingest_and_process(container, "invoice_01_acme.pdf")
        ingest_and_process(container, "invoice_02_brightpath.pdf")
        outcome = container.retriever.retrieve(
            "invoice amount due", document_id=inv.document_id, top_k=10, min_score=-1.0
        )
        assert outcome.results
        assert {r.chunk.document_id for r in outcome.results} == {inv.document_id}
