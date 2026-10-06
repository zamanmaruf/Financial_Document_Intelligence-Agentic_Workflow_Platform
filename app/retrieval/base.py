"""Retrieval interface shared by the native and LlamaIndex engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.domain.models import RetrievalResult
from app.providers.vectorstore.base import MetadataFilterInput


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


@runtime_checkable
class RetrieverProtocol(Protocol):
    engine: str
    top_k: int
    min_score: float
    min_score_scoped: float

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
        ...
