"""In-process vector store (exact cosine search). Used for tests, evals and failure injection."""

from __future__ import annotations

import math
import threading

from app.core.errors import VectorStoreError
from app.domain.models import Chunk
from app.providers.vectorstore.base import MetadataFilter


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _matches(chunk: Chunk, where: MetadataFilter | None) -> bool:
    if not where:
        return True
    for key, expected in where.items():
        actual = chunk.document_id if key == "document_id" else chunk.metadata.get(key)
        if actual != expected:
            return False
    return True


class InMemoryVectorStore:
    def __init__(self, fail: bool = False) -> None:
        self._items: dict[str, tuple[Chunk, list[float]]] = {}
        self._lock = threading.Lock()
        self.fail = fail  # failure injection switch for resilience tests

    @property
    def name(self) -> str:
        return "memory"

    def _check(self) -> None:
        if self.fail:
            raise VectorStoreError("in-memory vector store unavailable (injected)")

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self._check()
        if len(chunks) != len(embeddings):
            raise VectorStoreError("chunks and embeddings length mismatch")
        with self._lock:
            for chunk, emb in zip(chunks, embeddings, strict=True):
                self._items[chunk.chunk_id] = (chunk, emb)

    def query(
        self, embedding: list[float], top_k: int, where: MetadataFilter | None = None
    ) -> list[tuple[Chunk, float]]:
        self._check()
        with self._lock:
            scored = [
                (chunk, cosine(embedding, emb))
                for chunk, emb in self._items.values()
                if _matches(chunk, where)
            ]
        scored.sort(key=lambda cs: (-cs[1], cs[0].chunk_id))
        return scored[:top_k]

    def delete_document(self, document_id: str) -> None:
        self._check()
        with self._lock:
            for cid in [c for c, (ch, _) in self._items.items() if ch.document_id == document_id]:
                del self._items[cid]

    def count(self) -> int:
        return len(self._items)

    def healthcheck(self) -> bool:
        return not self.fail
