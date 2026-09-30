# ADR-002: Vector store choice

- Status: Accepted
- Date: 2026-09-30

## Context

RAG needs similarity search over document chunks with metadata filters (document id, document type,
extraction method). The system must run locally with no external services, run in CI, and be
replaceable by a managed store in production.

## Decision

- Define a narrow `VectorStore` protocol (`app/providers/vectorstore/base.py`): `upsert`, `query`
  (with a metadata `where` filter), `delete_document`, `count`, `healthcheck`.
- **Default: Chroma 1.x** in embedded persistent mode (`PersistentClient`, cosine space,
  `embedding_function=None`: we always pass our own vectors).
- **Tests and evaluation: `InMemoryVectorStore`**, an exact cosine search with the same filter
  semantics and a `fail` flag for failure-injection tests.
- The Chroma collection name includes a hash of the embedding model identity
  (`chunks_<sha(model)>`), so switching embedding models can never mix incompatible vectors in one
  index.
- Re-indexing a document deletes its previous chunks first (idempotent re-processing; covered by
  `test_chroma_backend_end_to_end`).

## Alternatives considered

| Option | Why not (for this scope) |
|---|---|
| FAISS | no metadata filtering or persistence semantics out of the box |
| pgvector | excellent production choice but needs a Postgres service locally and in CI |
| OpenSearch / Azure AI Search / Pinecone | managed services, need credentials; they are production targets |
| Qdrant | good, but requires a separate server process for persistence |

## Consequences

- Zero-infrastructure local and CI runs. The Docker image stores the index on the `/data` volume.
- Embedded Chroma is single-process; it is **not** suitable for multiple API replicas writing
  concurrently. Production should move to pgvector (if Postgres is already the system of record),
  OpenSearch Serverless (AWS) or Azure AI Search (Azure), implemented behind the same protocol.
- Chroma distance is converted to similarity (`1 - distance`) so thresholds are store-agnostic.
