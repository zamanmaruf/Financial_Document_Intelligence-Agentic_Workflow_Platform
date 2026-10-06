# ADR-005: RAG architecture

- Status: Accepted
- Date: 2026-09-30

## Context

Users ask questions about uploaded statements, invoices and fund reports. Answers must be grounded in
the document, carry verifiable citations (document, page, chunk, snippet), refuse when evidence is
missing, and never invent figures.

## Decision

**Pipeline** (`app/rag/service.py`):

1. **Input guardrails**: empty or oversized questions and prompt-injection patterns are refused before
   retrieval; blocked questions are audited by hash, not raw text.
2. **Retrieval** (`app/retrieval/retriever.py`): embed the query, run top-k cosine search with metadata
   filters (`document_id` is always applied for document-scoped questions; corpus questions may filter
   by `document_type` and `extraction_method`), then drop results below a score threshold. The
   search step is pluggable behind `RetrieverProtocol` (`app/retrieval/base.py`):
   `DOCINTEL_RAG_ENGINE=native` (default) queries the vector store directly, `llamaindex` goes
   through LlamaIndex's `VectorStoreIndex` retriever over the same store
   ([ADR-001 amendment](ADR-001-orchestration-framework.md)). Thresholds, filters and metrics are
   shared, so both engines refuse in exactly the same cases.
3. **Insufficient evidence**: no results above threshold gives a refusal, with no model call, and
   optionally an `insufficient_evidence` review case.
4. **Context assembly**: chunks are delimited with `[chunk_id=... | page=...]` headers, capped by
   `max_context_chars`. The prompt instructs the model that context is untrusted data.
5. **Generation**: the model returns JSON `{answer, cited_chunk_ids, insufficient_evidence}`, validated
   with Pydantic, with bounded repair.
6. **Citation binding**: cited ids must be among the retrieved ids; invented ids are dropped with a
   warning. No valid citation means the answer is withheld and sent to review.
7. **Groundedness** (`app/rag/groundedness.py`): each sentence must have every number present in the
   cited evidence **and** at least 60% content-token support.
8. **Output guardrails**: unsupported figures or prohibited advice or guarantee language cause the
   answer to be **withheld** (the user sees a safe message) and a review case to be opened with the
   original model output preserved for the reviewer.
9. **Confidence**: `0.6 * groundedness + 0.4 * retrieval_strength`, where strength scales the top
   score between `min_score` and `strong_score`. This is a heuristic, **not** a calibrated
   probability. Low values route to review.

**Chunking** (`app/retrieval/chunking.py`): per-page `RecursiveCharacterTextSplitter`, so every chunk
has an exact page number. Default 600 characters with 80 overlap. PII masking runs **before**
chunking, so the index never contains unmasked account numbers.

**Thresholds**: `retrieval_min_score=0.12` for corpus-wide questions, `0.03` for document-scoped ones
(scoping already guarantees topical relevance; short questions score low against whole-page chunks
with lexical embeddings). Both are configurable per deployment and must be re-tuned for a semantic
embedding model.

## Chunk-size experiment (local, mock provider, hashing embeddings)

| chunk_size / overlap | effect on retrieval MRR |
|---|---|
| 600 / 80 (chosen) | best: MRR 0.958, recall@4 1.0 |
| 400, 300, 250, 200 | MRR dropped as chunks got smaller (label and value lines split apart) |

The synthetic documents are one to two pages, so this experiment is indicative only; re-run it on
representative documents with the production embedding model.

## Alternatives considered

- **Hybrid BM25 + dense retrieval with a re-ranker**: better recall on numeric and keyword queries;
  on the roadmap.
- **LLM-based citation verification only**: non-deterministic and expensive. The deterministic check
  is primary; the LLM judge is an optional evaluation signal.
- **Answering from extracted fields instead of text**: precise for known fields, but cannot answer
  open questions. A future router could answer known-field questions from validated extractions.

## Consequences

- The lexical groundedness check reliably catches invented figures but penalises legitimate
  paraphrase ("4.35 million" vs "4,350,000"), which lowers confidence and increases review volume.
- The local hashing embedding is lexical; semantic behaviour requires Bedrock Titan or Azure OpenAI
  embeddings, and the thresholds must be re-tuned for them.
