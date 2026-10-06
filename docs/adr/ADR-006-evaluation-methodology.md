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

## Amendment (2026-10-06): judge context, judge provider and calibration

- **Full chunks.** The judge now receives the full text of every chunk the answer cites, each
  headed `[chunk_id=… | page=…]`, instead of the one-sentence citation snippets. Snippets
  can leave out context an answer relies on (a currency or column heading printed on another
  line), which would make a correct answer look unsupported.
- **A different judge.** `DOCINTEL_EVAL_JUDGE_PROVIDER` (`mock`, `bedrock` or `azure_openai`)
  builds a second model gateway for the judge, so one vendor's model can grade another's
  answers. Unset, the answer model judges itself. The report records `llm_judge_model`.
- **Failures are visible.** Answers scored below 1.0 appear in the report's failures with the
  judge's rationale. A failed judge call is counted in `llm_judge_errors` instead of being scored
  0, and `llm_judge_groundedness` is omitted when no call succeeded.
- **Calibration.** `scripts/judge_calibration.py` scores each original answer and three
  rule-generated corruptions (changed number, negated claim, appended unsupported sentence) with
  the judge and with the lexical check (`app/evaluation/judge_calibration.py`).

Live run on 6 October 2026, Claude Haiku 4.5 answering and Azure `gpt-4.1-mini` judging
(`evals/results/llm_judge_2026-10-06.json`): judge groundedness 1.00 on 20 answers with no
errors, gate passed. In calibration the judge flagged 0 of 20 originals, 20 of 20 changed numbers,
12 of 12 negations and 20 of 20 appended claims. The lexical check flagged 19, 0 and 20
respectively: it cannot see negation, and it missed a changed fiscal year ("FY2028") because
digits glued to letters are not parsed as numbers.

Consequences: the judge complements the lexical check rather than replacing it. The lexical check
stays in the request path because it is free, instant and explainable. The calibration uses simple
synthetic corruptions and one run; agreement with human graders is still unmeasured, and that is
the next step before the judge score is used as a gate.
