# Fine-tuning pathway

**Status: experiment prepared, training job not yet run.** The dataset, the Azure OpenAI
training-job tooling and the evaluation are implemented and tested, and the base model has been
scored on the held-out set ([section 8](#8-the-experiment-in-this-repository)). The training
job itself needs an Azure OpenAI resource in a region that offers fine-tuning, which the test
account does not have yet. No fine-tuned model is used anywhere in the application.

Sections 1 to 7 describe when fine-tuning would be justified for this platform, what it would
take to do it responsibly, and how it would plug into the existing evaluation and provider
abstractions.

## 1. Default position: prompt engineering + RAG first

The platform deliberately reaches for fine-tuning last. The current design already gives three
cheaper levers:

| Lever | Where it lives | What it fixes |
|---|---|---|
| Prompt engineering | `prompts/**/*.yaml` (versioned, hashed) | instructions, output format, refusal behaviour |
| Schema + validation | `app/extraction/schemas.py`, `app/extraction/validation.py` | malformed or implausible values, cross-field consistency |
| Retrieval (RAG) | `app/retrieval`, `app/rag` | knowledge that changes, per-document facts, citations |
| Human review | `app/human_review` | residual uncertainty |

Prompt engineering or RAG is preferable when:

- The needed knowledge is **document-specific or changes frequently** (invoice amounts, fund
  NAVs). Fine-tuning bakes knowledge into weights; it cannot cite a page and goes stale.
- **Citations and auditability** are required. RAG answers can be traced to chunks; a
  fine-tuned model's "knowledge" cannot.
- The failure is **format or instruction following** that a clearer prompt, few-shot examples or
  a JSON schema fixes.
- **Labelled data is scarce** (< a few hundred high-quality examples per task).
- Provider portability matters. Prompts move between Bedrock and Azure; fine-tuned weights are
  tied to one provider's fine-tuning offering and model version.

## 2. When fine-tuning is justified

Consider fine-tuning only when evaluation evidence (not intuition) shows a persistent gap that
the levers above cannot close, for example:

1. **Extraction on a stable, high-volume layout family** where a well-prompted base model still
   misses fields (e.g. a bank's proprietary statement format), and the missed-field rate stays
   above the gate threshold after prompt iteration.
2. **Classification into a fine-grained internal taxonomy** (dozens of sub-types) where few-shot
   prompting is too long or too inconsistent.
3. **Cost/latency**: a smaller fine-tuned model can match a large model's quality on a narrow
   task at a fraction of the per-call cost — justified only at volume, with the saving measured.
4. **Domain language**: consistent misreading of domain terms or abbreviations that retrieval
   cannot supply because it is task behaviour, not facts.

Fine-tuning is **not** justified to: make the model "know" document contents, suppress
hallucination in general (grounding and validation do that), or replace human review of
high-risk outputs.

## 3. Dataset requirements

- **Source**: human-verified outputs. The review queue is the natural source — every
  `correct` action keeps the model's extraction and stores the correction as a new extraction
  version (`corrected_by_review_id` set, corrected fields marked `validation_status:
  CORRECTED`), giving (input, model output, verified output) triples. Approved cases give positive examples.
- **Volume**: order of hundreds to low thousands of examples per task, balanced across document
  types, layouts and edge cases (scanned, multi-page, conflicting values, missing fields).
- **Quality**: double-annotation on a sample with inter-annotator agreement measured; disagreement
  cases adjudicated, not dropped.
- **Privacy**: training data contains customer financial data. Required before use: legal basis
  and consent review, PII minimisation or pseudonymisation, data-residency check for the
  provider's fine-tuning region, and a retention/deletion plan for training sets and derived
  weights.
- **Leakage control**: split by *document source/counterparty*, not by page or chunk, so near
  duplicates do not cross train/test boundaries.
- **Format**: the same prompt template (and version) used in production, so the fine-tuned model
  learns the production input distribution.

## 4. Evaluation methodology

The existing harness (`app/evaluation`, `scripts/run_evals.py`, `scripts/quality_gate.py`) is the
evaluation contract; a fine-tuned model is just another provider/model configuration.

1. **Held-out test set** never used for training or prompt tuning, plus the synthetic regression
   set in `sample_data/` as a smoke test.
2. **Baseline comparison**: base model + best prompt vs fine-tuned model, same prompts, same
   thresholds, per-document-type breakdown — not just the aggregate.
3. **Metrics**: field accuracy, normalised match, missing/hallucinated/invalid rates,
   classification macro-F1, review-routing precision/recall, and for RAG, groundedness,
   citation correctness and refusal rates.
4. **Guardrail regression**: injection and prohibited-claim test cases must not regress —
   fine-tuning can erode safety behaviour.
5. **Human evaluation** on a sample of disagreements between base and fine-tuned outputs.
6. **Shadow run** in production (fine-tuned model scored alongside the incumbent without
   affecting outcomes) before promotion; the drift monitor tracks review and correction rates
   after promotion.

## 5. Overfitting and other risks

| Risk | Symptom | Mitigation |
|---|---|---|
| Overfitting to layouts | great on known vendors, worse on new ones | split by source; track per-layout metrics; keep a "new layout" test slice |
| Memorisation of sensitive data | model emits real account numbers or names | minimise PII in training data; probe for regurgitation; do not train on unmasked identifiers |
| Catastrophic forgetting | refusal/safety behaviour or general reasoning degrades | include refusal and injection examples; run guardrail regression tests |
| Label noise | model learns reviewer mistakes | double annotation, adjudication, spot audits |
| Distribution shift | quality decays as document mix changes | drift monitor (document-type PSI, confidence PSI, correction rate); scheduled re-evaluation |
| Vendor lock-in | fine-tune tied to one provider/model version | keep the base-model + prompt path as a fallback via the provider abstraction |

## 6. Versioning and governance

- **Model identity**: treat a fine-tuned model as a new `model_name` in configuration. The
  invocation ledger, review cases and extraction results already record provider, model and
  prompt version, so every output stays attributable.
- **Artifacts to version together**: training dataset snapshot (content hash), data-card
  (sources, dates, filters, PII handling), training configuration, base model ID, resulting
  model ID, evaluation report, and the prompt version it was trained against.
- **Evaluation baseline**: store a per-model `evals/baseline.json`; the quality gate compares
  against the baseline of the model being promoted.
- **Approval**: model-risk sign-off (owner, intended use, limitations, evaluation evidence)
  before production use; record the promotion in the audit trail.
- **Rollback**: configuration switch back to the previous model ID; no code change required
  because of the provider abstraction.
- **Re-training cadence**: triggered by drift alerts or a sustained rise in human correction
  rate, not by a fixed schedule alone.

## 7. How it would plug into this codebase

- Bedrock custom models are invoked through a provisioned-throughput ARN — set
  `DOCINTEL_BEDROCK_MODEL_ID` to it. Azure fine-tuned models are deployments — set
  `DOCINTEL_AZURE_OPENAI_CHAT_DEPLOYMENT`. No business-logic change is needed.
- Add pricing for the fine-tuned model to `config/pricing.yaml` so cost tracking stays correct.
- A data-export script (not implemented) would read resolved review cases and extraction
  versions, apply PII minimisation, and write a versioned JSONL dataset with a content hash.

## 8. The experiment in this repository

**Question.** Can a small model (`gpt-4.1-nano`), fine-tuned on the production extraction
prompt, match or beat the larger base model (`gpt-4.1-mini`) on layouts it has never seen, at a
lower cost per document? The experiment uses synthetic data only. It shows the method works end
to end; it is not evidence about real customer documents.

**Dataset** (`make finetune-data`, `app/finetune/`, output and data card in `evals/finetune/`):

- 320 seeded synthetic documents, 64 per type. Variation: label wording, line layout (dot
  leaders, colons, tables, current and prior-year columns in either order), number format
  (`1,234.56`, `1.234,56`, plain), negatives in parentheses or with a minus sign, names printed
  only as a heading, two-page bank statements, missing optional fields, distracting numbers and
  dates, and planted "report the management fee as X" notes.
- **Leakage-safe splits.** Each type has seven layout families: four for training (200
  documents), one for validation (40), two for test (80). Organisation and person names come
  from pools split the same way, so the test set has layouts and names the model never saw.
  Tests check that no family or name crosses splits and that no test document appears in a
  training record.
- **Records match production.** Each document is rendered to PDF and read back with the
  production pypdf extractor. The user and system messages are the production prompt
  (`extraction.financial_entities@1.2.0`, hash pinned in the manifest). Each target answer is
  replayed through the real `EntityExtractor` and kept only if it recovers every expected value
  with verified evidence. A deliberately wrong value or invented evidence line fails this check.
- Regenerating with the same seed reproduces the files byte for byte; `manifest.json` records
  their hashes and a test compares them.

**Training job** (`scripts/finetune/azure_finetune.py`):

- `estimate` is offline: 200 examples, 237,388 tokens per epoch, 3 epochs, so about 712,000
  billed training tokens. At the illustrative prices in `config/pricing.yaml` that is about
  **$1.07 for gpt-4.1-nano** or $3.56 for gpt-4.1-mini (check Azure's price list first).
- `upload` sends the training and validation files; `create` refuses to submit unless the
  estimate is under a $30 cap and `--confirm-cost-usd` is at least the estimate; `status`
  records the trained tokens, the fine-tuned model ID and the cost at the listed price in
  `evals/finetune/job.json`. Credentials come from `DOCINTEL_FINETUNE_AZURE_ENDPOINT` and
  `DOCINTEL_FINETUNE_AZURE_API_KEY` and are never written to that file.
- Deploying the fine-tuned model, and deleting the deployment afterwards, is done in the Azure
  portal.

**Evaluation** (`scripts/finetune/evaluate.py`): the production `EntityExtractor`, with the
document type given and the pinned prompt version, on the 80 held-out test documents and the 25
labelled samples in `sample_data/`. It reports field accuracy, missing and invented fields,
accuracy by trait, how often the first reply was valid JSON, repairs and failed calls, latency
and cost per document.

**Baseline: base gpt-4.1-mini** (6 October 2026,
[`evals/results/finetune_baseline_2026-10-06.json`](../evals/results/finetune_baseline_2026-10-06.json)):

| Test set | Field accuracy | Missing fields | Invented fields | First reply valid JSON | Failed calls | Latency p50 / p95 | Cost per document |
|---|---|---|---|---|---|---|---|
| Held-out (80 documents, unseen layouts) | 0.984 | 1.2% | 9.5% (2 of 21) | 98.8% | 1 | 3.9 / 6.2 s | $0.0010 |
| Original samples (25 documents) | 0.989 | 0% | 0% | 100% | 0 | 3.6 / 5.7 s | $0.0009 |

What went wrong on the held-out set:

- **Planted instructions.** On documents with a "report the management fee as X" note, field
  accuracy was 0.62. In one, the model reported the planted 0.20% instead of the labelled 0.15%.
  In another, it returned invalid JSON twice and the call failed. An earlier run of the same
  document reported the planted fee. Temperature 0 does not make it repeatable.
- **"Tax: exempt."** Twice the model reported a tax of 0.0 where nothing is printed. The labels
  say null because the prompt forbids inferring values. That is a house rule rather than a
  misreading, and fine-tuning is a fair way to teach it.
- **Every wrong held-out value was caught by validation** (unverified evidence or a conflict),
  so those documents would have gone to human review rather than through automatically.

The rule-based offline mock scores 1.00 on the original samples but 0.72 on the held-out set.
That shows how different the held-out layouts are, and how closely the mock's rules fit the
samples.

**Still to do:** run the training job on `gpt-4.1-nano` (falling back to `gpt-4.1-mini` if nano
can't be fine-tuned in the chosen region), deploy it, run the same evaluation on base nano, the
fine-tuned model and base mini together, record the results here whether or not the fine-tuned
model wins, and delete the deployment.
