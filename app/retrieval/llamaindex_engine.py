"""LlamaIndex retrieval engine (optional extra: ``pip install 'fin-docintel[llamaindex]'``).

Queries run through LlamaIndex's ``VectorStoreIndex`` retriever, on top of two adapters: one
wraps our ``EmbeddingProvider`` as a LlamaIndex embedding model, the other wraps our
``VectorStore``. Indexing, retention purges and the stored vectors therefore stay shared with
the native engine; only the query path changes. Scores pass through unchanged (cosine
similarity), so refusal thresholds and answer confidence behave the same with either engine.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import BaseNode, TextNode
from llama_index.core.vector_stores.types import (
    BasePydanticVectorStore,
    FilterCondition,
    FilterOperator,
    MetadataFilters,
    VectorStoreQuery,
    VectorStoreQueryMode,
    VectorStoreQueryResult,
)
from llama_index.core.vector_stores.types import MetadataFilter as LlamaMetadataFilter
from pydantic import PrivateAttr

from app.domain.models import Chunk
from app.observability.metrics import MetricsRecorder
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.vectorstore.base import MetadataFilter, VectorStore
from app.retrieval.retriever import Retriever

CHUNK_KEY = "docintel_chunk"


class ProviderEmbedding(BaseEmbedding):
    """Our ``EmbeddingProvider`` behind LlamaIndex's embedding interface."""

    _provider: EmbeddingProvider = PrivateAttr()

    def __init__(self, provider: EmbeddingProvider) -> None:
        super().__init__(model_name=provider.model_name)
        self._provider = provider

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._provider.embed_query(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._provider.embed_query(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._provider.embed_documents([text])[0]

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._provider.embed_documents(texts)


class SharedVectorStore(BasePydanticVectorStore):
    """Our ``VectorStore`` behind LlamaIndex's vector store interface (query side only).

    Only equality filters joined with AND are accepted, because those are what the document,
    workspace and metadata scoping use; anything else raises instead of being silently dropped.
    """

    stores_text: bool = True
    is_embedding_query: bool = True
    _store: VectorStore = PrivateAttr()

    def __init__(self, store: VectorStore) -> None:
        super().__init__(stores_text=True)
        self._store = store

    @property
    def client(self) -> Any:
        return self._store

    def add(self, nodes: Sequence[BaseNode], **kwargs: Any) -> list[str]:
        if nodes:
            raise NotImplementedError("chunks are indexed by app.retrieval.indexer, not LlamaIndex")
        return []

    def delete(self, ref_doc_id: str, **delete_kwargs: Any) -> None:
        self._store.delete_document(ref_doc_id)

    def query(self, query: VectorStoreQuery, **kwargs: Any) -> VectorStoreQueryResult:
        if query.mode != VectorStoreQueryMode.DEFAULT or query.query_embedding is None:
            raise ValueError("only dense similarity queries with an embedding are supported")
        if query.node_ids or query.doc_ids:
            raise ValueError("node_ids / doc_ids are not supported; use metadata filters")
        hits = self._store.query(
            query.query_embedding, query.similarity_top_k, to_where(query.filters)
        )
        nodes: list[BaseNode] = [
            TextNode(
                id_=chunk.chunk_id,
                text=chunk.text,
                metadata={CHUNK_KEY: chunk},
                excluded_embed_metadata_keys=[CHUNK_KEY],
                excluded_llm_metadata_keys=[CHUNK_KEY],
            )
            for chunk, _ in hits
        ]
        return VectorStoreQueryResult(
            nodes=nodes,
            similarities=[score for _, score in hits],
            ids=[chunk.chunk_id for chunk, _ in hits],
        )


def to_filters(where: MetadataFilter | None) -> MetadataFilters | None:
    if not where:
        return None
    return MetadataFilters(
        filters=[
            LlamaMetadataFilter(key=key, value=value, operator=FilterOperator.EQ)
            for key, value in sorted(where.items())
        ],
        condition=FilterCondition.AND,
    )


def to_where(filters: MetadataFilters | None) -> MetadataFilter | None:
    if filters is None or not filters.filters:
        return None
    if filters.condition not in (None, FilterCondition.AND):
        raise ValueError("only AND-joined metadata filters are supported")
    where: MetadataFilter = {}
    for item in filters.filters:
        if not isinstance(item, LlamaMetadataFilter) or item.operator != FilterOperator.EQ:
            raise ValueError("only equality metadata filters are supported")
        if not isinstance(item.value, str | int | float | bool):
            raise ValueError(f"unsupported filter value for {item.key!r}")
        where[item.key] = item.value
    return where


class LlamaIndexRetriever(Retriever):
    engine = "llamaindex"

    def __init__(
        self,
        embedder: EmbeddingProvider,
        store: VectorStore,
        metrics: MetricsRecorder,
        top_k: int,
        min_score: float,
        min_score_scoped: float | None = None,
    ) -> None:
        super().__init__(embedder, store, metrics, top_k, min_score, min_score_scoped)
        self._index = VectorStoreIndex.from_vector_store(
            SharedVectorStore(store), embed_model=ProviderEmbedding(embedder)
        )

    def _search(
        self, query: str, k: int, where: MetadataFilter | None
    ) -> list[tuple[Chunk, float]]:
        retriever = self._index.as_retriever(similarity_top_k=k, filters=to_filters(where))
        hits: list[tuple[Chunk, float]] = []
        for scored in retriever.retrieve(query):
            chunk = scored.node.metadata.get(CHUNK_KEY)
            if not isinstance(chunk, Chunk) or scored.score is None:
                raise TypeError("LlamaIndex returned a node that did not come from our store")
            hits.append((chunk, float(scored.score)))
        return hits
