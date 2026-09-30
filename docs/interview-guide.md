# Interview guide — Financial Document Intelligence & Agentic Workflow Platform

How to explain this project in an interview, at three lengths, followed by a topic-by-topic
deep dive. Every topic answers the same six questions: **What** it is, **Why** it exists,
**How** it is implemented here (with file references), **What could fail**, **How the failure is
mitigated**, and **What to improve in production**.

Ground rule for the conversation: be precise about what is implemented, what is mocked and what
is only designed. The mock provider's perfect scores on synthetic data are a pipeline test, not
a model-quality claim — say so before anyone asks.

---

## 30-second explanation

> I built a document-intelligence platform for financial PDFs — invoices, bank statements,
> income statements, balance sheets and fund summaries. It extracts text (with OCR fallback),
> classifies the document, extracts typed fields with Pydantic schemas and business-rule
> validation, indexes the text for retrieval, and answers questions with citations. Every model
> call goes through one gateway with versioned prompts, retries and schema validation; the
> workflow is a deterministic state machine, and anything low-confidence, ungrounded or
> suspicious goes to a human review queue with a hash-chained audit trail. It runs fully offline
> in a deterministic mock mode and switches to Claude on Bedrock or Azure OpenAI by
> configuration. It has an evaluation harness with a CI quality gate, drift monitoring, and
> about 250 tests.

## 2-minute explanation

> The business problem is that operations teams re-key values from financial PDFs and answer
> questions about them by hand, and any automation has to be explainable and controllable.
>
> The architecture is a FastAPI modular monolith. A document is uploaded — size-capped,
> magic-byte checked, hashed for de-duplication — then processed by an explicit state machine:
> text extraction with pypdf, falling back to Tesseract or Textract for scans; classification
> by an LLM; structured extraction against a per-type schema defined in YAML; validation with
> rules like subtotal plus tax equals total and assets equal liabilities plus equity; and
> evidence checking, where each extracted value's quoted snippet must actually appear in the
> page text. Then it chunks the PII-masked text, embeds it and indexes it in Chroma.
>
> For Q&A, the RAG service screens the question for prompt injection, retrieves top-k chunks
> with a score threshold and metadata filters, calls the model with a grounded prompt that
> treats context as untrusted data, and only accepts citations that point at chunks it actually
> retrieved. A deterministic groundedness check requires every number in the answer to appear
> in the cited evidence. If evidence is insufficient it refuses rather than guesses.
>
> Anything uncertain — low confidence, failed rules, OCR, injection, weak grounding, provider
> failures after retries — becomes a review case that a reviewer approves, rejects or corrects;
> corrections are re-validated and versioned. Every transition and decision is written to a
> hash-chained audit log.
>
> Operationally: JSON logs with request and workflow IDs and PII masking, metrics in JSON and
> Prometheus format, an invocation ledger with tokens, latency and cost, an evaluation harness
> covering classification, extraction, retrieval, answers and routing with a regression gate in
> CI, and a PSI-based drift monitor.

## 10-minute walkthrough (suggested order)

1. **Problem and constraints (1 min)** — regulated context: accuracy, explainability,
   auditability, human control, vendor risk. These drove every design choice.
2. **Architecture diagram (1.5 min)** — README section 5. API → orchestrator → pipeline steps →
   vector store; RAG with guardrails; review queue; provider layer behind a gateway; operational
   layer. Point out the seams (`Protocol`s) and the single dependency container.
3. **Live demo or curl walk-through (2.5 min)** — `make dev` + `make demo`: upload an invoice →
   `READY` with six audited transitions; the scanned invoice → OCR → `NEEDS_REVIEW (ocr_used)`;
   the injection invoice → `guardrail_triggered`; ask "What is the amount due?" → cited answer;
   ask an unanswerable question → refusal; ask an injection question → blocked before retrieval.
4. **Model gateway (1 min)** — versioned + hashed prompts, timeout, bounded retries with
   backoff, JSON extraction + one repair re-prompt, Pydantic validation, invocation ledger.
   Provider swap is configuration only.
5. **Trust controls (1.5 min)** — evidence verification, validation rules, citation binding,
   deterministic groundedness, refusal, prohibited-claim filter, review routing, audit chain
   with `/audit/verify`.
6. **Quality (1.5 min)** — test pyramid (unit/integration/e2e, fault injection), evaluation
   metrics, thresholds and regression gate in CI, prompt-hash lock, drift monitor. Be explicit
   that mock scores validate the harness, not a model.
7. **Production gaps (1 min)** — synchronous processing → queue + workers; SQLite/embedded
   Chroma → Postgres/managed vector store; API keys → OIDC; no tracing yet; real-provider
   evaluation corpus needed.

---

## Topics

### 1. Business problem

- **What**: Automating reading, extraction and Q&A over financial PDFs for operations teams.
- **Why**: Manual re-keying is slow and error-prone; errors have financial and regulatory
  consequences; answers must be traceable.
- **How**: The platform produces typed, validated fields and cited answers, and routes
  uncertainty to humans (`app/workflows/orchestrator.py`, `app/rag/service.py`,
  `app/human_review/service.py`).
- **What could fail**: Automation that is confidently wrong; reviewers overwhelmed by false
  positives; users trusting answers without checking citations.
- **Mitigation**: Conservative thresholds, validation rules, groundedness checks, one
  consolidated review case per document, citations on every answer.
- **Production improvement**: Measure business KPIs (straight-through-processing rate, review
  time, correction rate, error escapes) and tune thresholds against them.

### 2. Architecture

- **What**: A FastAPI modular monolith with protocol-based seams for LLM, embeddings, vector
  store, OCR and storage.
- **Why**: One deployable unit is simple to run, test and explain, while the seams keep each
  dependency replaceable and make it possible to split into services later.
- **How**: `app/services/container.py` wires everything (`build_container`); `app/providers/factory.py`
  selects implementations from settings; routers depend only on the container.
- **What could fail**: A monolith couples scaling of API and heavy processing; a shared
  SQLite database limits concurrency.
- **Mitigation**: Processing is isolated in the orchestrator, so moving it to workers is a
  deployment change; persistence goes through repositories on SQLAlchemy.
- **Production improvement**: API service + queue-driven workers, Postgres, object storage,
  managed vector store.

### 3. Requirements translation

- **What**: Turning business needs into concrete technical controls.
- **Why**: "Must be explainable" or "must be auditable" are only meaningful when mapped to
  mechanisms that can be tested.
- **How**: Explainability → citations + evidence snippets + classification rationale.
  Auditability → hash-chained audit events for every transition and decision. Control → review
  routing with explicit reasons. Vendor risk → provider abstraction. Quality → evaluation gate.
- **What could fail**: Requirements satisfied on paper but not tested.
- **Mitigation**: Each control has tests (e.g. audit tampering detection, uncited numbers
  flagged, injection routed to review).
- **Production improvement**: Traceability matrix from requirement → control → test → evidence
  for model-risk and audit reviews.

### 4. Why document intelligence (vs. plain LLM chat)

- **What**: A pipeline that converts documents into structured, validated data and indexed
  evidence before any Q&A.
- **Why**: Downstream systems need typed fields, not prose; structured outputs can be
  validated; retrieval over indexed evidence enables citations.
- **How**: Classification → schema-driven extraction → validation → indexing, all persisted.
- **What could fail**: Schemas lag behind new document formats.
- **Mitigation**: Unknown types route to review; each schema is a small, declarative Pydantic
  model in `app/extraction/schemas.py`, so adding a type is a contained change.
- **Production improvement**: Schema versioning with migrations; analytics on unknown-type
  volume to prioritise new schemas.

### 5. OCR

- **What**: Optical character recognition for scanned PDFs without a text layer.
- **Why**: A meaningful share of financial documents are scans or faxes.
- **How**: `app/ingestion/extractors.py` uses native `pypdf` text first; if the text layer is too
  sparse it renders pages with `pypdfium2` and runs Tesseract (`app/providers/ocr/tesseract.py`)
  or AWS Textract `DetectDocumentText` (`app/providers/ocr/textract.py`). OCR use adds the
  `ocr_used` review reason; OCR unavailable ends in `NEEDS_REVIEW (ocr_unavailable)`. Verified in
  Docker: the scanned sample invoice extracted all eight fields correctly.
- **What could fail**: Misread digits (5 ↔ S, 0 ↔ O), lost table structure, skewed scans.
- **Mitigation**: OCR output always goes to review; validation rules catch arithmetic
  inconsistencies; numeric coercion rejects garbage.
- **Production improvement**: Textract `AnalyzeDocument` (tables/forms), image pre-processing
  (deskew, denoise), per-field OCR confidence feeding the review decision.

### 6. Classification

- **What**: Assigning a document type with confidence and rationale.
- **Why**: The type selects the extraction schema and validation rules.
- **How**: `app/classification/service.py` calls the gateway with
  `prompts/classification/document_type.v1.yaml` and validates into `ClassificationResult`.
  Unknown type or confidence < 0.70 (configurable) → review.
- **What could fail**: The model's self-reported confidence is not calibrated; similar types
  (income statement vs fund summary) get confused.
- **Mitigation**: Confidence is treated as a routing signal, not a probability; wrong types
  are fixed by a reviewer correcting `document_type`, which re-runs extraction.
- **Production improvement**: Calibrate on labelled data (reliability diagrams), or use a
  cheaper dedicated classifier with the LLM as fallback.

### 7. Structured extraction

- **What**: Extracting typed fields (amounts, dates, identifiers) with evidence.
- **Why**: Downstream systems need machine-readable values with provenance.
- **How**: `app/extraction/service.py` builds the field list from the registry, calls the
  gateway, coerces each value according to the field kind declared on the type's Pydantic model
  (`app/extraction/schemas.py`), verifies each evidence quote against the page text, masks
  account numbers, and runs rules from `app/extraction/validation.py`.
- **What could fail**: Hallucinated values, wrong field mapped, values present in the text but
  from the wrong row (e.g. prior-year column).
- **Mitigation**: Evidence verification (`unverified_evidence`), cross-field rules, conflicting
  values surfaced (`conflicting_values`), missing required fields routed to review.
- **Production improvement**: Layout-aware extraction (bounding boxes), per-field confidence
  calibration, field-level reviewer UI.

### 8. Why Pydantic

- **What**: Runtime data validation and serialisation via type annotations.
- **Why**: LLM output is untrusted input. Pydantic turns "looks like JSON" into "is a valid,
  typed object" or a clear error.
- **How**: Domain models (`app/domain/models.py`), API schemas (`app/api/schemas.py`),
  settings (`app/core/config.py`), and per-type extraction models. The gateway validates
  every response into a response model.
- **What could fail**: Over-permissive coercion (e.g. "1,000" silently becoming 1000 when it
  should be flagged); schema drift between prompt and model.
- **Mitigation**: Custom coercion for financial numbers and dates with explicit failure; prompt
  hash lock forces deliberate prompt changes.
- **Production improvement**: Publish JSON Schemas as versioned contracts to downstream
  consumers.

### 9. RAG (retrieval-augmented generation)

- **What**: Answering questions by retrieving relevant chunks and asking the model to answer
  only from them.
- **Why**: Keeps answers grounded in the actual documents, enables citations, and avoids
  fine-tuning on changing data.
- **How**: `app/rag/service.py`: input guardrail → retrieval → context assembly with chunk IDs →
  `rag.grounded_answer` prompt → JSON answer → citation binding (only retrieved IDs accepted)
  → groundedness → prohibited-claim check → confidence → answer, refusal or review.
- **What could fail**: Retrieval misses the right chunk; model ignores context; citations
  point at irrelevant chunks.
- **Mitigation**: Score threshold + refusal on no evidence; groundedness check; citation
  correctness evaluated; weak grounding routes to review.
- **Production improvement**: Hybrid search + re-ranking, query rewriting, answer-level user
  feedback loop.

### 10. Embeddings

- **What**: Vector representations of text used for similarity search.
- **Why**: Enables retrieval by meaning (with semantic models) or by terms (lexical).
- **How**: `EmbeddingProvider` protocol (`app/providers/embeddings/base.py`). Offline default:
  `HashingEmbeddingProvider` (512-dim hashed unigrams + bigrams, L2-normalised). Real:
  Bedrock Titan v2 or Azure `text-embedding-3-small` via LangChain adapters. Chroma collections
  are namespaced by embedding model hash, so changing models never mixes vector spaces.
- **What could fail**: Lexical embeddings miss synonyms; semantic embeddings blur exact
  numbers and identifiers; model changes invalidate the index.
- **Mitigation**: Collection-per-model; re-index on change; financial Q&A is term-heavy, so
  lexical works acceptably for the sample corpus.
- **Production improvement**: Semantic embeddings + BM25 hybrid; embedding-model version in
  the drift report; background re-indexing.

### 11. Vector databases

- **What**: Stores that index vectors for nearest-neighbour search with metadata filters.
- **Why**: Retrieval must be fast and filterable by document, type or tenant.
- **How**: `VectorStore` protocol with `ChromaVectorStore` (persistent, cosine space; similarity
  = 1 − distance) and `InMemoryVectorStore` (tests/eval). Upserts are idempotent by chunk ID;
  delete-by-document is supported.
- **What could fail**: Embedded Chroma is single-node; filters misconfigured → cross-document
  leakage.
- **Mitigation**: Filter keys are allow-listed at the API; per-document queries always filter
  by `document_id`; failures raise `VectorStoreError` (HTTP 503, workflow `FAILED`).
- **Production improvement**: Managed store (OpenSearch, pgvector) with mandatory tenant
  filters enforced server-side.

### 12. Chunking

- **What**: Splitting page text into overlapping pieces for embedding.
- **Why**: Chunk size trades recall against precision and context cost.
- **How**: `app/retrieval/chunking.py` uses LangChain's `RecursiveCharacterTextSplitter` per page
  (600 chars, 80 overlap) on PII-masked text; chunk IDs are content hashes; metadata carries
  page, type and extraction method. ADR-005 records a sweep: smaller chunks lowered MRR because
  labels and values were split apart.
- **What could fail**: Tables split mid-row; context lost across pages.
- **Mitigation**: Page-aware chunking keeps citations exact; overlap preserves boundary
  context.
- **Production improvement**: Structure-aware chunking (tables as units, section headers as
  metadata), parent-document retrieval.

### 13. Retrieval strategy

- **What**: How candidate chunks are selected for a question.
- **Why**: The answer can only be as good as the retrieved evidence.
- **How**: `app/retrieval/retriever.py`: embed the question, query top-k (default 4) with
  filters, drop results below `retrieval_min_score` (0.12); `retrieval_strong_score` feeds the
  confidence heuristic.
- **What could fail**: Threshold too high → false refusals; too low → noisy context.
- **Mitigation**: Thresholds are evaluated (false-refusal rate 0.167 on the mock set is visible
  in the report); settings are configurable.
- **Production improvement**: Tune thresholds per embedding model on a labelled set; add
  re-ranking; MMR for diversity.

### 14. Metadata filtering

- **What**: Restricting retrieval by attributes like document ID or type.
- **Why**: Precision, and more importantly isolation — a question about one document must not
  pull evidence from another.
- **How**: `/documents/{id}/ask` always filters by `document_id`; `/ask` accepts allow-listed
  keys (`document_type`, `extraction_method`); unknown keys → 422.
- **What could fail**: A missing filter leaks data across documents or tenants.
- **Mitigation**: Allow-list at the schema; tests assert filtered retrieval only returns the
  target document.
- **Production improvement**: Tenant ID as a mandatory, server-injected filter.

### 15. Citations

- **What**: References from answer to source chunk, page and snippet.
- **Why**: Users and auditors must be able to verify any answer.
- **How**: The model returns chunk IDs; the service accepts only IDs that were retrieved,
  discards others (with a warning), and picks the best-matching snippet from each chunk
  (`best_snippet`). Each citation carries document ID, page, chunk ID, snippet and score.
- **What could fail**: Model cites an unrelated chunk or invents IDs.
- **Mitigation**: ID binding rejects invented IDs; citation correctness is an evaluation metric.
- **Production improvement**: Character-offset highlighting in a viewer; sentence-level
  citation alignment.

### 16. Hallucination mitigation

- **What**: Preventing or catching model statements not supported by evidence.
- **Why**: A fabricated figure in finance is a material error.
- **How**: Layered: grounded prompt; refusal when retrieval is empty; citation binding;
  deterministic groundedness (numbers must appear in evidence, ≥ 60% token support per
  sentence); evidence verification for extraction; validation rules; review routing.
- **What could fail**: Paraphrased but wrong statements pass lexical checks; correct
  paraphrases ("4.35 million") are flagged.
- **Mitigation**: Unsupported numbers are the strictest check; optional LLM judge in
  evaluation; low groundedness goes to review rather than being silently returned.
- **Production improvement**: NLI-based entailment check, calibrated judge, numeric
  normalisation for scale words.

### 17. Guardrails

- **What**: Input and output policies around model use.
- **Why**: Defence against misuse, prompt injection and inappropriate outputs.
- **How**: `app/guardrails/injection.py` (patterns such as ignore-instructions, role override,
  prompt exfiltration, markup injection, payment manipulation, suppress-review);
  `app/guardrails/policy.py` (question checks, prohibited financial-advice claims);
  `app/guardrails/pii.py` (masking in logs and chunks). Questions are screened before retrieval;
  document text is scanned during processing.
- **What could fail**: Pattern-based detection misses novel phrasing; false positives on
  legitimate text.
- **Mitigation**: Defence in depth — even if injection text passes, prompts treat content as
  data, outputs are schema-validated and grounded, and actions are never taken by the model.
- **Production improvement**: A classifier-based injection detector (e.g. Bedrock Guardrails
  or a fine-tuned model), red-team test suite, output moderation.

### 18. Human-in-the-loop

- **What**: Routing uncertain outputs to people who approve, reject or correct.
- **Why**: Residual risk must be controlled by accountable humans, and their decisions are the
  best training and evaluation signal.
- **How**: `app/human_review/service.py`. One consolidated case per document with all reasons;
  answer-level cases from RAG. Corrections are coerced by the schema, re-validated (422 on
  invalid), stored as a new extraction version; correcting the type re-runs extraction. Only
  `pending` cases can be resolved (409 otherwise). With auth, reviewer identity comes from the
  API key.
- **What could fail**: Review fatigue; rubber-stamping; reviewer error.
- **Mitigation**: Specific reasons and details on each case; metrics for review rate and
  resolution time; audit of every decision.
- **Production improvement**: Maker-checker for high-value items, sampling of auto-approved
  documents for QA, reviewer UI with page highlighting.

### 19. Bedrock

- **What**: AWS's managed service for foundation models.
- **Why**: Data stays within the AWS account and region; IAM-based access; no key management
  for the model API.
- **How**: `BedrockClaudeProvider` in `app/providers/llm/langchain_chat.py` wraps
  `ChatBedrockConverse` (`model_id`, temperature 0, max tokens, timeout). Credentials via the
  AWS chain. Titan v2 embeddings via `BedrockEmbeddings`.
- **What could fail**: Throttling, model-access not enabled, regional availability.
- **Mitigation**: Bounded retries with exponential backoff; `ProviderConfigurationError` at
  start-up; errors classified and logged; `retries_exhausted` routes to review.
- **Production improvement**: Provisioned throughput for predictable latency, cross-region
  inference profiles, Bedrock Guardrails.

### 20. Claude

- **What**: Anthropic's model family, the primary LLM here via Bedrock.
- **Why**: Strong instruction following, long context and reliable JSON output for extraction.
- **How**: Used for classification, extraction, answering and (optionally) judging. Prompts
  ask for one JSON object; the gateway extracts and validates it.
- **What could fail**: Occasional prose around JSON; refusals on benign content; version changes
  shift behaviour.
- **Mitigation**: JSON extraction + repair re-prompt; version recorded on every output; drift
  monitor flags model version changes.
- **Production improvement**: Use native tool/structured output features; pin model versions
  and re-baseline on upgrade.

### 21. Azure OpenAI abstraction

- **What**: A second provider behind the same interface.
- **Why**: Vendor diversification, customer or region requirements, fallback.
- **How**: `AzureOpenAIProvider` wraps `AzureChatOpenAI`; config validated at construction;
  selected by `DOCINTEL_LLM_PROVIDER=azure_openai`. No business code changes.
- **What could fail**: Different JSON habits and token accounting; quality differences.
- **Mitigation**: The gateway normalises output handling; the evaluation harness runs unchanged
  per provider.
- **Production improvement**: Automatic failover policy with per-provider baselines and
  cost-aware routing.

### 22. Agentic workflow

- **What**: A multi-step workflow where AI performs steps (classify, extract, answer) and the
  system decides what happens next.
- **Why**: Documents need several dependent AI steps with checks between them.
- **How**: The "agent" is the orchestrator: fixed steps with LLM-powered components, explicit
  decision points (OCR needed? safe? trustworthy? valid? grounded?), and escalation to humans.
  The model never chooses tools or control flow.
- **What could fail**: Rigid flows can't handle novel tasks.
- **Mitigation**: Unknown situations route to review instead of improvising.
- **Production improvement**: Bounded tool use (e.g. a lookup against a vendor master) inside a
  step, with the same validation and audit — not an open-ended loop.

### 23. Deterministic orchestration

- **What**: Control flow defined by code and a transition table, not by a model.
- **Why**: Enumerable paths are testable and explainable to auditors; failures are reproducible.
- **How**: `app/workflows/state_machine.py` (`ALLOWED_TRANSITIONS`; illegal moves raise
  `IllegalTransitionError`, 409); every transition audited; the orchestrator collects soft
  failures and opens one review case. ADR-004.
- **What could fail**: A crash mid-workflow leaves a document in an in-progress state.
- **Mitigation**: Unexpected errors move the document to `FAILED` with the error recorded; a
  retry transitions `FAILED → INGESTED`.
- **Production improvement**: Durable workflow engine (Step Functions, Temporal) for retries,
  timeouts and resumability.

### 24. Model evaluation

- **What**: Measuring model-driven steps against labelled data.
- **Why**: Model changes must be justified by evidence, and regressions caught before release.
- **How**: `app/evaluation/runner.py` + `metrics.py`: classification accuracy/macro-F1/confusion
  matrix; extraction field accuracy, normalised match, missing/hallucinated/invalid rates;
  workflow routing accuracy and review precision/recall.
- **What could fail**: Small, synthetic datasets overstate quality.
- **Mitigation**: Honest reporting; the harness is provider-agnostic so real data plugs in.
- **Production improvement**: Representative labelled corpus, confidence intervals, slice
  analysis by layout and source.

### 25. RAG evaluation

- **What**: Measuring retrieval and answer quality separately.
- **Why**: Distinguishes "didn't find it" from "found it but answered badly".
- **How**: Retrieval: precision@k, recall@k, hit rate, MRR, document hit rate, context
  relevance. Answers: completeness, groundedness, citation correctness, relevance,
  unsupported-statement rate, schema validity, correct and false refusal rates. Optional LLM
  judge.
- **What could fail**: Lexical metrics miss semantic correctness.
- **Mitigation**: Multiple complementary metrics; failing cases (a04, a11, a12) kept visible.
- **Production improvement**: Human-graded answer sets, judge calibration against humans.

### 26. Test harness

- **What**: The pytest suite plus fixtures that build real containers with controllable fakes.
- **Why**: Fast, deterministic tests for every layer, including failure modes.
- **How**: `tests/conftest.py` (`container_factory`, `mock_llm_factory`), `tests/support.py`
  (settings, PDF builders, `FakeTextract`); markers auto-assigned by folder.
- **What could fail**: Mocks drift from real provider behaviour.
- **Mitigation**: LangChain adapters are tested with LangChain's own fake chat models; the mock
  implements the same interface; real-provider smoke tests are a roadmap item.
- **Production improvement**: Contract tests against live providers in a scheduled pipeline.

### 27. Regression testing

- **What**: Guarding previously correct behaviour.
- **Why**: Prompt or model tweaks often fix one case and break another.
- **How**: Evaluation baseline (`evals/baseline.json`) with 0.03 tolerance; prompt hash lock
  (`tests/fixtures/prompt_hashes.json`); integration tests pin routing and fields per sample.
- **What could fail**: Baselines updated carelessly.
- **Mitigation**: `make baseline` is a separate, explicit step documented as "only after
  reviewing an intentional change".
- **Production improvement**: Baseline changes require PR review with the diff of metrics.

### 28. Quality gates

- **What**: Automated pass/fail criteria before merge or release.
- **Why**: Objective, repeatable release decisions.
- **How**: `scripts/quality_gate.py` applies `evals/thresholds.yaml` (e.g. groundedness ≥ 0.90,
  hallucinated field rate ≤ 0.10, schema validity = 1.0) and regression checks; CI fails on any
  breach, lint error, type error or test failure.
- **What could fail**: Thresholds set too low to matter, or too high to be met by real models.
- **Mitigation**: Separate thresholds/baselines per provider are recommended in the config.
- **Production improvement**: Gate on real-provider evaluation for release candidates.

### 29. MLOps

- **What**: Practices for operating ML/LLM systems: versioning, evaluation, deployment,
  monitoring.
- **Why**: LLM behaviour changes with prompts, models and data.
- **How**: Versioned + hashed prompts, model/prompt versions recorded on every output and
  invocation, evaluation + gate in CI, drift monitor, invocation ledger with cost.
- **What could fail**: Untracked prompt edits, silent model upgrades.
- **Mitigation**: Prompt hash lock; version change surfaced by drift report.
- **Production improvement**: Prompt/model registry with approvals, shadow and canary rollout.

### 30. CI/CD

- **What**: Automated build, test and (eventually) deploy.
- **Why**: Every change validated the same way.
- **How**: `.github/workflows/ci.yml`: quality job (ruff, format, mypy strict, unit/integration/e2e,
  evals, gate, artifact upload) and docker job (build, run, health check). Installs from
  `requirements.lock`.
- **What could fail**: Environment drift between CI and production.
- **Mitigation**: Locked dependencies; same Docker image for CI smoke test and runtime.
- **Production improvement**: Image signing, SBOM, vulnerability scanning, environment
  promotion, CD with approval gates.

### 31. Observability

- **What**: Logs, metrics (and traces) that explain system behaviour.
- **Why**: Debugging, SLOs, cost control, audit support.
- **How**: JSON logs with request/document/workflow IDs via `contextvars`
  (`app/observability/logging.py`); metrics recorder (in-memory, OTel API, Prometheus text);
  invocation ledger; `/metrics` and `/health`.
- **What could fail**: Logs leaking PII; missing correlation IDs.
- **Mitigation**: Logging filter masks PII and redacts credential keys; document text is never
  logged; request IDs propagated and returned.
- **Production improvement**: OTel tracing, exporter, dashboards, SLO alerts.

### 32. Drift

- **What**: Changes over time in inputs, outputs or operations that may degrade quality.
- **Why**: A model can degrade silently as the document mix changes or providers update models.
- **How**: `app/drift/monitor.py`: PSI over type mix and confidence distributions; rate deltas
  (review, rejection, correction, schema failure, unsupported answers, refusals); ratios for
  latency, tokens and cost; version changes; `insufficient_data` below 5 samples.
- **What could fail**: Alert noise from small samples; drift detected without a remedy.
- **Mitigation**: Sample gating; thresholds in `config/drift.yaml`; report explains each metric.
- **Production improvement**: Scheduled job, alert routing, drift-triggered re-evaluation.

### 33. Security

- **What**: Protection of the service, data and model interactions.
- **Why**: Financial documents are sensitive; LLM systems add injection risk.
- **How**: Optional API-key auth with roles; upload validation; atomic writes with generated
  names; prompt-injection defences; non-root, read-only container; secrets only from env.
- **What could fail**: API keys leaked; injection bypass; unauthenticated default mode exposed.
- **Mitigation**: Constant-time comparison; auth required to be configured when enabled;
  documented that local mode is unauthenticated.
- **Production improvement**: OIDC, WAF, rate limits, malware scanning, secrets manager.

### 34. Privacy

- **What**: Minimising and protecting personal and financial data.
- **Why**: Legal obligations and customer trust.
- **How**: PII masking in logs and in indexed chunks; account numbers masked in extraction
  results; answers and document text not logged. ADR-009 documents what is not protected
  (raw text at rest, text sent to the model provider).
- **What could fail**: Regex-based PII detection misses formats.
- **Mitigation**: Tests for masking including false-positive cases (invoice numbers, amounts).
- **Production improvement**: Named-entity-based PII detection, encryption at rest, retention
  enforcement, data-residency pinning.

### 35. Scalability

- **What**: Handling growth in documents, users and questions.
- **Why**: Batch uploads (month-end) create bursts.
- **How today**: Single process, synchronous processing, SQLite, embedded Chroma — suitable for a
  demo or small team.
- **What could fail**: Request timeouts on large documents; SQLite write contention.
- **Mitigation**: Components are stateless apart from storage; seams allow replacement.
- **Production improvement**: Queue + autoscaled workers, Postgres, managed vector store,
  provider concurrency limits.

### 36. Cost

- **What**: Model, embedding and infrastructure spend.
- **Why**: LLM cost scales with tokens and volume.
- **How**: Every invocation records tokens and an estimated cost from `config/pricing.yaml`;
  metrics and drift track cost per call.
- **What could fail**: Price table out of date; prompt growth silently increases cost.
- **Mitigation**: Tokens-per-call drift ratio alert (1.5×).
- **Production improvement**: Budgets and alerts per tenant, caching of classification by
  content hash, smaller models for simpler steps.

### 37. Latency

- **What**: Time to process a document or answer a question.
- **Why**: Interactive Q&A needs seconds; batch processing needs throughput.
- **How**: Latency histograms for HTTP, LLM, retrieval, indexing and workflows; timeouts on every
  provider call.
- **What could fail**: Retries multiply latency; OCR is slow.
- **Mitigation**: Bounded retries with capped backoff; OCR only when needed.
- **Production improvement**: Async processing, streaming answers, parallel page OCR.

### 38. Failure modes

- **What**: The ways the system can break.
- **Why**: Designing for failure is essential in regulated contexts.
- **How**: Tested explicitly (`tests/integration/test_failure_modes.py`): malformed model JSON
  (repair then review), provider outage (retries then `retries_exhausted` review), timeouts,
  empty/malformed/encrypted PDFs, OCR unavailable, vector-store failure (`FAILED`), illegal
  transitions (409), duplicate uploads (de-duplicated).
- **What could fail**: Unanticipated exceptions.
- **Mitigation**: Catch-all moves the workflow to `FAILED` and re-raises; uniform error envelope
  with request ID.
- **Production improvement**: Dead-letter queues, chaos testing, runbooks.

### 39. Production deployment

- **What**: Running the platform for real users.
- **How today**: Docker image (non-root, read-only FS, health check, Tesseract included) and
  docker compose; CI builds and smoke-tests the image.
- **What could fail**: Single container is a single point of failure; local volume storage.
- **Mitigation**: Stateless API design apart from storage.
- **Production improvement**: ECS/EKS behind an ALB with TLS, RDS, S3 + KMS, managed vector
  store, secrets manager, private networking to Bedrock (VPC endpoints).

### 40. Trade-offs

- **What**: The deliberate compromises and why they were made.
- **How**: Deterministic state machine over autonomous agents (auditability over flexibility);
  LangChain only as adapters (breadth without lock-in); synchronous processing (simplicity over
  throughput); lexical groundedness (explainable, cheap, but paraphrase-blind); hashing
  embeddings offline (deterministic, but lexical); one review case per document (context over
  granularity).
- **What could fail**: Trade-offs that are right for a demo become wrong at scale.
- **Mitigation**: Each is recorded in an ADR with the conditions under which to revisit it.
- **Production improvement**: Revisit async processing, semantic retrieval and entailment-based
  groundedness first.
