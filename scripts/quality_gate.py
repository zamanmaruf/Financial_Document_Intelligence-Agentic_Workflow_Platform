"""Enforce evaluation thresholds and regression tolerance. Exit code 1 on failure (CI gate).

python scripts/quality_gate.py reports/eval_results.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.evaluation.gate import evaluate_gate, load_baseline, load_thresholds  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "results", type=Path, nargs="?", default=ROOT / "reports" / "eval_results.json"
    )
    parser.add_argument("--thresholds", type=Path, default=ROOT / "evals" / "thresholds.yaml")
    parser.add_argument("--baseline", type=Path, default=ROOT / "evals" / "baseline.json")
    args = parser.parse_args()

    results = json.loads(args.results.read_text())
    gate = evaluate_gate(
        results["metrics"], load_thresholds(args.thresholds), load_baseline(args.baseline)
    )
    print(f"quality gate: {'PASSED' if gate.passed else 'FAILED'} ({gate.checked} checks)")
    for failure in gate.failures:
        print(f"  FAIL {failure}")
    return 0 if gate.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
