"""Produce a drift report, or (re)build the drift baseline.

    python scripts/drift_report.py                      # live data dir vs evals/drift_baseline.json
    python scripts/drift_report.py --since-hours 24     # only the last 24h of live data
    python scripts/drift_report.py --save-baseline      # snapshot reference workload as baseline

The reference workload is the labelled evaluation run (all sample documents plus the evaluation
questions) executed in an isolated sandbox, so the baseline is reproducible from the repository.
In production the baseline would instead be a snapshot of a known-good traffic window.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.clock import utcnow  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.drift.monitor import DriftSnapshot, render_markdown  # noqa: E402
from app.evaluation.runner import EvaluationRunner  # noqa: E402
from app.observability.logging import configure_logging  # noqa: E402
from app.services.container import Container, build_container  # noqa: E402


def reference_snapshot(settings: Settings) -> DriftSnapshot:
    captured: list[DriftSnapshot] = []

    def capture(container: Container) -> None:
        captured.append(container.drift.snapshot())

    EvaluationRunner(settings).run(inspect=capture)
    return captured[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "drift_report.md")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument("--since-hours", type=float, default=None)
    args = parser.parse_args()

    configure_logging("WARNING", json_logs=False)
    logging.getLogger("app").setLevel(logging.ERROR)
    settings = Settings()

    if args.save_baseline:
        snapshot = reference_snapshot(settings)
        settings.drift_baseline_path.write_text(snapshot.model_dump_json(indent=2) + "\n")
        print(f"drift baseline written to {settings.drift_baseline_path}")
        return 0

    since = utcnow() - timedelta(hours=args.since_hours) if args.since_hours else None
    container = build_container(settings)
    try:
        report = container.drift.report(settings.drift_baseline_path, since=since)
    finally:
        container.close()

    markdown = render_markdown(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown)
    args.output.with_suffix(".json").write_text(report.model_dump_json(indent=2))
    print(markdown)
    print(f"report written to {args.output} (+ .json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
