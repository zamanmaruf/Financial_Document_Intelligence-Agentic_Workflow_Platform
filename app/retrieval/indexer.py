"""Embeds chunks and (re)indexes them for a document. Re-indexing is idempotent."""

from __future__ import annotations

import time

from app.domain.models import Chunk
from app.observability.metrics import MetricsRecorder
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.vectorstore.base import VectorStore

EMBED_BATCH_SIZE = 64


class Indexer:
    def __init__(
        self, embedder: EmbeddingProvider, store: VectorStore, metrics: MetricsRecorder
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._metrics = metrics

    def index(self, document_id: str, chunks: list[Chunk]) -> int:
        started = time.perf_counter()
        self._store.delete_document(document_id)
        for i in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[i : i + EMBED_BATCH_SIZE]
            vectors = self._embedder.embed_documents([c.text for c in batch])
            self._store.upsert(batch, vectors)
        elapsed = (time.perf_counter() - started) * 1000
        self._metrics.observe("indexing_latency_ms", elapsed)
        self._metrics.increment("chunks_indexed_total", len(chunks))
        return len(chunks)
