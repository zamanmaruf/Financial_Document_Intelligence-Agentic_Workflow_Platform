from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from app.domain.models import Chunk

# Metadata filters are simple equality constraints, e.g. {"document_id": "doc_x"}.
MetadataFilter = dict[str, str | int | float | bool]
MetadataFilterInput = Mapping[str, str | int | float | bool]


@runtime_checkable
class VectorStore(Protocol):
    @property
    def name(self) -> str: ...

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None: ...

    def query(
        self, embedding: list[float], top_k: int, where: MetadataFilter | None = None
    ) -> list[tuple[Chunk, float]]:
        """Return up to ``top_k`` (chunk, cosine_similarity) pairs, best first."""
        ...

    def delete_document(self, document_id: str) -> None: ...

    def count(self) -> int: ...

    def healthcheck(self) -> bool: ...
