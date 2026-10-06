# Project completion report — fin-docintel

Date: 2026-10-03, updated 2026-10-06 (section 21) · Version: 0.1.0 · Python 3.12.14 · License: MIT

## 1. Executive summary

`fin-docintel` is a runnable, tested Financial Document Intelligence & Agentic Workflow Platform.
It ingests financial PDFs, extracts text (with Tesseract, Textract or vision-model OCR fallback), classifies
documents, extracts typed and validated fields with verified evidence, indexes PII-masked chunks
in a vector store, answers questions with citations and deterministic groundedness checks,
routes uncertainty to a human review queue, and records every step in a hash-chained audit trail.
It ships with an evaluation harness plus CI quality gate, drift monitoring, structured
observability, a small built-in operator console at `/ui`, Docker packaging and GitHub Actions
CI.

Everything runs offline in a clearly labelled, deterministic mock mode; AWS Bedrock (Claude) and
Azure OpenAI are real integrations selected by configuration. **Azure OpenAI has been verified
live** with a `gpt-4.1-mini` deployment over two rounds: 20 documents, then 30 documents that add
harder layouts, European number formats, an unsupported look-alike document and a subtler prompt
injection. The final 30-document run passes the quality gate with classification 1.00,
extraction normalised match 0.989, and no missing or hallucinated fields. The README's
"Real-model results" section lists each issue those runs surfaced and how it was fixed.
**AWS Bedrock has also been verified live**: Claude Haiku 4.5 with Titan Text Embeddings V2
passes the same gate on the same 30 documents with no code or prompt changes (extraction
normalised match 0.995, retrieval MRR 0.979). Textract, Azure embeddings and Azure
reasoning-model mode are implemented and tested with stubs, but have not been run against live
endpoints. Vision OCR (Claude on Bedrock, gpt-4.1-mini on Azure), a switchable LlamaIndex
retrieval engine and a cross-provider LLM judge were since added and run live; an Azure OpenAI
fine-tuning experiment is built but its training job has not run yet; a GitHub Actions deploy
pipeline with OIDC is in use and the deployed site now searches with Titan (section 21).

A **public guided demo site** was added afterwards: a React landing page, an eight-step guided
tour and a playground for non-technical visitors. It's served by the same container in an opt-in
demo mode with per-visitor workspaces, rate limits, a daily live-AI budget and 24-hour retention.
It's deployed on AWS at https://d1cpufi9ii8q1y.cloudfront.net (section 20).

Final validation (2026-10-06): **446 Python tests passed** locally, none skipped (Tesseract is
installed), **95% line coverage**, ruff lint and format clean, **mypy `--strict` clean on 108
files**, **quality gate PASSED (27 checks)** in mock mode. Web: ESLint, TypeScript, **20 Vitest
tests** and the build pass; **17 Playwright browser tests** pass in Chromium (14 desktop, 3 phone)
and the 14 desktop tests pass in WebKit. `cfn-lint` and `actionlint` are clean.

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

- **Operator console** (`app/web`) — static HTML/CSS/JS served at `/ui`, a client of the public
  API only, with a strict Content-Security-Policy (ADR-010).

- **Public demo** (`app/demo`, `web/`, `deploy/aws`) — opt-in demo mode for anonymous visitors
  and a Vite + React site served at `/` (ADR-011).

The Mermaid diagram is in README section 5; the decisions behind it are in `docs/adr/ADR-001` to `ADR-011`.

## 3. Features implemented

| Area | Implemented |
|---|---|
| Upload | size cap enforced while reading, `.pdf` + content-type + `%PDF` magic checks, page limit, encrypted / active-content flags, SHA-256 de-duplication, generated storage names, atomic writes |
| Text extraction | pypdf per page; OCR fallback when < 40 chars/page; Tesseract and Textract providers; OCR routes to review |
| Classification | LLM + versioned prompt, confidence threshold 0.70, unknown → review |
| Extraction | 5 per-type Pydantic schemas, typed coercion, evidence verification against page text (numeric values must also appear in their own evidence), alternatives / conflict detection, account masking; English and European number formats |
| Validation | per-field (ISO currency, date plausibility, percent range, numeric, masked account, evidence not injected text) and cross-field rules (invoice total, balance-sheet identity, income-statement consistency, bank reconciliation, fund fee range) |
| Indexing | PII-masked, page-aware chunking (600/80), deterministic chunk IDs, idempotent re-indexing, embedding-model-namespaced Chroma collections |
| RAG | input guardrail, top-k + threshold + allow-listed filters, grounded JSON answer, citation binding to retrieved chunks, deterministic groundedness, prohibited-claims filter, heuristic confidence, refusal, answer review |
| HITL | consolidated review cases with 15 reason codes; approve / reject / correct; corrections schema- and rule-validated (422 on invalid); type correction re-runs extraction; versioned corrected extractions |
| Audit | SHA-256 hash chain, per-document history, `/audit/verify` |
| Observability | JSON logs with request/document/workflow IDs, PII masking and credential redaction; ~20 counters and 6 histograms; Prometheus text; OTel metrics API adapter; health checks with 503 on degradation |
| Evaluation | classification, extraction, retrieval, answer and workflow metrics; optional LLM judge; thresholds + regression gate vs baseline |
| Drift | PSI (type mix, confidence distributions), rate deltas, operational ratios, version changes, sample-size gating |
| Security | optional API-key auth (viewer < analyst < reviewer < admin), reviewer identity from the key, secrets via env only, non-root read-only container |
| Endpoints | all 15 required endpoints (see README), plus `GET /documents`, `POST /ask`, `GET /drift/report`, `GET /audit/verify` |
| Operator console | `/ui`: upload and process, extracted fields with evidence and validation status, document and corpus Q&A with citations, review queue (approve / reject / correct), audit history; can be disabled with `DOCINTEL_UI_ENABLED=false` |
| Providers | Azure reasoning deployments (o-series, gpt-5) supported by setting: `reasoning_effort` instead of temperature, larger completion-token budget, API-version check at start-up |

## 4. Exact technology choices

Python 3.12.14 · FastAPI 0.142.2 · Uvicorn 0.54.0 · Pydantic 2.13.5 · pydantic-settings 2.15.0 ·
SQLAlchemy 2.0.54 · pypdf 6.19.0 · pypdfium2 5.13.0 · pytesseract 0.3.13 (Tesseract in Docker) ·
chromadb 1.5.9 · langchain-core 1.6.6 · langchain-text-splitters 1.1.3 · langchain-aws 1.8.0
(`ChatBedrockConverse`, `BedrockEmbeddings`) · langchain-openai 1.6.7 (`AzureChatOpenAI`,
`AzureOpenAIEmbeddings`) · boto3 1.43.105 (Textract) · opentelemetry-api 1.45.0 · pytest 9.1.1 ·
ruff 0.16.9 · mypy 2.3.1 · reportlab 5.0.1 (synthetic PDFs). Dependencies are pinned in
`requirements.lock` (uv, universal, Python 3.12).

LangChain is used only as an integration layer (adapters, `PromptTemplate`,
`RecursiveCharacterTextSplitter`); orchestration is our own state machine (ADR-001).

## 5. External integrations

| Integration | Status | Verification |
|---|---|---|
| AWS Bedrock — Claude chat | Implemented (`BedrockClaudeProvider`) | **verified live** (Claude Haiku 4.5 via the `us.` inference profile; full evaluation on 30 documents, gate passed) |
| AWS Bedrock — Titan embeddings | Implemented | **verified live** (Titan Text Embeddings V2 in a full evaluation run; MRR 0.979) |
| Azure OpenAI — chat | Implemented, config validated at start-up | **verified live** (`gpt-4.1-mini`, full evaluation on 30 documents, gate passed); reasoning mode verified only by asserting the request body |
| Azure OpenAI — embeddings | Implemented | unit-tested with fakes; not called live (needs an embedding deployment) |
| Vision OCR — Claude on Bedrock, gpt-4.1-mini on Azure OpenAI | Implemented (`VisionLLMOCRExtractor`, ADR-013) | **verified live** on three scored scans (character error rate 0.000 for both, Tesseract 0.104) and through the whole pipeline on two scans |
| LlamaIndex retrieval engine | Implemented (`DOCINTEL_RAG_ENGINE=llamaindex`, optional extra) | parity tests; **verified live** with Titan: same ranked chunks as the native engine for all 51 evaluation queries |
| Azure OpenAI — fine-tuning | Scripts implemented (`scripts/finetune/`) | dataset built and checked by tests, cost estimated, base gpt-4.1-mini baseline measured live; **training job not yet run** (needs a fine-tuning resource) |
| AWS Textract OCR | Implemented (`TextractOCRExtractor`) | integration test with a stubbed Textract client exercising real rendering + line assembly; a live call reached AWS but the test account had no Textract subscription (`SubscriptionRequiredException`, surfaced as a provider error) |
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
| Unit (`tests/unit`) | 251 | passed |
| Integration (`tests/integration`) | 138 | passed (the Tesseract test is skipped where Tesseract isn't installed) |
| End-to-end API, console, demo mode and site serving (`tests/e2e`) | 57 | passed |
| **Python total** | **446** | **446 passed · 95% coverage (app)** |
| Web unit (`web/src/**/*.test.ts`, Vitest) | 20 | passed |
| Browser (`web/e2e`, Playwright: tour, evidence viewer, axe, mobile) | 14 desktop + 3 phone | passed in Chromium; the desktop set also passes in WebKit (plus one screenshot spec, skipped unless `SCREENSHOTS=1`) |

Static checks: `ruff check` and `ruff format --check` clean (app, scripts, tests); `mypy --strict`
clean (108 source files); ESLint and `tsc` clean for `web/`; `cfn-lint` clean for the AWS templates; `actionlint` clean for the workflows. The console was also checked by hand in a browser against a mock-mode
server (upload, fields, Q&A, review queue; screenshots in `docs/images/`). Earlier manual
validation: live Uvicorn + `scripts/demo.py`
(no 5xx; the two 422s are intentional malformed-upload rejections), Docker build + container smoke
test (health, OCR, review details, logs), and a privacy scan confirming no account numbers,
question text or document lines appear in logs, audit events, review cases or indexed chunks.

## 8. Evaluation results (mock mode, deterministic)

| Area | Results |
|---|---|
| Classification (n=27) | accuracy 1.00, macro-F1 1.00 |
| Extraction (191 fields) | exact 0.995, normalised 1.00, missing 0.00, hallucinated 0.00, invalid 0.038 (the expected invalid values in the review-routed documents) |
| Retrieval (24 queries, k=4) | precision@k 0.260, recall@k 1.00, hit rate 1.00, MRR 0.951, document hit 1.00, context relevance 0.570 |
| Answers (27 cases) | completeness 0.75, groundedness 1.00, citation correctness 1.00, relevance 0.902, unsupported 0.00, schema validity 1.00, correct refusal 1.00, false refusal 0.15 |
| Workflow (30 documents) | routing accuracy 1.00, review precision 1.00, review recall 1.00 |

Quality gate: **PASSED (27 checks)**, regression tolerance 0.03 against `evals/baseline.json`.
Interpretation: synthetic data and mock rules were built together, so perfect
classification and extraction scores demonstrate harness correctness only. The honest signals are
the visible failures (answer cases a04, a11, a12, a13, a20; false refusals; low precision@k from
lexical retrieval) and the fact that the same harness runs unchanged on real providers (ADR-006).
Live runs at temperature 0 are not guaranteed to repeat exactly.

**Live Azure OpenAI `gpt-4.1-mini`, 30 documents** (prompts: classification v1.1.0, extraction
v1.2.0): classification 1.00; extraction normalised 0.989, exact 0.973, missing 0.00,
hallucinated 0.00; answers completeness 1.00, groundedness 1.00, citation correctness 1.00,
false refusal 0.00, correct refusal 1.00; routing 1.00; gate passed. The two remaining misses are
definitional (a fiscal-year heading reported instead of the labelled period end; an invoice total
reported instead of the balance after partial payment) and are listed in the README.

## 9. CI/CD status

`.github/workflows/ci.yml` originally defined two jobs: **quality** (Tesseract install, lock
install, ruff, format check, mypy, unit, integration, e2e, offline evaluation, quality gate,
report artifact) and **docker** (build, run, health smoke test, logs). The workflow's first run
on GitHub passed both
([run 36735688189](https://github.com/zamanmaruf/Financial_Document_Intelligence-Agentic_Workflow_Platform/actions/runs/36735688189)).
The demo work adds **web** (ESLint, tsc, Vitest, build), **e2e** (Playwright against a demo-mode
API) and **infra** (`cfn-lint`, deploy-script syntax) jobs, and the docker job now builds the
multi-stage image and smoke-tests the site in demo mode. Every command in these jobs passed
locally. The infra job also runs `actionlint` on the workflows.

**Deployment.** `.github/workflows/deploy.yml` (added 2026-10-06) runs after `ci` succeeds on
`main`: it waits for a reviewer in the GitHub environment `production`, signs in to AWS with
GitHub's OIDC token (the `docintel-github-deploy` stack, already created, holds the OIDC provider
and two roles), deploys through a CloudFormation service role and runs `make smoke-live`. **In
use since 2026-10-06**: the first successful run ([run 37427484224](https://github.com/zamanmaruf/Financial_Document_Intelligence-Agentic_Workflow_Platform/actions/runs/37427484224)) took 8 minutes from approval to passing
smoke tests. `make deploy` still works from a laptop.

## 10. Security

Implemented: env-only secrets (`SecretStr`), git- and docker-ignored `.env`, AWS credential
chain; optional API-key auth with constant-time comparison and role hierarchy; key-derived
reviewer identity (no impersonation); upload validation and safe storage (generated IDs, resolved
path checks, atomic writes, restrictive permissions); prompt-injection defence in depth
(question screening, document scanning → review, untrusted-data prompts, schema validation,
citation binding, groundedness, no model-initiated actions); PII masking in logs, chunks and
extracted account numbers; hash-chained audit; non-root, read-only container with
`no-new-privileges`.

Demo mode adds: HMAC-signed visitor sessions bound to private workspaces (404 on
cross-workspace access, retrieval filtered by workspace on the server), operator endpoints closed
to visitors, in-memory per-visitor and per-IP rate limits with `429` + `Retry-After`, a daily
live-model budget with a labelled offline fallback, smaller upload caps, 24-hour purging of
visitor data, and a strict-CSP site that renders document text as text only (enforced by lint
rules).

Not implemented (documented in ADR-009 and README section 21): encryption at rest, TLS inside the
app (the AWS template terminates TLS at CloudFront), retention/deletion policies outside demo
mode, data-residency enforcement, multi-tenancy for API-key users, SSO/OIDC, distributed rate
limiting or WAF, malware scanning. Raw document text is stored unmasked and sent in full to the
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
| Real-model run: Pinnacle ground truth said "no bank name" although the heading prints it (mock bias) | ground truth corrected; mock handles unlabelled bank headings |
| Real-model run: prompt didn't say how to format dates; model reformatted dates and turned a quarter into a date | prompt `extraction.financial_entities` v1.1.0 |
| Real-model run: model mis-masked an IBAN (`****2619` for `…9268 19`) | masked value recomputed in code from the printed number once found in the source text |
| Real-model run: case-only "alternatives" (capitalised headings) counted as conflicts, sending 3 clean documents to review | conflict detection ignores case/spacing for text; numbers must match to the cent |
| Evaluation report listed the oldest prompt version instead of the one in use | `PromptRegistry.active_versions()` |
| Azure deployment names had no price entry | `aliases:` in `config/pricing.yaml` |
| 30-document live run: the model obeyed an injected "report the fee as 0.10%" sentence, quoting it as evidence | a field whose evidence is flagged as injection is invalid and routes to review as `guardrail_triggered`; extraction prompt v1.2.0 says instruction sentences are not data |
| Evidence verification checked only the quoted raw text, so a hijacked value paired with a genuine quote would pass | the returned numeric value must itself appear in the evidence quote |
| 30-document live run: valid JSON followed by a stray `}` failed parsing twice, dropping the extraction | the parser reads the first complete JSON object and ignores trailing text |
| 30-document live run: a credit card statement was classified as a bank statement | classification prompt v1.1.0 lists look-alike documents that must be `unknown` |
| European number formats (`12.435,50`) were parsed as small decimals in evidence checks, groundedness and evaluation | one shared normaliser for both conventions, with tests for the ambiguous cases |
| Sample generator and committed ground truth had drifted (hand edit) | fixed in the generator; regenerating reproduces the committed files |
| End-to-end audit: `pip-audit` found 49 advisories in pypdf 5.9.0 (crafted PDFs exhausting memory and similar), reachable because every upload is parsed | upgraded to pypdf 6.19.0; LangChain packages upgraded to 1.x to clear 4 unreachable advisories; both live providers re-run on the new versions with identical results |
| End-to-end audit: the demo's last step (`POST /evaluations/run`) timed out after 120 s against a real provider | demo allows 15 minutes for that call and says why |
| End-to-end audit: an unsupported answer sentence lowered groundedness but wasn't listed in the report, so a failed gate couldn't be explained | each flagged sentence is recorded in `failures.answers` with its case ID; test added |
| End-to-end audit: the drift baseline predated the prompt updates, so every drift report raised a "new prompt versions" alert | baseline regenerated (mock, current prompts, 30 documents) |

**End-to-end audit (2026-10-03):** fresh clone from GitHub installed from the lock file in a clean
environment passes lint, types, all tests, evaluation and gate offline; live demo walkthrough
against Bedrock (upload, process, cited Q&A, refusal, injection block, review correct / reject,
audit-chain verification); console checked in a browser against the live server; Docker image
rebuilt with the new dependencies (non-root, `/ui` served, Tesseract OCR extracted all 8 fields
of the scanned invoice); full git history scanned for credentials (none; all commits by one
author); README links, anchors, setting names, `make` targets, endpoint and reason counts
checked against the code.

Earlier in the build, tests had caught and fixed: the PII regex masking invoice numbers and
missing sentence-final account numbers, and reviewer corrections accepting invalid currencies.

## 13. Known limitations

Mock metrics are not model-quality evidence; the fine-tuning job has not run; vision OCR was measured on three synthetic pages only, and the judge was calibrated against rule-generated corruptions, not human graders; Textract, Azure embeddings and Azure reasoning mode are unverified live (Azure OpenAI chat, Bedrock Claude and Titan embeddings are verified); the real-model evaluation uses only 30 synthetic documents, and live runs at temperature 0 are not guaranteed to repeat; the console is a single-user operator tool; processing is
synchronous; SQLite and embedded Chroma are single-node; single-tenant; lexical hashing embeddings
in mock mode; lexical groundedness misses paraphrase errors and can over-flag scale words;
pattern-based injection detection; heuristic active-content scan; four unfixed chromadb advisories
(server-only, not reachable in embedded use); no automated dependency audit in CI; no tracing or exporter; no
scheduled drift job or alerting; indicative pricing only; OCR has no table/layout model.

## 14. Features intentionally not implemented

Asynchronous job queue and workers; fine-tuning (dataset, job tooling and baseline evaluation since
added, training job not yet run: `docs/fine-tuning-pathway.md` section 8);
a full product front end (the `/ui` console is deliberately minimal: no page-image highlighting,
saved views or multi-user features); multi-tenancy; SSO; retention endpoints; distributed tracing; hybrid
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
make dev                          # API on http://127.0.0.1:8000 (console at /ui, OpenAPI at /docs)
make demo                         # live walkthrough (requires `make dev` in another terminal)
make lint typecheck               # ruff + mypy --strict
make test                         # 446 Python tests with coverage
make web && make demo-site        # build the demo site; serve it at http://127.0.0.1:8000/
make web-check && make web-e2e    # web lint/types/unit/build; Playwright browser tests
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
- A live model partly obeyed a document-borne injection; the defence that held was
  deterministic (injected evidence is never trusted, numbers must appear in their evidence), not
  the prompt alone.
- A clear production path: async workers, managed stores, OIDC, tracing, real-provider evaluation.

Further detail: `README.md`, `docs/adr/`, `docs/interview-guide.md` (40 topics),
`docs/interview-questions.md` (112 questions), `docs/codebase-walkthrough.md`,
`docs/fine-tuning-pathway.md`.

## 20. Addendum: public guided demo site (2026-10-03)

**What was built**

| Part | Status |
|---|---|
| Demo mode (`DOCINTEL_DEMO_MODE`): signed visitor cookie, workspace-scoped reviewer principal, operator endpoints closed to visitors | implemented, e2e-tested (tampered and expired cookies, 403s, demo-off behaviour unchanged) |
| Workspaces on documents, reviews, answers and chunks; per-workspace dedup; 404 ownership checks; server-side retrieval filter; SQLite migration with `schema_meta` | implemented, tested (isolation across list, get, ask, review and corpus retrieval; legacy-database migration) |
| Allow-listed samples (`/demo/samples`), background processing with progress polling, per-document audit verification | implemented, tested |
| Limits (per visitor and per IP), daily live-AI budget with labelled offline fallback, 24-hour retention task | implemented, tested |
| React site (`web/`): landing, eight-step tour, playground, how-it-works, glossary tooltips, live/offline badge | implemented; Playwright runs the whole tour against the real API; axe finds no serious or critical WCAG 2.1 AA issues on any page; checked by hand in a browser against the Docker image |
| Serving at `/` (SPA fallback, strict CSP, immutable asset caching) and a multi-stage Dockerfile | implemented, tested; image built and smoke-tested locally |
| CI: web, e2e, infra jobs; docker job smoke-tests the site | written; every command passes locally |
| AWS: CloudFormation template, `deploy.sh`, runbook | `cfn-lint` clean; **deployed** on 2026-10-03 at https://d1cpufi9ii8q1y.cloudfront.net |

**Differences from the plan:** background processing is
`POST /documents/{id}/process/background` rather than a query flag; a per-document audit
verification endpoint was added for visitors; the audit trail keeps filenames, decisions and short
flagged excerpts (the plan said "no document text"; "no page text" is accurate); the site is
served only in demo mode; and expected hosting cost is about $45 a month rather than $25–35,
mainly because of public IPv4 address charges and the ALB's fixed price. Details are in ADR-011.

**Found and fixed while testing in a real browser:** the tour said the audit trail records
every AI call, but model calls go to the separate invocation ledger, so the copy was corrected;
two colour-contrast failures (4.48:1) and an unlabelled file input were caught by axe; amounts
with cents now show two decimals (`1,985.50`); and the console at `/ui` now starts a visitor
session when demo mode requires one.

**Deployment (2026-10-03).** `make deploy` ran with an admin profile and created the stack in
about ten minutes. Checks against the public URL:
- `/`, `/tour`, `/try`, `/how-it-works`, `/ui/` and `/health` return 200, and an unknown route
  returns the 404 page.
- The CSP and HSTS headers are present.
- A request straight to the load balancer times out, because only CloudFront can reach it.
- The clean invoice reached READY and its question got a cited answer. CloudWatch shows three
  Bedrock calls with `is_mock: false`, made through the task role, costing about $0.006 in total.
- Step 1 of the tour ran in a browser, with the badge reading **Live AI**.

The deployed task used the offline lexical vectoriser for search until the 6 October deploy,
which switched it to Titan embeddings (section 21).

**Live smoke suite (2026-10-05).** `make smoke-live` runs 10 Playwright tests from
`web/e2e-live/` against the deployed URL, then the read-only AWS checks in `deploy/aws/smoke.sh`.
All 10 tests and all 5 AWS checks passed, and the run cost about $0.02 of model usage.

The first run failed the visitor-isolation test, with visitor A reading visitor B's document.
Checking by hand with two separate cookie jars showed production returning 404 as it should. The
fault was in the test: request contexts created inside a Playwright test inherit the config's
shared `storageState`, so "visitor B" was carrying visitor A's cookie. B now starts with an empty
cookie state, and the test asserts that B's session is newly created.

Still to do: confirm the AWS Budgets email subscription, and deactivate the admin access key used
for the first deploy.

## 21. Addendum: résumé alignment round (2026-10-06)

Seven items were planned so that every capability described for this project exists and is
labelled honestly. Status at the end of this round:

| Item | Status | Evidence |
|---|---|---|
| Vision OCR with Claude on Bedrock and gpt-4.1-mini on Azure OpenAI | **done, run live** | `app/providers/ocr/vision_llm.py`, ADR-013; `scripts/ocr_compare.py` scored Tesseract and both vision models on three scans (`evals/results/ocr_compare_2026-10-06.json`) |
| LlamaIndex as a switchable retrieval engine | **done, run live** | `app/retrieval/llamaindex_engine.py`, parity tests, offline and live comparison (`evals/results/rag_engine_compare_2026-10-06.json`), ADR-001 amendment |
| LLM-as-judge run live | **done, run live** | judge reads full cited chunks, optional separate judge provider; Claude's answers judged by gpt-4.1-mini (1.00 on 20), calibration flagged all 52 corrupted answers (`evals/results/llm_judge_2026-10-06.json`), ADR-006 amendment |
| Azure OpenAI fine-tuning experiment | **prepared; training not run** | seeded corpus with leakage-safe splits, records replayed through the production extractor, cost-guarded job script, evaluation harness, base gpt-4.1-mini baseline (0.984 held-out field accuracy, `evals/results/finetune_baseline_2026-10-06.json`); needs an Azure fine-tuning resource |
| GitHub Actions CD with OIDC | **done, in use** | `deploy/aws/github-oidc.yaml`, `.github/workflows/deploy.yml`, ADR-011 and runbook; first successful deploy [run 37427484224](https://github.com/zamanmaruf/Financial_Document_Intelligence-Agentic_Workflow_Platform/actions/runs/37427484224), all steps including the live smoke tests passed |
| Titan embeddings on the live site | **done, live** | deployed by that run; `/health` reports `bedrock:amazon.titan-embed-text-v2:0` and the container logs show successful Titan calls |
| Azure embeddings live run | **not started** | adapter implemented and unit-tested; needs a `text-embedding-3-small` deployment |

**Found along the way:**
- The fine-tuning generator printed a currency code on fund documents whose currency was
  labelled absent; the base-model baseline exposed it, and the dataset was rebuilt.
- Base gpt-4.1-mini followed a planted "report the fee as X" note in two of the three held-out
  documents that contain one (across runs), and reported 0.0 for "Tax: exempt" where the labels
  say null. Production validation flagged every wrong held-out value for review.
- The lexical groundedness check misses negation entirely and doesn't read numbers glued to
  letters ("FY2028"); the judge caught both. Documented rather than changing the shared parser.
- Live runs at temperature 0 still vary: one Claude answer failed the deterministic check in one
  run and passed in another.
- The first pipeline runs failed safely twice. AWS refused the OIDC sign-in because GitHub's
  subject now includes the owner and repository IDs (found in the denied CloudTrail event; the
  trust policy now pins them). Then the stack update rolled back because a new alert email forces
  the budget to be replaced and the replacement collided with its fixed name (the name now
  includes the address). The live site was unaffected both times.

**Remaining steps, each blocked on an account action:** create an Azure embedding deployment and
run the evaluation with it; create an Azure fine-tuning resource, then run, evaluate and record
the training job and delete its deployment.
