# Codebase walkthrough

A file-by-file tour of `fin-docintel`. For each module: **responsibility**, **depends on**,
**data in → data out**, **key classes/functions**, **design decisions**, and **likely interview
questions**. Package `__init__.py` files are empty or only re-export and are omitted, except
`app/__init__.py` (holds `__version__`).

Suggested reading order for a reviewer: `app/services/container.py` → `app/workflows/orchestrator.py`
→ `app/services/model_gateway.py` → `app/rag/service.py` → `app/human_review/service.py` →
`app/api/main.py`.

---

## 1. Request path: API layer (`app/api`)

### `app/api/main.py`
- **Responsibility:** FastAPI application factory.
- **Depends on:** settings, container, routers, logging, error types.
- **Data in → out:** HTTP requests → JSON responses; lifecycle events → container build/close.
- **Key elements:** `create_app(settings=None, container=None)`; lifespan builds the container
  (or uses the injected one) and closes it on shutdown; HTTP middleware that validates or
  generates `X-Request-ID`, sets it in a `contextvar`, records `http_requests_total` and
  `http_latency_ms`, and logs `http_request`; exception handlers that turn `DocIntelError` into
  `{"error": {"type", "message"}, "request_id"}` and anything else into a generic 500.
  `app = create_app()` is the Uvicorn entry point.
- **Design decisions:** factory + injectable container so tests build apps with fault-injecting
  providers; unhandled errors never leak internals to clients.
- **Likely questions:** How do you correlate client errors with logs? Why a lifespan instead of
  module-level globals?

### `app/api/deps.py`
- **Responsibility:** Dependency-injection helpers and authentication/authorisation.
- **Depends on:** config (`Role`, API key map), errors, hashing, container.
- **Data in → out:** `X-API-Key` header → `Principal` (id, role, authenticated flag).
- **Key elements:** `get_container`; `get_principal` (constant-time `hmac.compare_digest` over
  configured keys; identity `key-<sha10>` so raw keys never appear in logs or audit);
  `require_role(minimum)`; `Annotated` aliases `ContainerDep`, `Viewer`, `Analyst`, `Reviewer`,
  `Admin`. With auth disabled every caller is `local-dev` with admin rights.
- **Design decisions:** role hierarchy by rank; actor strings like `api_key:key-…` go into the
  audit trail.
- **Likely questions:** Why hash the key for identity? What changes with OIDC?

### `app/api/schemas.py`
- **Responsibility:** Public request/response contracts.
- **Depends on:** domain enums and models.
- **Data in → out:** domain objects → API DTOs (`from_domain`), JSON bodies → validated requests.
- **Key elements:** `DocumentResponse`, `UploadResponse`, `ProcessResponse`,
  `ExtractionsResponse`, `AskRequest` (question 1–1000 chars, `top_k` 1–20, allow-listed
  `filters`: `document_type`, `extraction_method`), `AskResponse`, `ReviewResponse`,
  `ReviewDecisionRequest` / `ReviewCorrectionRequest` (`extra="forbid"`), `AuditResponse`,
  `AuditVerifyResponse`, `HealthResponse`, `ErrorResponse`.
- **Design decisions:** API DTOs are separate from domain models so internal fields (e.g.
  `workflow_id` on reviews) don't leak and the contract can evolve independently.
- **Likely questions:** Why forbid extra fields on requests? Why allow-list filter keys?

### `app/api/routes/documents.py`
- **Responsibility:** Document upload, listing, processing, extractions, Q&A, audit.
- **Depends on:** deps, schemas, errors; services via the container.
- **Endpoints:** `POST /documents/upload` (Analyst, 201; reads at most limit + 1 bytes),
  `GET /documents`, `GET /documents/{id}`, `POST /documents/{id}/process` (Analyst),
  `GET /documents/{id}/extractions` (latest + history), `POST /documents/{id}/ask` (Viewer),
  `POST /ask` (corpus-wide), `GET /documents/{id}/audit`.
- **Design decisions:** routes are thin; the upload handler is `async` only to read the stream,
  the rest are sync so blocking work runs in Starlette's threadpool.
- **Likely questions:** Why is processing synchronous? How would you make it 202 + polling?

### `app/api/routes/reviews.py`
- **Responsibility:** Human review queue endpoints.
- **Endpoints:** `GET /reviews` (filters: status, document_id, limit, offset), `GET /reviews/{id}`,
  `POST /reviews/{id}/approve|reject|correct` (Reviewer).
- **Key elements:** `_reviewer_id(principal, body)` — the authenticated identity wins over a
  client-supplied `reviewer_id`.
- **Likely questions:** How do you prevent reviewer impersonation?

### `app/api/routes/evaluations.py`
- **Responsibility:** Run and list evaluations.
- **Endpoints:** `GET /evaluations` (recent results), `POST /evaluations/run` (Admin) — runs
  `EvaluationRunner` in an isolated container, persists the result, audits
  `evaluation.completed`.
- **Likely questions:** Why isolate evaluation from the live data store?

### `app/api/routes/system.py`
- **Responsibility:** Health, metrics, drift, audit verification.
- **Endpoints:** `GET /health` (public; DB `SELECT 1`, vector-store health, provider names,
  OCR availability, `mock_mode`), `GET /metrics` (`format=json|prometheus`, includes DB totals),
  `GET /drift/report` (Viewer), `GET /audit/verify` (Admin).
- **Likely questions:** What should a health check verify, and what should it not expose?

---

## 2. Composition root

### `app/services/container.py`
- **Responsibility:** Build and hold every service, provider and repository.
- **Depends on:** nearly every package (it is the composition root).
- **Data in → out:** `Settings` (+ optional overrides) → `Container`.
- **Key elements:** `Container` dataclass (settings, engine, repositories, providers, gateway,
  classifier, extractor, chunker, indexer, retriever, workflow, reviews, rag, audit, metrics,
  drift…) with `close()`; `build_container(settings, llm=None, embedder=None, vector_store=None,
  ocr=_UNSET, retry_policy=None)`. Wires `HumanReviewService.set_reprocessor(workflow)` to break
  the review ↔ workflow cycle.
- **Design decisions:** one place to see the whole object graph; overrides make tests and the
  evaluation runner trivial; no global singletons.
- **Likely questions:** Why not a DI framework? How do you avoid circular dependencies?

---

## 3. Core utilities (`app/core`)

### `app/core/config.py`
- **Responsibility:** Typed runtime configuration.
- **Key elements:** provider enums (`LLMProviderName`, `EmbeddingProviderName`,
  `VectorStoreName`, `OCRProviderName`, `MetricsBackendName`), `Role` with `rank`, `Settings`
  (`DOCINTEL_` prefix; thresholds, chunking, retrieval, providers, auth, limits, paths) with
  validators (chunk overlap < size, strong score > min score, auth requires keys),
  `api_key_roles()`, `public_summary()` for `/health`, `get_settings()`.
- **Design decisions:** fail fast on inconsistent config; secrets as `SecretStr`; `.env` for local
  development only (tests pass `_env_file=None`).
- **Likely questions:** How do you keep secrets out of logs and repr?

### `app/core/errors.py`
- **Responsibility:** Domain exception hierarchy with `error_type` and `http_status`.
- **Key elements:** `DocIntelError`; `NotFoundError` (404) family; `InvalidDocumentError`,
  `EmptyDocumentError`; `OCRUnavailableError`; `ProviderError` (retryable flag) with timeout,
  response and configuration variants; `VectorStoreError` (503); `IllegalTransitionError` and
  `InvalidStateError` (409); `GuardrailViolationError`.
- **Likely questions:** Why map errors centrally rather than raising `HTTPException` in services?

### `app/core/hashing.py`
- **Key elements:** `sha256_bytes`, `sha256_text`, `stable_json` (sorted keys, compact),
  `stable_hash`, `short_hash`.
- **Design decisions:** canonical serialisation for audit and prompt hashes and collection names.

### `app/core/clock.py`
- **Key elements:** `utcnow()` (timezone-aware UTC), `new_id(prefix)` (`doc_…`, `wf_…`, `rev_…`).

### `app/core/registry.py`
- **Responsibility:** Load `config/document_types.yaml` (mock classifier keywords and extractor
  label synonyms).
- **Key elements:** `DocumentTypeConfig`, `DocumentTypeRegistry.load/get`.
- **Design decisions:** used only by the mock handlers; real providers get field descriptions
  from the Pydantic schemas. A test asserts every schema field has synonyms.

### `app/core/resilience.py`
- **Responsibility:** Timeout and retry primitives.
- **Key elements:** `RetryPolicy` (max_retries 2, backoff 0.5 s × 2ⁿ capped at 8 s),
  `call_with_timeout` (bounded thread pool + `future.result(timeout)`), `retry_call` (retries only
  retryable `ProviderError`s, calls `on_retry`), `CallOutcome`, `RetriesExhaustedError`.
- **Likely questions:** Can you cancel a thread on timeout? (No — hence SDK timeouts too.)

### `app/core/text.py`
- **Responsibility:** Text normalisation shared by extraction, groundedness and evaluation.
- **Key elements:** `normalize_ws`, `clean_line` (dot leaders), `normalize_number`
  (`(1,234.00)` → `-1234`), `extract_numbers`, `parse_amount`, `tokenize`/`content_tokens`
  (light stemming, stop words), `split_sentences`, `contains_normalized`.
- **Design decisions:** one normaliser used everywhere so "4,350,000.00" and "4350000" compare
  equal consistently.

---

## 4. Domain (`app/domain`)

### `app/domain/enums.py`
- **Key elements:** `DocumentType` (5 supported + `unknown`), `WorkflowStatus`,
  `ValidationStatus`, `ReviewStatus`, `ReviewTargetType`, `ReviewReason` (15 reasons),
  `TextExtractionMethod`, `Severity`.

### `app/domain/models.py`
- **Responsibility:** Pydantic domain model shared by services and persistence.
- **Key elements:** `Document`, `PageText`/`ExtractedText`, `ClassificationResult`, `Evidence`,
  `ExtractedEntity` (value, confidence, evidence, alternatives, validation status),
  `ValidationIssue`, `ExtractionResult` (with `corrected_by_review_id`), `Chunk`,
  `RetrievalResult`, `Citation`, `GroundednessReport`, `RAGAnswer`, `ReviewCase`, `AuditEvent`,
  `WorkflowState`/`WorkflowTransition`, `ModelInvocation`, `EvaluationResult`.
- **Design decisions:** results carry provider, model, prompt version and `is_mock` so every
  output is attributable.

---

## 5. Ingestion (`app/ingestion`)

### `app/ingestion/service.py`
- **Responsibility:** Validate and store uploads.
- **Data in → out:** filename, content type, bytes → `UploadOutcome(document, duplicate)`.
- **Key elements:** `sanitize_filename` (strips path components; display-only),
  `IngestionService.validate` (empty, size, `.pdf`, allowed content types, `%PDF` magic in the
  first 1 KB), `upload` (inspect PDF, page limits, SHA-256 de-dup, atomic store, audit
  `document.uploaded`, metrics and logs; rejections logged as `upload_rejected`).
- **Likely questions:** Why is the magic-byte check authoritative over the content type?

### `app/ingestion/pdf.py`
- **Key elements:** `PdfInspection` (page count, text layer, encrypted, active content,
  flags), `open_pdf`, `inspect_pdf` (byte scan for `/JavaScript`, `/JS`, `/Launch`,
  `/EmbeddedFile`), `PypdfTextExtractor`.
- **Design decisions:** active-content detection is an explicit heuristic; flagged, not blocked.

### `app/ingestion/extractors.py`
- **Responsibility:** Native text first, OCR fallback.
- **Key elements:** `DocumentTextExtractor` protocol; `TextExtractionService.extract` — uses the
  native layer when it averages ≥ 40 chars/page, otherwise OCR; raises `OCRUnavailableError`
  when OCR is needed but not configured; logs `ocr_fallback`.

---

## 6. AI steps

### `app/services/model_gateway.py`
- **Responsibility:** The only path to an LLM.
- **Data in → out:** prompt name + variables + response model → `GatewayResult[T]` (parsed
  object, raw text, invocation record).
- **Key elements:** `extract_json_object` (tolerates fences/prose), `ModelGateway.invoke` —
  render prompt, call provider with timeout + retries, parse, validate, one repair re-prompt,
  estimate cost, persist `ModelInvocation`, emit `model_invocation` log and `llm_*` metrics, raise
  typed errors on exhaustion.
- **Design decisions:** cross-cutting concerns in one place; business services stay
  provider-agnostic.
- **Likely questions:** Why only one repair attempt? How do you avoid nested retries?

### `app/prompts/registry.py`
- **Key elements:** `PromptSpec` (name, version, purpose, system/user templates, rendered via
  LangChain `PromptTemplate`; `hash` over the templates), `PromptRegistry.load/get/catalog`
  (latest version by semantic version unless pinned; duplicates rejected).
- **Likely questions:** What goes into the prompt hash, and why lock it in tests?

### `prompts/**.yaml`
- `classification/document_type.v1.yaml`, `extraction/financial_entities.v1.yaml`,
  `rag/grounded_answer.v1.yaml`, `validation/groundedness_judge.v1.yaml` — each declares that
  document/context text is untrusted data and requests a single JSON object.

### `app/classification/service.py`
- **Key elements:** `ClassificationLLMOutput`, `DocumentClassifier.classify` — bounded excerpt
  (`max_chars`), gateway call, unknown types mapped to `unknown`, `requires_review` when
  confidence < threshold.

### `app/extraction/schemas.py`
- **Responsibility:** Per-type field schemas — the single source of truth for field names,
  descriptions (rendered into the prompt), kinds and required flags.
- **Key elements:** `FieldKind` (text, amount, percent, date, currency, masked_account),
  `IncomeStatementFields`, `BalanceSheetFields`, `InvoiceFields`, `BankStatementFields`,
  `FundSummaryFields`, `SCHEMAS`, `FieldSpec`, `field_specs()`.

### `app/extraction/service.py`
- **Data in → out:** `Document` + `ExtractedText` → `ExtractionResult`.
- **Key elements:** `mask_account_number`, `coerce_field_value`, `_verify_evidence` (quote must
  appear in the cited page, whitespace-normalised), `EntityExtractor.extract` — gateway call,
  coercion, alternatives, evidence verification, validation, review reasons.

### `app/extraction/validation.py`
- **Key elements:** cross-field rules `check_balance_sheet`, `check_invoice`,
  `check_income_statement`, `check_bank_statement`, `check_fund_summary` (tolerance-based);
  `validate_field` (ISO currency, masked account, plausible date, percent range, numeric amount);
  `validate_extraction` (required fields, format, conflicting values, evidence not found).
- **Likely questions:** Why tolerances? How do reviewer corrections get validated? (Same
  functions.)

---

## 7. Retrieval and RAG

### `app/retrieval/chunking.py`
- **Key elements:** `Chunker.chunk` — PII-masks each page, splits with LangChain
  `RecursiveCharacterTextSplitter` (600/80, `add_start_index`), deterministic chunk IDs, metadata
  (`document_type`, `extraction_method`).

### `app/retrieval/indexer.py`
- **Key elements:** `Indexer.index` — delete a document's old chunks, embed in batches, upsert;
  `chunks_indexed_total`, `indexing_latency_ms`.

### `app/retrieval/retriever.py`
- **Key elements:** `Retriever.retrieve(question, document_id, top_k, filters)` → 
  `RetrievalOutcome` (results above `min_score`, `top_score`); retrieval metrics.

### `app/rag/service.py`
- **Responsibility:** Question answering with citations, groundedness and review routing.
- **Key elements:** `RAGLLMOutput`, `RAGSettings`, `best_snippet`, `RAGService.ask` — question
  check, document state checks (queryable; warnings for pending review or injection flag),
  retrieval, context assembly, gateway call, citation binding, groundedness, prohibited claims,
  confidence, `_refusal`/`_insufficient`/`_finalize` (persist, audit, metrics,
  `answer_generated` log, answer review cases).
- **Likely questions:** Walk me through a refusal path. How are invented citations handled?

### `app/rag/groundedness.py`
- **Key elements:** `check_groundedness(answer, evidence_texts, token_support_threshold=0.6)` →
  `GroundednessReport` (score, unsupported sentences and numbers).

---

## 8. Guardrails (`app/guardrails`)

### `app/guardrails/injection.py`
- **Key elements:** named regex patterns (ignore_instructions, role_override,
  prompt_exfiltration, new_instructions, markup_injection, payment_manipulation,
  suppress_review), `scan_for_injection` → `InjectionScanResult`.

### `app/guardrails/policy.py`
- **Key elements:** `check_question` (empty, > 1000 chars, injection), `find_prohibited_claims`
  (advice/guarantee phrases in answers).

### `app/guardrails/pii.py`
- **Key elements:** account-number regex (4+ digit groups ending in 4 digits, excluding
  identifiers like `INV-2025-0412` and decimals), IBAN and e-mail masking, `redact_text`,
  `redact_value` (credential-like keys → `[REDACTED]`, but not token counts).

---

## 9. Workflow and review

### `app/workflows/state_machine.py`
- **Key elements:** `ALLOWED_TRANSITIONS`, `IN_PROGRESS`, `QUERYABLE`, `can_transition`,
  `WorkflowStateMachine.transition` (validates, persists, appends history, audits).

### `app/workflows/orchestrator.py`
- **Responsibility:** Run the document pipeline deterministically.
- **Key elements:** `DocumentWorkflow.process`, `reprocess_with_type`, `_run` (extract text →
  injection scan → classify → extract → validate → index → decide), `_classify`, `_extract`
  (logs `extraction_validated`), `_open_review`, `_finish_review_early`, `_fail`, `_complete`.
- **Design decisions:** soft failures accumulate into one review case; hard failures go to
  `FAILED`; unexpected exceptions still move the document to `FAILED` before re-raising.

### `app/human_review/service.py`
- **Key elements:** `ReviewInputError` (422), `DocumentReprocessor` protocol,
  `HumanReviewService.create_case`, `list`, `get`, `supersede_pending_for_document`, `approve`,
  `reject`, `correct` (field corrections with schema coercion + `validate_field` +
  `validate_extraction`; `document_type` correction triggers reprocessing; answer corrections).
- **Likely questions:** What happens to pending cases when a document is reprocessed?
  (Superseded.) How are corrections versioned?

### `app/audit/service.py`
- **Key elements:** `_hash_event`, `AuditService.record` (redacts details, chains hashes),
  `history`, `verify_chain` → `(ok, first_broken_sequence)`.

---

## 10. Providers (`app/providers`)

### `app/providers/factory.py`
- `build_llm_provider`, `build_embedding_provider`, `build_vector_store`, `build_ocr_extractor`
  (`auto` → Tesseract if installed), `build_metrics` — selection by settings via `match`.

### `app/providers/llm/base.py`
- `LLMRequest`, `LLMResponse` (text, tokens, `tokens_estimated`, latency), `LLMProvider`
  protocol, `estimate_tokens`.

### `app/providers/llm/langchain_chat.py`
- `LangChainChatProvider` (invoke, usage extraction, error mapping), `BedrockClaudeProvider`
  (`ChatBedrockConverse`, `max_retries` disabled at the SDK level), `AzureOpenAIProvider`
  (`AzureChatOpenAI`, config validation). Both accept an injected `chat_model` for tests.

### `app/providers/llm/mock.py` and `mock_handlers.py`
- `MockLLMProvider` (handlers keyed by prompt name; `fail_first_n`, `malformed_first_n`,
  `delay_s`; records calls). Handlers: keyword-scored classification, label/regex extraction with
  evidence and alternatives, extractive RAG answers citing the best chunks, lexical groundedness
  judge. They read only the prompt content, never ground truth.

### `app/providers/embeddings/*`
- `EmbeddingProvider` protocol; `HashingEmbeddingProvider` (512-dim lexical);
  `LangChainEmbeddingProvider` with `bedrock_embeddings` and `azure_openai_embeddings` builders.

### `app/providers/vectorstore/*`
- `VectorStore` protocol and `MetadataFilterInput`; `ChromaVectorStore` (persistent client,
  cosine space, collection `chunks_<hash(model)>`, `$eq`/`$and` filters, errors →
  `VectorStoreError`); `InMemoryVectorStore` (cosine, filters, thread-safe).

### `app/providers/ocr/*`
- `TesseractOCRExtractor` (pypdfium2 render → pytesseract), `TextractOCRExtractor` (render →
  `detect_document_text` per page; client injectable).

### `app/providers/storage/local.py`
- `DocumentStore` protocol; `LocalDocumentStore` — only server-generated IDs accepted (regex),
  resolved-path check, atomic write (temp file → fsync → `os.replace`), `0o600` files in a
  `0o700` directory.

---

## 11. Persistence, observability, evaluation, drift

### `app/persistence/db.py` and `repositories.py`
- SQLAlchemy tables storing Pydantic JSON payloads plus indexed columns (status, document ID,
  SHA-256, timestamps). Repositories: documents (`list_page`, `find_by_sha256`), document texts,
  extractions (versions, latest), workflows, reviews (`search`), audit (`events`, append),
  invocations, answers, evaluations (`recent`).
- **Design decision:** JSON payload columns keep the schema simple while domain models evolve;
  a production Postgres schema would normalise hot query fields and add Alembic migrations.

### `app/observability/logging.py`
- `JsonFormatter` (adds request/document/workflow IDs from contextvars, redacts PII),
  `TextFormatter`, `configure_logging`, `log_event(logger, event, level, **fields)`.

### `app/observability/metrics.py`
- `MetricsRecorder` protocol, `InMemoryMetrics` (counters, bounded histograms, `snapshot`,
  `prometheus_text`), `OpenTelemetryMetrics` (also forwards to the OTel metrics API).

### `app/observability/cost.py`
- `CostEstimator.load(config_dir)` from `config/pricing.yaml`; `estimate(model, in, out)`; mock
  models cost 0.

### `app/evaluation/metrics.py`, `runner.py`, `gate.py`
- Metric functions (classification, extraction exact/normalised match, retrieval per query,
  context relevance, answer completeness/relevance); `EvaluationRunner.run(inspect=None)` builds an
  isolated in-memory container, processes all samples, runs retrieval and answer datasets,
  optional LLM judge, returns `EvaluationResult`; `evaluate_gate` applies thresholds and regression
  tolerance.

### `app/drift/monitor.py`
- `DriftThresholds.load`, `DriftSnapshot` (distributions, scalars, sample counts, versions),
  `psi`, `DriftMonitor.snapshot/compare/report`, `render_markdown`.

---

## 12. Scripts, config, data, tests

| Path | Purpose |
|---|---|
| `scripts/generate_sample_data.py` | Deterministically generates the 20 synthetic PDFs (reportlab; the scanned sample is rasterised) and `ground_truth.json` |
| `scripts/run_evals.py` | Runs the evaluation, writes `reports/eval_results.json`, `--update-baseline` |
| `scripts/quality_gate.py` | Applies thresholds + regression; non-zero exit on failure |
| `scripts/drift_report.py` | Markdown + JSON drift report; `--save-baseline` |
| `scripts/demo.py` | Live walkthrough against a running server (httpx) |
| `config/drift.yaml`, `config/pricing.yaml` | Drift thresholds; indicative model prices |
| `evals/thresholds.yaml`, `baseline.json`, `drift_baseline.json`, `datasets/*.jsonl` | Gate thresholds, regression and drift baselines, labelled questions |
| `tests/conftest.py`, `tests/support.py` | Fixtures (`container_factory`, `mock_llm_factory`), hermetic settings, PDF builders, `FakeTextract` |
| `tests/unit/*` | Pure logic, providers, gateway, guardrails, drift, prompt hash lock |
| `tests/integration/*` | Real workflow over samples, failure modes, review, RAG, OCR, evaluation runner |
| `tests/e2e/*` | FastAPI `TestClient`: every endpoint, auth and roles |
| `Dockerfile`, `docker-compose.yml`, `.github/workflows/ci.yml` | Non-root image with Tesseract; compose with read-only FS; CI quality + docker jobs |
