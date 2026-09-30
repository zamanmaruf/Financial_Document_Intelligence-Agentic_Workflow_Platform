"""AI-system drift monitoring.

LLM systems drift differently from classical supervised models: the model weights are usually
fixed (until the provider or we change the version), but the *inputs* (document mix, formats),
the *prompts*, the *retrieval corpus* and the *vendor model* change. Ground-truth labels are
rarely available online, so we monitor proxies:

* input drift        document-type mix, document length           (PSI vs baseline)
* model-behaviour    extraction confidence, retrieval scores,      (PSI / mean deltas)
                     groundedness, refusal and unsupported rates
* human signal       review rate, reviewer rejection & correction  (rate deltas)
                     rates (the closest online proxy for accuracy)
* quality            schema-failure rate; latest offline eval metrics
* operations         latency p95, tokens and cost per call         (ratios)
* configuration      model and prompt versions in use              (change detection)

A baseline snapshot is captured from a known-good period (or the reference dataset) and the
current window is compared against configurable thresholds.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.core.clock import utcnow
from app.domain.enums import ReviewReason, ReviewStatus, ReviewTargetType
from app.observability.metrics import percentile
from app.persistence.repositories import (
    AnswerRepository,
    DocumentRepository,
    EvaluationRepository,
    ExtractionRepository,
    InvocationRepository,
    ReviewRepository,
)

BINS: dict[str, list[float]] = {
    "document_length": [0, 500, 1000, 2000, 5000, 10000, math.inf],
    "extraction_confidence": [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001],
    "retrieval_top_score": [-1, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0001],
    "llm_latency_ms": [0, 10, 50, 100, 500, 1000, 5000, math.inf],
}


class DriftThresholds(BaseModel):
    min_samples: int = 5
    psi: dict[str, float] = Field(default_factory=lambda: {"warn": 0.1, "alert": 0.25})
    rate_delta: dict[str, float] = Field(default_factory=dict)
    ratio: dict[str, float] = Field(default_factory=dict)

    @classmethod
    def load(cls, config_dir: Path) -> DriftThresholds:
        path = config_dir / "drift.yaml"
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text()) or {}
        data.pop("version", None)
        return cls.model_validate(data)


class DriftSnapshot(BaseModel):
    created_at: datetime = Field(default_factory=utcnow)
    window_start: datetime | None = None
    counts: dict[str, int]
    categorical: dict[str, dict[str, int]]
    histograms: dict[str, list[int]]
    scalars: dict[str, float | None]
    versions: dict[str, list[str]]
    samples: dict[str, int] = Field(default_factory=dict)


class DriftMetric(BaseModel):
    name: str
    kind: str  # psi | rate_delta | ratio | version
    baseline: Any = None
    current: Any = None
    value: float | None = None
    threshold: float | None = None
    status: str  # ok | warn | alert | insufficient_data | info


class DriftReport(BaseModel):
    generated_at: datetime = Field(default_factory=utcnow)
    has_baseline: bool
    baseline_created_at: datetime | None = None
    current: DriftSnapshot
    metrics: list[DriftMetric]
    alerts: list[str]
    status: str  # ok | warn | alert | insufficient_data | no_baseline


def histogram(values: list[float], edges: list[float]) -> list[int]:
    counts = [0] * (len(edges) - 1)
    for v in values:
        for i in range(len(edges) - 1):
            if edges[i] <= v < edges[i + 1]:
                counts[i] += 1
                break
    return counts


def psi(
    expected: list[int] | dict[str, int], actual: list[int] | dict[str, int], eps: float = 1e-4
) -> float:
    """Population Stability Index between two count distributions."""
    if isinstance(expected, dict) or isinstance(actual, dict):
        e_map = expected if isinstance(expected, dict) else {}
        a_map = actual if isinstance(actual, dict) else {}
        keys = sorted(set(e_map) | set(a_map))
        e_counts = [e_map.get(k, 0) for k in keys]
        a_counts = [a_map.get(k, 0) for k in keys]
    else:
        e_counts, a_counts = list(expected), list(actual)
    e_total, a_total = sum(e_counts), sum(a_counts)
    if e_total == 0 or a_total == 0:
        return 0.0
    value = 0.0
    for e, a in zip(e_counts, a_counts, strict=True):
        pe = max(e / e_total, eps)
        pa = max(a / a_total, eps)
        value += (pa - pe) * math.log(pa / pe)
    return round(value, 4)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


class DriftMonitor:
    def __init__(
        self,
        documents: DocumentRepository,
        extractions: ExtractionRepository,
        reviews: ReviewRepository,
        answers: AnswerRepository,
        invocations: InvocationRepository,
        evaluations: EvaluationRepository,
        thresholds: DriftThresholds,
    ) -> None:
        self._documents = documents
        self._extractions = extractions
        self._reviews = reviews
        self._answers = answers
        self._invocations = invocations
        self._evaluations = evaluations
        self.thresholds = thresholds

    # ------------------------------------------------------------------ snapshot

    def snapshot(self, since: datetime | None = None) -> DriftSnapshot:
        def recent(ts: datetime) -> bool:
            return since is None or ts >= since

        docs = [d for d in self._documents.all() if recent(d.created_at) and d.document_type]
        extractions = [
            e
            for e in self._extractions.all()
            if recent(e.created_at) and e.corrected_by_review_id is None
        ]
        reviews = [r for r in self._reviews.all() if recent(r.created_at)]
        answers = [a for a in self._answers.all() if recent(a.created_at)]
        invocations = [
            i for i in self._invocations.all() if recent(i.created_at) and i.operation != "judge"
        ]

        doc_reviews = [r for r in reviews if r.target_type == ReviewTargetType.DOCUMENT_PROCESSING]
        resolved = [
            r
            for r in reviews
            if r.status in (ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.CORRECTED)
        ]
        ext_conf = [e.overall_confidence for e in extractions]
        schema_failures = sum(
            1 for e in extractions if ReviewReason.SCHEMA_VALIDATION_FAILED in e.review_reasons
        )
        answered = [a for a in answers if not a.refused]
        unsupported = sum(
            1
            for a in answers
            if (a.groundedness and a.groundedness.unsupported_sentences)
            or (a.refusal_reason or "").startswith("answer withheld")
        )
        top_scores = [a.retrieval_scores[0] for a in answers if a.retrieval_scores]
        latencies = [i.latency_ms for i in invocations]
        tokens = [float(i.input_tokens + i.output_tokens) for i in invocations]
        costs = [i.estimated_cost_usd for i in invocations if i.estimated_cost_usd is not None]
        latest_eval = self._evaluations.recent(limit=1)
        eval_extraction = (
            latest_eval[0].metrics.get("extraction", {}).get("normalized_match")
            if latest_eval
            else None
        )

        return DriftSnapshot(
            window_start=since,
            counts={
                "documents": len(docs),
                "extractions": len(extractions),
                "reviews": len(reviews),
                "resolved_reviews": len(resolved),
                "answers": len(answers),
                "invocations": len(invocations),
            },
            categorical={
                "document_type": dict(
                    Counter(d.document_type.value for d in docs if d.document_type)
                ),
            },
            histograms={
                "document_length": histogram(
                    [float(d.char_count or 0) for d in docs], BINS["document_length"]
                ),
                "extraction_confidence": histogram(ext_conf, BINS["extraction_confidence"]),
                "retrieval_top_score": histogram(top_scores, BINS["retrieval_top_score"]),
                "llm_latency_ms": histogram(latencies, BINS["llm_latency_ms"]),
            },
            scalars={
                "review_rate": _rate(len(doc_reviews), len(docs)),
                "human_rejection_rate": _rate(
                    sum(1 for r in resolved if r.status == ReviewStatus.REJECTED), len(resolved)
                ),
                "human_correction_rate": _rate(
                    sum(1 for r in resolved if r.status == ReviewStatus.CORRECTED), len(resolved)
                ),
                "schema_failure_rate": _rate(schema_failures, len(extractions)),
                "unsupported_answer_rate": _rate(unsupported, len(answers)),
                "refusal_rate": _rate(len(answers) - len(answered), len(answers)),
                "groundedness_mean": _mean(
                    [a.groundedness.score for a in answered if a.groundedness]
                ),
                "extraction_confidence_mean": _mean(ext_conf),
                "latency_p95_ms": round(percentile(latencies, 0.95), 3) if latencies else None,
                "tokens_per_call": _mean(tokens),
                "cost_per_call_usd": round(sum(costs) / len(costs), 8) if costs else None,
                "eval_extraction_normalized_match": eval_extraction,
            },
            samples={
                "review_rate": len(docs),
                "human_rejection_rate": len(resolved),
                "human_correction_rate": len(resolved),
                "schema_failure_rate": len(extractions),
                "unsupported_answer_rate": len(answers),
                "refusal_rate": len(answers),
                "groundedness_mean": sum(1 for a in answered if a.groundedness),
                "extraction_confidence_mean": len(ext_conf),
                "latency_p95_ms": len(latencies),
                "tokens_per_call": len(tokens),
                "cost_per_call_usd": len(costs),
            },
            versions={
                "models": sorted({f"{i.provider}:{i.model_name}" for i in invocations}),
                "prompts": sorted(
                    {f"{i.prompt_name}@{i.prompt_version}" for i in invocations if i.prompt_name}
                ),
            },
        )

    # ------------------------------------------------------------------ compare

    def compare(self, current: DriftSnapshot, baseline: DriftSnapshot | None) -> DriftReport:
        if baseline is None:
            return DriftReport(
                has_baseline=False, current=current, metrics=[], alerts=[], status="no_baseline"
            )
        t = self.thresholds
        metrics: list[DriftMetric] = []

        def psi_status(value: float, n_cur: int, n_base: int) -> str:
            if n_cur < t.min_samples or n_base < t.min_samples:
                return "insufficient_data"
            if value >= t.psi.get("alert", 0.25):
                return "alert"
            if value >= t.psi.get("warn", 0.1):
                return "warn"
            return "ok"

        for name in ("document_type",):
            b, c = baseline.categorical.get(name, {}), current.categorical.get(name, {})
            value = psi(b, c)
            metrics.append(
                DriftMetric(
                    name=f"{name}_distribution",
                    kind="psi",
                    baseline=b,
                    current=c,
                    value=value,
                    threshold=t.psi.get("alert"),
                    status=psi_status(value, sum(c.values()), sum(b.values())),
                )
            )
        for name, b_hist in baseline.histograms.items():
            c_hist = current.histograms.get(name, [0] * len(b_hist))
            value = psi(b_hist, c_hist)
            metrics.append(
                DriftMetric(
                    name=f"{name}_distribution",
                    kind="psi",
                    baseline=b_hist,
                    current=c_hist,
                    value=value,
                    threshold=t.psi.get("alert"),
                    status=psi_status(value, sum(c_hist), sum(b_hist)),
                )
            )

        def enough(name: str) -> bool:
            return (
                current.samples.get(name, 0) >= t.min_samples
                and baseline.samples.get(name, 0) >= t.min_samples
            )

        for name, limit in t.rate_delta.items():
            b_val, c_val = baseline.scalars.get(name), current.scalars.get(name)
            if b_val is None or c_val is None or not enough(name):
                metrics.append(
                    DriftMetric(
                        name=name,
                        kind="rate_delta",
                        baseline=b_val,
                        current=c_val,
                        threshold=limit,
                        status="insufficient_data",
                    )
                )
                continue
            delta = round(c_val - b_val, 4)
            # for "higher is better" signals, alert on drops; otherwise on increases
            worse = -delta if name in ("groundedness_mean", "extraction_confidence_mean") else delta
            metrics.append(
                DriftMetric(
                    name=name,
                    kind="rate_delta",
                    baseline=b_val,
                    current=c_val,
                    value=delta,
                    threshold=limit,
                    status="alert" if worse > limit else "ok",
                )
            )

        for name, limit in t.ratio.items():
            b_val, c_val = baseline.scalars.get(name), current.scalars.get(name)
            if not b_val or c_val is None or not enough(name):
                metrics.append(
                    DriftMetric(
                        name=name,
                        kind="ratio",
                        baseline=b_val,
                        current=c_val,
                        threshold=limit,
                        status="insufficient_data",
                    )
                )
                continue
            ratio = round(c_val / b_val, 4)
            metrics.append(
                DriftMetric(
                    name=name,
                    kind="ratio",
                    baseline=b_val,
                    current=c_val,
                    value=ratio,
                    threshold=limit,
                    status="alert" if ratio > limit else "ok",
                )
            )

        for name in ("models", "prompts"):
            new = sorted(set(current.versions.get(name, [])) - set(baseline.versions.get(name, [])))
            metrics.append(
                DriftMetric(
                    name=f"{name}_in_use",
                    kind="version",
                    baseline=baseline.versions.get(name, []),
                    current=current.versions.get(name, []),
                    status="info" if new else "ok",
                    value=float(len(new)),
                )
            )

        alerts = [
            f"{m.name}: {m.status} (value={m.value}, threshold={m.threshold})"
            for m in metrics
            if m.status in ("alert", "warn")
        ]
        alerts += [
            f"{m.name}: new versions {sorted(set(m.current) - set(m.baseline))} — re-run evaluation"
            for m in metrics
            if m.kind == "version" and m.status == "info"
        ]
        statuses = {m.status for m in metrics if m.kind != "version"}
        if "alert" in statuses:
            status = "alert"
        elif "warn" in statuses:
            status = "warn"
        elif statuses <= {"insufficient_data"}:
            status = "insufficient_data"
        else:
            status = "ok"
        return DriftReport(
            has_baseline=True,
            baseline_created_at=baseline.created_at,
            current=current,
            metrics=metrics,
            alerts=alerts,
            status=status,
        )

    def report(self, baseline_path: Path, since: datetime | None = None) -> DriftReport:
        baseline = (
            DriftSnapshot.model_validate_json(baseline_path.read_text())
            if baseline_path.exists()
            else None
        )
        return self.compare(self.snapshot(since), baseline)


def render_markdown(report: DriftReport) -> str:
    baseline = report.baseline_created_at.isoformat() if report.baseline_created_at else "none"
    lines = [
        "# AI System Drift Report",
        "",
        f"- Generated: {report.generated_at.isoformat()}",
        f"- Overall status: **{report.status.upper()}**",
        f"- Baseline: {baseline}",
        f"- Current window counts: {report.current.counts}",
        "",
    ]
    if report.alerts:
        lines += ["## Alerts", ""] + [f"- {a}" for a in report.alerts] + [""]
    lines += [
        "## Metrics",
        "",
        "| Metric | Kind | Baseline | Current | Value | Threshold | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in report.metrics:
        lines.append(
            f"| {m.name} | {m.kind} | {m.baseline} | {m.current} | {m.value} | {m.threshold} | "
            f"{m.status} |"
        )
    lines += ["", "## Current scalars", ""]
    lines += [f"- {k}: {v}" for k, v in report.current.scalars.items()]
    lines += ["", "## Versions in use", ""]
    lines += [f"- {k}: {', '.join(v) or '-'}" for k, v in report.current.versions.items()]
    lines += [
        "",
        "_Notes: PSI compares binned distributions; rates are absolute deltas; ratios compare "
        "current/baseline. Mock-mode token counts are estimates and costs are zero._",
    ]
    return "\n".join(lines) + "\n"
