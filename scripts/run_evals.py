"""Run the offline evaluation suite and write a JSON report.

    python scripts/run_evals.py --output reports/eval_results.json [--update-baseline]

Uses the providers configured in the environment (mock by default). No network is needed in
mock mode.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.evaluation.gate import baseline_snapshot, load_thresholds  # noqa: E402
from app.evaluation.runner import EvaluationRunner  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402

SUMMARY_KEYS = {
    "classification": ["accuracy", "macro_precision", "macro_recall", "macro_f1"],
    "extraction": [
        "exact_match",
        "normalized_match",
        "field_accuracy",
        "missing_field_rate",
        "hallucinated_field_rate",
        "invalid_value_rate",
    ],
    "retrieval": [
        "precision_at_k",
        "recall_at_k",
        "hit_rate",
        "mrr",
        "document_hit_rate",
        "context_relevance_lexical",
    ],
    "answers": [
        "completeness",
        "groundedness",
        "citation_correctness",
        "answer_relevance_lexical",
        "unsupported_statement_rate",
        "schema_validity",
        "correct_refusal_rate",
        "false_refusal_rate",
        "llm_judge_groundedness",
        "llm_judge_cases",
        "llm_judge_errors",
    ],
    "workflow": ["routing_accuracy", "review_precision", "review_recall"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "eval_results.json")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument(
        "--run-name", help="label stored in the report, e.g. bedrock-titan-llamaindex"
    )
    args = parser.parse_args()

    configure_logging("WARNING", json_logs=False)
    logging.getLogger("app").setLevel(logging.ERROR)
    settings = Settings()
    result = EvaluationRunner(settings, run_name=args.run_name).run()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2))

    mode = "MOCK (deterministic simulated model)" if result.is_mock else "REAL PROVIDER"
    print(f"\nEvaluation run {result.run_id}  mode={mode}  duration={result.duration_s}s")
    print(
        f"run={result.config['run_name']}  llm={result.config['llm_model']}  "
        f"embeddings={result.config['embedding_model']}  rag_engine={result.config['rag_engine']}  "
        f"vector_store={result.config['vector_store']}"
    )
    if result.config["llm_judge"]:
        print(f"judge={result.config['llm_judge_model']}")
    for category, keys in SUMMARY_KEYS.items():
        values = result.metrics.get(category, {})
        cells = [f"{k}={values[k]}" for k in keys if k in values]
        print(f"  {category:<15} " + "  ".join(cells))
    print(f"\nQuality gate: {'PASSED' if result.gate_passed else 'FAILED'}")
    for failure in result.gate_failures:
        print(f"  - {failure}")
    print(f"report written to {args.output}")

    if args.update_baseline:
        thresholds = load_thresholds(settings.evals_dir / "thresholds.yaml")
        snapshot = baseline_snapshot(result.metrics, thresholds.regression_metrics)
        baseline_path = settings.evals_dir / "baseline.json"
        baseline_path.write_text(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "is_mock": result.is_mock,
                    "llm_model": result.config["llm_model"],
                    "embedding_model": result.config["embedding_model"],
                    "metrics": snapshot,
                },
                indent=2,
            )
            + "\n"
        )
        print(f"baseline updated: {baseline_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
