# ADR-006: Evaluation methodology

- Status: Accepted
- Date: 2026-09-30

## Context

LLM features regress silently when prompts, models, chunking or thresholds change. We need repeatable,
mostly deterministic evaluation that runs in CI without paid APIs and can be pointed at a real
provider when credentials exist.

## Decision

`app/evaluation/runner.py` processes the labelled synthetic dataset (`sample_data/ground_truth.json`,
`evals/datasets/*.jsonl`) in an **isolated sandbox** (temp directory, in-memory vector store) through
the *real* workflow code, then computes:

| Category | Metrics |
|---|---|
| Classification | accuracy, macro precision, recall and F1, per-class scores, confusion matrix |
| Extraction | exact match, normalized match (case/whitespace-insensitive; amounts sign-insensitive within 0.5%), field accuracy, missing-field rate, hallucinated-field rate, invalid-value rate, per-type and per-field accuracy |
| Retrieval | precision@k, recall@k, hit rate, MRR, document hit rate, lexical context relevance |
| Answers | completeness (expected facts present), groundedness, citation correctness, lexical answer relevance, unsupported-statement rate, schema validity, correct-refusal rate, false-refusal rate |
| Workflow | routing accuracy (READY / NEEDS_REVIEW / FAILED / UPLOAD_REJECTED), review precision and recall |

**LLM-as-judge** (`prompts/validation/groundedness_judge.v1.yaml`) is optional
(`DOCINTEL_EVAL_USE_LLM_JUDGE=true`) and reported as a separate metric. It is never the only measure,
and it is off in CI.

**Quality gate** (`evals/thresholds.yaml`, `scripts/quality_gate.py`):

- absolute thresholds per metric (`min` / `max`);
- regression tolerance (0.03 absolute) against `evals/baseline.json` for key metrics;
- CI fails on any threshold breach or regression.

The baseline is updated only deliberately (`make baseline`) after reviewing an intentional change.
Prompt text is additionally locked by hash per version (`tests/fixtures/prompt_hashes.json`), so
editing a prompt without bumping its version fails CI.

## Honest interpretation of current numbers

In mock mode classification and extraction score 1.0 **because the deterministic mock is rule-based
and the synthetic documents were written with the labels it recognises**. These numbers prove the
pipeline, the metrics and the gate work end to end; they say nothing about Claude's or GPT-4o's
accuracy. Answer metrics are more informative: completeness is 0.75 and the false-refusal rate is
0.17, with visible failure cases kept in the report instead of tuned away.

## Consequences

- Deterministic metrics make CI stable and cheap.
- Lexical proxies (context relevance, answer relevance) are crude; semantic similarity or judge-based
  relevance should be added when real providers are used.
- The dataset is small (17 evaluable documents, 16 retrieval queries, 16 answer cases). Production
  needs a larger, stratified, versioned dataset drawn from real (consented, de-identified) traffic.
- Real-provider evaluation should run as a separate scheduled or manual job with its own baseline per
  provider and model.
