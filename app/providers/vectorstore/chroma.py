"""Embedded persistent Chroma vector store.

Embeddings are always computed by our ``EmbeddingProvider`` and passed explicitly, so Chroma's
default embedding function (which downloads a model) is never used. The collection name embeds
the embedding model identity so vectors from different models/dimensions are never mixed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from app.core.errors import VectorStoreError
from app.core.hashing import short_hash
from app.domain.models import Chunk
from app.providers.vectorstore.base import MetadataFilter


class ChromaVectorStore:
    def __init__(self, persist_dir: Path, embedding_model: str) -> None:
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise VectorStoreError("chromadb is not installed") from exc
        persist_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._client = chromadb.PersistentClient(
                path=str(persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False),
            )
            self._collection_name = f"chunks_{short_hash(embedding_model, 10)}"
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=None,
                metadata={"hnsw:space": "cosine", "embedding_model": embedding_model},
            )
        except Exception as exc:
            raise VectorStoreError(f"failed to open Chroma store: {type(exc).__name__}") from exc

    @property
    def name(self) -> str:
        return "chroma"

    @staticmethod
    def _to_metadata(chunk: Chunk) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "page_number": chunk.page_number if chunk.page_number is not None else -1,
            "extra_json": json.dumps(chunk.metadata, sort_keys=True),
        }
        # also expose extra metadata as top-level keys so it can be used in `where` filters
        for key, value in chunk.metadata.items():
            meta.setdefault(key, value)
        return meta

    @staticmethod
    def _from_record(chunk_id: str, text: str, meta: dict[str, Any]) -> Chunk:
        page = int(meta.get("page_number", -1))
        return Chunk(
            chunk_id=chunk_id,
            document_id=str(meta["document_id"]),
            text=text,
            page_number=None if page < 0 else page,
            chunk_index=int(meta["chunk_index"]),
            start_char=int(meta["start_char"]),
            end_char=int(meta["end_char"]),
            metadata=json.loads(str(meta.get("extra_json", "{}"))),
        )

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise VectorStoreError("chunks and embeddings length mismatch")
        try:
            self._collection.upsert(
                ids=[c.chunk_id for c in chunks],
                embeddings=cast(Any, embeddings),
                documents=[c.text for c in chunks],
                metadatas=[self._to_metadata(c) for c in chunks],
            )
        except Exception as exc:
            raise VectorStoreError(f"Chroma upsert failed: {type(exc).__name__}") from exc

    def query(
        self, embedding: list[float], top_k: int, where: MetadataFilter | None = None
    ) -> list[tuple[Chunk, float]]:
        where_clause: dict[str, Any] | None = None
        if where:
            clauses = [{k: {"$eq": v}} for k, v in sorted(where.items())]
            where_clause = clauses[0] if len(clauses) == 1 else {"$and": clauses}
        try:
            res = self._collection.query(
                query_embeddings=cast(Any, [embedding]),
                n_results=top_k,
                where=where_clause,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise VectorStoreError(f"Chroma query failed: {type(exc).__name__}") from exc
        ids = res["ids"][0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out: list[tuple[Chunk, float]] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, dists, strict=True):
            # cosine distance -> cosine similarity
            out.append((self._from_record(cid, doc or "", dict(meta or {})), 1.0 - float(dist)))
        out.sort(key=lambda cs: (-cs[1], cs[0].chunk_id))
        return out

    def delete_document(self, document_id: str) -> None:
        try:
            self._collection.delete(where=cast(Any, {"document_id": {"$eq": document_id}}))
        except Exception as exc:
            raise VectorStoreError(f"Chroma delete failed: {type(exc).__name__}") from exc

    def count(self) -> int:
        return int(self._collection.count())

    def healthcheck(self) -> bool:
        try:
            self._client.heartbeat()
            return True
        except Exception:
            return False
