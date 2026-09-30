# Project completion report — fin-docintel

Date: 2026-09-30 · Version: 0.1.0 · Python 3.12.14

## 1. Executive summary

`fin-docintel` is a runnable, tested Financial Document Intelligence & Agentic Workflow Platform.
It ingests financial PDFs, extracts text (with Tesseract or Textract OCR fallback), classifies
documents, extracts typed and validated fields with verified evidence, indexes PII-masked chunks
in a vector store, answers questions with citations and deterministic groundedness checks,
routes uncertainty to a human review queue, and records every step in a hash-chained audit trail.
It ships with an evaluation harness plus CI quality gate, drift monitoring, structured
observability, Docker packaging and GitHub Actions CI.

Everything runs offline in a clearly labelled, deterministic mock mode; AWS Bedrock (Claude) and
Azure OpenAI are real integrations selected by configuration. They are implemented and
unit-tested with fakes, but were **not** exercised against live cloud endpoints in this
environment (no credentials).

Final validation (this run): **255 tests passed, 1 skipped** locally (the skipped Tesseract test
passes in the Docker image, which ships Tesseract), **94% line coverage**, ruff lint and format
clean, **mypy `--strict` clean on 87 files**, **quality gate PASSED (27 checks)**, live demo against
Uvicorn completed, Docker image built and smoke-tested (healthy, non-root, real OCR).

## 2. Architecture

A FastAPI modular monolith with protocol-based seams at every external dependency:

- **API** (`app/api`) — routers, DTOs, API-key auth with roles, request-ID middleware, error
  envelope.
- **Orchestrator** (`app/workflows`) — deterministic state machine (`INGESTED → TEXT_EXTRACTED →
  CLASSIFIED → ENTITIES_EXTRACTED → VALIDATED → INDEXED → READY | NEEDS_REVIEW`, plus `FAILED`,
  `REJECTED`); every transition audited; the LLM never decides control flow.
- **Domain services** — ingestion, classification, extraction + validation, retrieval, RAG,
  guardrails, human review, audit, evaluation, drift.
- **Model gateway** — the only path to an LLM: versioned + hashed prompts, timeout, bounded
  retries, JSON extraction + one repair re-prompt, Pydantic validation, invocation ledger with
  tokens, latency and estimated cost.
- **Providers** — LLM (mock / Bedrock / Azure), embeddings (hashing / Titan / Azure), vector store
  (Chroma / in-memory), OCR (Tesseract / Textract), storage (local, atomic writes).
- **Persistence** — SQLAlchemy 2 over SQLite (any SQLAlchemy URL).
- **Operations** — JSON logs with PII masking, metrics (in-memory, OpenTelemetry API, Prometheus
  text), audit chain, evaluation + gate, drift monitor.

The Mermaid diagram is in README section 5; the decisions behind it are in `docs/adr/ADR-001` to `ADR-009`.

## 3. Features implemented

| Area | Implemented |
|---|---|
| Upload | size cap enforced while reading, `.pdf` + content-type + `%PDF` magic checks, page limit, encrypted / active-content flags, SHA-256 de-duplication, generated storage names, atomic writes |
| Text extraction | pypdf per page; OCR fallback when < 40 chars/page; Tesseract and Textract providers; OCR routes to review |
| Classification | LLM + versioned prompt, confidence threshold 0.70, unknown → review |
| Extraction | 5 per-type Pydantic schemas, typed coercion, evidence verification against page text, alternatives / conflict detection, account masking |
| Validation | per-field (ISO currency, date plausibility, percent range, numeric, masked account) and cross-field rules (invoice total, balance-sheet identity, income-statement consistency, bank reconciliation, fund fee range) |
| Indexing | PII-masked, page-aware chunking (600/80), deterministic chunk IDs, idempotent re-indexing, embedding-model-namespaced Chroma collections |
| RAG | input guardrail, top-k + threshold + allow-listed filters, grounded JSON answer, citation binding to retrieved chunks, deterministic groundedness, prohibited-claims filter, heuristic confidence, refusal, answer review |
| HITL | consolidated review cases with 15 reason codes; approve / reject / correct; corrections schema- and rule-validated (422 on invalid); type correction re-runs extraction; versioned corrected extractions |
| Audit | SHA-256 hash chain, per-document history, `/audit/verify` |
| Observability | JSON logs with request/document/workflow IDs, PII masking and credential redaction; ~20 counters and 6 histograms; Prometheus text; OTel metrics API adapter; health checks with 503 on degradation |
| Evaluation | classification, extraction, retrieval, answer and workflow metrics; optional LLM judge; thresholds + regression gate vs baseline |
| Drift | PSI (type mix, confidence distributions), rate deltas, operational ratios, version changes, sample-size gating |
| Security | optional API-key auth (viewer < analyst < reviewer < admin), reviewer identity from the key, secrets via env only, non-root read-only container |
| Endpoints | all 15 required endpoints (see README), plus `GET /documents`, `POST /ask`, `GET /drift/report`, `GET /audit/verify` |

## 4. Exact technology choices

Python 3.12.14 · FastAPI 0.142.2 · Uvicorn 0.54.0 · Pydantic 2.13.5 · pydantic-settings 2.15.0 ·
SQLAlchemy 2.0.54 · pypdf 5.9.0 · pypdfium2 5.13.0 · pytesseract 0.3.13 (Tesseract in Docker) ·
chromadb 1.5.9 · langchain-core 0.3.86 · langchain-text-splitters 0.3.11 · langchain-aws 0.2.35
(`ChatBedrockConverse`, `BedrockEmbeddings`) · langchain-openai 0.3.35 (`AzureChatOpenAI`,
`AzureOpenAIEmbeddings`) · boto3 1.43.105 (Textract) · opentelemetry-api 1.45.0 · pytest 9.1.1 ·
ruff 0.16.9 · mypy 2.3.1 · reportlab 5.0.1 (synthetic PDFs). Dependencies are pinned in
`requirements.lock` (uv, universal, Python 3.12).

LangChain is used only as an integration layer (adapters, `PromptTemplate`,
`RecursiveCharacterTextSplitter`); orchestration is our own state machine (ADR-001).

## 5. External integrations

| Integration | Status | Verification |
|---|---|---|
| AWS Bedrock — Claude chat | Implemented (`BedrockClaudeProvider`) | unit-tested with LangChain fake chat models; not called live |
| AWS Bedrock — Titan embeddings | Implemented | construction/config tested; not called live |
| Azure OpenAI — chat + embeddings | Implemented, config validated at start-up | unit-tested with fakes; not called live |
| AWS Textract OCR | Implemented (`TextractOCRExtractor`) | integration test with a stubbed Textract client exercising real rendering + line assembly |
| Tesseract OCR | Implemented | real OCR verified in the Docker image: scanned invoice → all 8 fields match ground truth |
| Chroma | Implemented (persistent) | used in Docker/live runs and tests |
| OpenTelemetry | Metrics API adapter | no exporter/MeterProvider configured by the app; tracing not implemented |

## 6. Mock behaviour

`MockLLMProvider` implements the same `LLMProvider` interface and goes through the same gateway
(prompt rendering, JSON parsing, validation, retries, ledger). Handlers keyed by prompt name derive
output **from the prompt content only** (keyword-scored classification, label/regex extraction with
evidence, extractive answers citing retrieved chunks, lexical judge); they never read ground
truth. Fault injection: `fail_first_n`, `malformed_first_n`, `delay_s`. Embeddings default to a
lexical hashing vectoriser. Every response and log line is labelled (`is_mock`, `mock_mode`,
`model_provider: "mock"`). Mock scores validate the pipeline, not model quality.

## 7. Tests executed

| Suite | Tests | Result |
|---|---|---|
| Unit (`tests/unit`) | 153 | passed |
| Integration (`tests/integration`) | 88 | 87 passed, 1 skipped locally (`requires_tesseract`) |
| End-to-end API (`tests/e2e`) | 15 | passed |
| **Total** | **256** | **255 passed, 1 skipped · 94% coverage (app)** |

Static checks: `ruff check` and `ruff format --check` clean (app, scripts, tests); `mypy --strict`
clean (87 source files). Additional manual validation in this run: live Uvicorn + `scripts/demo.py`
(no 5xx; the two 422s are intentional malformed-upload rejections), Docker build + container smoke
test (health, OCR, review details, logs), and a privacy scan confirming no account numbers,
question text or document lines appear in logs, audit events, review cases or indexed chunks.

## 8. Evaluation results (mock mode, deterministic)

| Area | Results |
|---|---|
| Classification (n=17) | accuracy 1.00, macro-F1 1.00 |
| Extraction (122 fields) | exact 1.00, normalised 1.00, missing 0.00, hallucinated 0.00, invalid 0.00 |
| Retrieval (16 queries, k=4) | precision@k 0.266, recall@k 1.00, hit rate 1.00, MRR 0.958, document hit 1.00, context relevance 0.523 |
| Answers (16 cases) | completeness 0.75, groundedness 1.00, citation correctness 1.00, relevance 0.917, unsupported 0.00, schema validity 1.00, correct refusal 1.00, false refusal 0.167 |
| Workflow (20 documents) | routing accuracy 1.00, review precision 1.00, review recall 1.00 |

Quality gate: **PASSED (27 checks)**, regression tolerance 0.03 against `evals/baseline.json`.
Interpretation: synthetic data and mock rules were built together, so perfect
classification and extraction scores demonstrate harness correctness only. The honest signals are
the visible failures (answer cases a04, a11, a12; false refusals; low precision@k from lexical
retrieval) and the fact that the same harness runs unchanged on real providers (ADR-006).

## 9. CI/CD status

`.github/workflows/ci.yml` defines two jobs: **quality** (Tesseract install, lock install, ruff,
format check, mypy, unit, integration, e2e, offline evaluation, quality gate, report artifact)
and **docker** (build, run, health smoke test, logs). Every command in these jobs was executed
locally and passed, and the workflow's first run on GitHub passed both jobs
([run 36735688189](https://github.com/zamanmaruf/Financial_Document_Intelligence-Agentic_Workflow_Platform/actions/runs/36735688189)). CD (registry
push, promotion, deployment) is intentionally not implemented.

## 10. Security

Implemented: env-only secrets (`SecretStr`), git- and docker-ignored `.env`, AWS credential
chain; optional API-key auth with constant-time comparison and role hierarchy; key-derived
reviewer identity (no impersonation); upload validation and safe storage (generated IDs, resolved
path checks, atomic writes, restrictive permissions); prompt-injection defence in depth
(question screening, document scanning → review, untrusted-data prompts, schema validation,
citation binding, groundedness, no model-initiated actions); PII masking in logs, chunks and
extracted account numbers; hash-chained audit; non-root, read-only container with
`no-new-privileges`.

Not implemented (documented in ADR-009 and README section 21): encryption at rest, TLS termination,
retention/deletion policies and endpoints, data-residency enforcement, multi-tenancy, SSO/OIDC,
rate limiting, malware scanning. Raw document text is stored unmasked and sent in full to the
configured model provider. No regulatory certification is claimed.

## 11. Observability

Structured JSON logs with correlation IDs (`http_request`, `model_invocation`, `llm_retry`,
`document_uploaded`, `upload_rejected`, `ocr_fallback`, `text_extraction_warnings`,
`extraction_validated`, `answer_generated`, `review_created`, `workflow_completed`,
`workflow_failed`, `request_error`); a persisted model-invocation ledger; `/metrics` in JSON or
Prometheus format; drift reports via API and script; `/health` returning 503 when degraded.

## 12. Principal-engineer review — issues found and fixed in the final pass

| Finding | Fix |
|---|---|
| Credential-key redaction matched "token" in `input_tokens`, hiding token counts in logs | precise credential pattern; parametrised tests (11 cases) |
| Unpriced models reported $0 cost (silently understating spend) | cost is `null` when unknown; `llm_unpriced_calls_total` metric; drift ignores unknown costs; test |
| `/health` returned 200 when degraded, so probes never failed | 503 on dependency failure, DB error logged; e2e test |
| Per-page extraction and OCR warnings were never surfaced | added to review details and logged (`text_extraction_warnings`); duplicate OCR detail removed; test |
| Active-content test corrupted the PDF xref | test builds real JavaScript + attachment with pypdf |
| Docs claimed schemas were built from YAML, a nonexistent `source` field, wrong filter keys, wrong dataset size, question-level advice blocking, a date-to-ISO conversion | all corrected against the code; YAML comment pointing at a nonexistent test fixed |
| `.env.example` omitted the `analyst` role | fixed |
| Spec audit: no test asserted low-confidence escalation (classification, extraction, answer) | `tests/integration/test_thresholds_and_escalation.py` |
| Spec audit: retrieval top-k and similarity threshold were configurable but untested | top-k, threshold and document-scope tests added |
| Spec audit: README drift section omitted document-length and retrieval-score distributions | corrected |
| Spec audit: architecture diagram did not show the orchestrator branching to RAG, guardrails and review | diagram restructured into document workflow + Q&A flow |

Earlier in the build, tests had caught and fixed: the PII regex masking invoice numbers and
missing sentence-final account numbers, and reviewer corrections accepting invalid currencies.

## 13. Known limitations

Mock metrics are not model-quality evidence; live cloud paths are unverified here; processing is
synchronous; SQLite and embedded Chroma are single-node; single-tenant; lexical hashing embeddings
in mock mode; lexical groundedness misses paraphrase errors and can over-flag scale words;
pattern-based injection detection; heuristic active-content scan; no tracing or exporter; no
scheduled drift job or alerting; indicative pricing only; OCR has no table/layout model.

## 14. Features intentionally not implemented

Asynchronous job queue and workers; fine-tuning (documentation only: `docs/fine-tuning-pathway.md`);
reviewer UI; multi-tenancy; SSO; retention endpoints; CD pipeline; distributed tracing; hybrid
search and re-ranking; autonomous tool-using agents (by design, ADR-004).

## 15. Components requiring credentials

| Component | Requirement |
|---|---|
| Bedrock chat / embeddings | AWS credentials via the standard chain, model access enabled, `bedrock:InvokeModel` on the model ARNs |
| Textract OCR | AWS credentials, `textract:DetectDocumentText` |
| Azure OpenAI | endpoint, API key (or future Entra ID), chat and embedding deployment names |
| API auth (optional) | `DOCINTEL_API_KEYS_JSON` from a secrets manager |

## 16. Production improvements (priority order)

1. Queue-backed workers with idempotent jobs and a dead-letter queue; 202 + polling.
2. Postgres + Alembic, S3 with SSE-KMS, managed vector store with server-enforced tenant filters.
3. OIDC/SSO, per-tenant RBAC, maker-checker review.
4. Real-provider evaluation corpus with per-provider baselines and a calibrated judge; scheduled
   live contract tests.
5. Semantic + BM25 hybrid retrieval, re-ranking, table-aware chunking, Textract AnalyzeDocument.
6. OTel tracing + exporter, dashboards, SLO alerts, scheduled drift jobs.
7. WAF, rate limits, malware scanning, retention jobs, data-residency enforcement.
8. Signed images, SBOM and vulnerability scanning, gated environment promotion, canary rollouts for
   prompt and model changes.

## 17. Exact commands

```bash
make install                      # .venv (Python 3.12) + package + dev tools
make dev                          # API on http://127.0.0.1:8000 (OpenAPI at /docs)
make demo                         # live walkthrough (requires `make dev` in another terminal)
make lint typecheck               # ruff + mypy --strict
make test                         # 256 tests with coverage
make eval && make gate            # evaluation report + quality gate
make drift                        # drift report (reports/drift_report.md + .json)
make docker && make docker-run    # build image; docker compose up
make check                        # lint + typecheck + test + gate
```

Direct equivalents: `.venv/bin/python -m pytest`, `.venv/bin/python scripts/run_evals.py --output
reports/eval_results.json`, `.venv/bin/python scripts/quality_gate.py`, `docker build -t
fin-docintel:local .`.

## 18. Demo walkthrough

1. `make dev`, then `make demo` (or follow README sections 13–15 with curl).
2. Health shows `mock_mode: true` and the configured providers.
3. Six PDFs are uploaded and processed: invoice, bank statement and fund summary → `READY`;
   Aurora income statement → review (`missing_required_fields`: no currency); Granite balance sheet → review (conflicting
   values, low extraction confidence); injection invoice → review (`guardrail_triggered`); a re-upload is de-duplicated and a
   malformed PDF is rejected with 422.
4. Q&A: cited answers with groundedness 1.0; an unanswerable question is refused ("insufficient
   evidence") and creates an answer review; an injection question is blocked before retrieval.
5. Review: Aurora corrected (currency USD) → `READY`; Granite corrected → `READY`; injection invoice
   rejected → `REJECTED`.
6. The audit trail shows transitions and the reviewer's correction; chain verification is valid.
7. Metrics, drift report (a genuine alert: the demo's review rate differs from the evaluation
   baseline) and an evaluation run with the gate passed.

## 19. Interview talking points

- Deterministic orchestration with AI steps, not an autonomous agent: enumerable, testable,
  auditable (ADR-004).
- One model gateway: versioned + hash-locked prompts, retries, JSON repair, validation, ledger.
- Layered hallucination control: evidence verification, cross-field rules, citation binding,
  numeric groundedness, refusal, review.
- HITL as a first-class feature: 15 explicit reasons, validated and versioned corrections,
  reviewer identity from auth, audited decisions.
- Honest evaluation: mock scores validate the harness; visible failures and a regression gate are
  the real signal; the same harness runs on Bedrock or Azure.
- Real bugs found by tests and by reading logs (PII regex, currency corrections, token-count
  redaction, unpriced cost, health status) — evidence of a working feedback loop.
- A clear production path: async workers, managed stores, OIDC, tracing, real-provider evaluation.

Further detail: `README.md`, `docs/adr/`, `docs/interview-guide.md` (40 topics),
`docs/interview-questions.md` (112 questions), `docs/codebase-walkthrough.md`,
`docs/fine-tuning-pathway.md`.
