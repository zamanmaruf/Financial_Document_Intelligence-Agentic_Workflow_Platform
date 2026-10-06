"""The LlamaIndex retrieval engine returns exactly what the native engine returns."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("llama_index.core")

from llama_index.core.vector_stores.types import (
    FilterCondition,
    FilterOperator,
    MetadataFilters,
)
from llama_index.core.vector_stores.types import MetadataFilter as LlamaFilter

from app.core.config import RAGEngineName, VectorStoreName
from app.core.errors import ProviderConfigurationError
from app.providers import factory
from app.retrieval.base import RetrievalOutcome, RetrieverProtocol
from app.retrieval.llamaindex_engine import (
    LlamaIndexRetriever,
    ProviderEmbedding,
    SharedVectorStore,
    to_filters,
    to_where,
)
from app.retrieval.retriever import Retriever
from app.services.container import Container
from tests.support import make_settings, sample_pdf

ContainerFactory = Callable[..., Container]

FILES = [
    "invoice_01_acme.pdf",
    "bank_statement_01_firstcoastal.pdf",
    "fund_summary_01_evergreen.pdf",
    "balance_sheet_01_northwind.pdf",
]
QUERIES = [
    "What is the amount due?",
    "closing balance",
    "management fee",
    "total assets",
    "Who is the vendor on the Acme invoice?",
    "something nobody wrote about",
]


def indexed(c: Container, workspace: str = "default") -> dict[str, str]:
    ids = {}
    for name in FILES:
        doc = c.ingestion.upload(
            name, "application/pdf", sample_pdf(name), workspace_id=workspace
        ).document
        c.workflow.process(doc.document_id)
        ids[name] = doc.document_id
    return ids


def llamaindex_twin(c: Container) -> LlamaIndexRetriever:
    native = c.retriever
    assert isinstance(native, Retriever)
    return LlamaIndexRetriever(
        c.embedder,
        c.vector_store,
        c.metrics,
        native.top_k,
        native.min_score,
        native.min_score_scoped,
    )


def same(a: RetrievalOutcome, b: RetrievalOutcome) -> None:
    assert [(r.chunk.chunk_id, r.score, r.rank) for r in a.results] == [
        (r.chunk.chunk_id, r.score, r.rank) for r in b.results
    ]
    assert a.candidate_scores == b.candidate_scores
    assert (a.top_k, a.min_score) == (b.top_k, b.min_score)
    assert [r.chunk for r in a.results] == [r.chunk for r in b.results]


@pytest.mark.parametrize("store", [VectorStoreName.MEMORY, VectorStoreName.CHROMA])
def test_parity_with_native_engine(
    container_factory: ContainerFactory, tmp_path: Path, store: VectorStoreName
) -> None:
    c = container_factory(settings=make_settings(tmp_path / store.value, vector_store=store))
    ids = indexed(c)
    llama = llamaindex_twin(c)
    native = c.retriever
    scoped = ids["invoice_01_acme.pdf"]
    for query in QUERIES:
        same(native.retrieve(query), llama.retrieve(query))
        same(native.retrieve(query, document_id=scoped), llama.retrieve(query, document_id=scoped))
        same(
            native.retrieve(query, top_k=8, min_score=-1.0),
            llama.retrieve(query, top_k=8, min_score=-1.0),
        )
        same(
            native.retrieve(query, filters={"document_type": "bank_statement"}),
            llama.retrieve(query, filters={"document_type": "bank_statement"}),
        )


def test_scoping_is_enforced(container_factory: ContainerFactory) -> None:
    c = container_factory()
    mine = indexed(c, workspace="ws_mine")
    indexed_other = c.ingestion.upload(
        "invoice_02_brightpath.pdf",
        "application/pdf",
        sample_pdf("invoice_02_brightpath.pdf"),
        workspace_id="ws_other",
    ).document
    c.workflow.process(indexed_other.document_id)
    llama = llamaindex_twin(c)

    outcome = llama.retrieve("amount due invoice", top_k=20, min_score=-1.0, workspace_id="ws_mine")
    assert outcome.results
    assert {r.chunk.metadata["workspace_id"] for r in outcome.results} == {"ws_mine"}

    scoped = llama.retrieve("balance", document_id=mine["bank_statement_01_firstcoastal.pdf"])
    assert {r.chunk.document_id for r in scoped.results} == {
        mine["bank_statement_01_firstcoastal.pdf"]
    }
    typed = llama.retrieve("total", top_k=20, min_score=-1.0, filters={"document_type": "invoice"})
    assert {r.chunk.metadata["document_type"] for r in typed.results} == {"invoice"}


def test_container_selects_llamaindex_and_answers_like_native(
    container_factory: ContainerFactory, tmp_path: Path
) -> None:
    native_c = container_factory(settings=make_settings(tmp_path / "n"))
    llama_c = container_factory(
        settings=make_settings(tmp_path / "l", rag_engine=RAGEngineName.LLAMAINDEX)
    )
    assert isinstance(llama_c.retriever, LlamaIndexRetriever)
    assert isinstance(llama_c.retriever, RetrieverProtocol)
    assert llama_c.retriever.engine == "llamaindex" and native_c.retriever.engine == "native"
    assert llama_c.settings.public_summary()["rag_engine"] == "llamaindex"
    for c in (native_c, llama_c):
        indexed(c)
    for question in ("What is the amount due on the Acme invoice?", "What is the weather?"):
        a, b = native_c.rag.ask(question), llama_c.rag.ask(question)
        assert (a.answer, a.refused, a.confidence) == (b.answer, b.refused, b.confidence)
        # chunk IDs embed the per-container document ID, so compare what was cited
        assert [(x.page_number, x.text_snippet, x.retrieval_score) for x in a.citations] == [
            (x.page_number, x.text_snippet, x.retrieval_score) for x in b.citations
        ]
    counters = llama_c.metrics.snapshot()["counters"]["retrieval_requests_total"]
    assert all(entry["labels"]["engine"] == "llamaindex" for entry in counters)


class TestAdapters:
    def test_filters_round_trip(self) -> None:
        where: dict[str, Any] = {"document_id": "doc_1", "workspace_id": "ws", "page": 2}
        assert to_where(to_filters(where)) == where
        assert to_filters(None) is None and to_where(None) is None

    @pytest.mark.parametrize(
        "filters",
        [
            MetadataFilters(
                filters=[LlamaFilter(key="a", value=1), LlamaFilter(key="b", value=2)],
                condition=FilterCondition.OR,
            ),
            MetadataFilters(filters=[LlamaFilter(key="a", value=1, operator=FilterOperator.GT)]),
            MetadataFilters(
                filters=[LlamaFilter(key="a", value=["x"], operator=FilterOperator.EQ)]
            ),
        ],
    )
    def test_unsupported_filters_raise_instead_of_widening_the_search(
        self, filters: MetadataFilters
    ) -> None:
        with pytest.raises(ValueError):
            to_where(filters)

    def test_store_is_query_only_and_embedding_delegates(self, container: Container) -> None:
        from llama_index.core.schema import TextNode

        store = SharedVectorStore(container.vector_store)
        assert store.add([]) == []
        with pytest.raises(NotImplementedError):
            store.add([TextNode(text="x")])
        embedding = ProviderEmbedding(container.embedder)
        assert embedding.get_query_embedding("fee") == container.embedder.embed_query("fee")
        assert embedding.get_text_embedding_batch(["a", "b"]) == container.embedder.embed_documents(
            ["a", "b"]
        )


def test_missing_extra_gives_a_clear_error(
    container: Container, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "llama_index", None)
    monkeypatch.setitem(sys.modules, "llama_index.core", None)
    monkeypatch.delitem(sys.modules, "app.retrieval.llamaindex_engine", raising=False)
    settings = make_settings(tmp_path, rag_engine=RAGEngineName.LLAMAINDEX)
    with pytest.raises(ProviderConfigurationError, match=r"fin-docintel\[llamaindex\]"):
        factory.build_retriever(
            settings, container.embedder, container.vector_store, container.metrics
        )
