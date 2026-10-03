"""Semantic retrieval with top-k, similarity threshold and metadata filtering."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.domain.models import RetrievalResult
from app.observability.metrics import MetricsRecorder
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.vectorstore.base import MetadataFilter, MetadataFilterInput, VectorStore


@dataclass
class RetrievalOutcome:
    query: str
    top_k: int
    min_score: float
    results: list[RetrievalResult]  # results at or above min_score
    candidate_scores: list[float] = field(default_factory=list)  # all top-k scores
    latency_ms: float = 0.0

    @property
    def top_score(self) -> float:
        return self.candidate_scores[0] if self.candidate_scores else 0.0


class Retriever:
    def __init__(
        self,
        embedder: EmbeddingProvider,
        store: VectorStore,
        metrics: MetricsRecorder,
        top_k: int,
        min_score: float,
        min_score_scoped: float | None = None,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._metrics = metrics
        self.top_k = top_k
        self.min_score = min_score
        self.min_score_scoped = min_score if min_score_scoped is None else min_score_scoped

    def retrieve(
        self,
        query: str,
        document_id: str | None = None,
        filters: MetadataFilterInput | None = None,
        top_k: int | None = None,
        min_score: float | None = None,
        workspace_id: str | None = None,
    ) -> RetrievalOutcome:
        """``workspace_id`` confines the search to one workspace; ``None`` searches all."""
        k = top_k or self.top_k
        if min_score is not None:
            threshold = min_score
        else:
            threshold = self.min_score_scoped if document_id else self.min_score
        where: MetadataFilter = dict(filters or {})
        if document_id:
            where["document_id"] = document_id
        if workspace_id is not None:
            where["workspace_id"] = workspace_id
        started = time.perf_counter()
        embedding = self._embedder.embed_query(query)
        hits = self._store.query(embedding, k, where or None)
        latency = (time.perf_counter() - started) * 1000
        results = [
            RetrievalResult(chunk=chunk, score=round(score, 6), rank=rank)
            for rank, (chunk, score) in enumerate(hits, start=1)
            if score >= threshold
        ]
        scores = [round(s, 6) for _, s in hits]
        self._metrics.observe("retrieval_latency_ms", latency)
        if scores:
            self._metrics.observe("retrieval_top_score", scores[0])
        self._metrics.increment(
            "retrieval_requests_total", labels={"empty": str(not results).lower()}
        )
        return RetrievalOutcome(
            query=query,
            top_k=k,
            min_score=threshold,
            results=results,
            candidate_scores=scores,
            latency_ms=round(latency, 3),
        )
